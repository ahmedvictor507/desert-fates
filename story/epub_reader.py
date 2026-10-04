"""Minimal, dependency-free EPUB reader: spine-ordered chapters as plain text.

Reads a local file only. Output belongs under packs/ (git-ignored); never commit it.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "o": "http://www.idpf.org/2007/opf"}
_BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "blockquote"}
_SKIP = {"script", "style", "head"}


@dataclass
class Chapter:
    index: int
    title: str
    text: str


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.heading, self._in_h, self._skip = [], None, False, 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        if tag in {"h1", "h2", "h3"} and self.heading is None:
            self._in_h = True
            self._h_buf = []
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        if self._in_h and tag in {"h1", "h2", "h3"}:
            self._in_h = False
            self.heading = " ".join("".join(self._h_buf).split()) or None
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._in_h:
            self._h_buf.append(data)


def _html_to_text(html: str):
    p = _Text()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text, p.heading


def read_epub(path: str, min_chars: int = 600) -> list[Chapter]:
    """Return spine-ordered chapters, skipping tiny front/back matter (< min_chars)."""
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", _NS).attrib["full-path"]
        opf = ET.fromstring(z.read(opf_path))
        base = posixpath.dirname(opf_path)
        manifest = {i.attrib["id"]: i.attrib["href"] for i in opf.findall(".//o:manifest/o:item", _NS)}
        chapters = []
        for ref in opf.findall(".//o:spine/o:itemref", _NS):
            href = manifest.get(ref.attrib["idref"])
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
            try:
                raw = z.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            text, heading = _html_to_text(raw)
            if len(text) < min_chars:
                continue
            idx = len(chapters) + 1
            chapters.append(Chapter(idx, heading or f"Section {idx}", text))
    return chapters


def split_scenes(text: str, max_chars: int = 3000) -> list[str]:
    """Split a chapter into scene-sized chunks on paragraph boundaries (for local-LLM context limits)."""
    out, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) > max_chars:
            out.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur.strip())
    return out


# --------------------------------------------------------------- structured read
# Uses the book's own table of contents and CSS classes instead of guessing from text.
_CHAPTER_LABEL = re.compile(r"^\s*(chapter|prologue|epilogue)\b", re.I)
_PART_LABEL = re.compile(r"^\s*(book|part)\b", re.I)
_EPI_QUOTE = re.compile(r"epigraph", re.I)
_EPI_SOURCE = re.compile(r"epigraph.?source|center01", re.I)
_SCENE_BREAK = re.compile(r"space-break|transition", re.I)
_LEAF = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"}


@dataclass
class BookChapter:
    index: int        # 1-based order in the whole book
    part: str         # e.g. "Book One: Dune" ("" if the book has no parts)
    title: str        # TOC label, e.g. "Chapter 01"
    epigraph: str
    source: str       # epigraph attribution, e.g. 'FROM "MANUAL OF MUAD'DIB" BY THE PRINCESS IRULAN'
    scenes: list      # list[str]; split at marked scene breaks only

    @property
    def text(self) -> str:
        return "\n\n".join(self.scenes)


class _Blocks(HTMLParser):
    """Flatten xhtml into [(classes, text)] paragraphs; classes include enclosing divs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self._stack, self._buf, self._skip = [], [], [], 0

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        cls = " ".join(c for _, c in self._stack if c)
        if text or _SCENE_BREAK.search(cls):
            self.blocks.append((cls, text))
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        if tag == "br":
            self._buf.append("\n")
            return
        if tag in _LEAF or tag in {"div", "blockquote", "hr"}:
            self._flush()
            if tag == "hr":
                self.blocks.append(("space-break", ""))
                return
            self._stack.append((tag, dict(attrs).get("class", "")))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._buf.append("\n")
        elif tag == "hr":
            self._flush()
            self.blocks.append(("space-break", ""))

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        if tag in _LEAF or tag in {"div", "blockquote"}:
            self._flush()
            for i in range(len(self._stack) - 1, -1, -1):
                if self._stack[i][0] == tag:
                    del self._stack[i:]
                    break

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)


def _toc(z: zipfile.ZipFile, opf, base: str, manifest: dict) -> list[tuple[str, str]]:
    """[(file path, label)] from the EPUB3 nav's toc list, falling back to the EPUB2 NCX."""
    nav = next((i.attrib["href"] for i in opf.findall(".//o:manifest/o:item", _NS)
                if "nav" in i.attrib.get("properties", "")), None)
    out = []
    if nav:
        path = posixpath.normpath(posixpath.join(base, unquote(nav)))
        html = z.read(path).decode("utf-8", errors="replace")
        m = re.search(r'<nav[^>]*epub:type="toc".*?</nav>', html, re.S)
        html = m.group(0) if m else html
        for href, label in re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S):
            f = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(href.split("#")[0])))
            out.append((f, " ".join(re.sub(r"<[^>]+>", " ", label).split())))
    if not out:
        ncx = next((h for h in manifest.values() if h.endswith(".ncx")), None)
        if ncx:
            path = posixpath.normpath(posixpath.join(base, unquote(ncx)))
            x = z.read(path).decode("utf-8", errors="replace")
            for label, src in re.findall(r"<navPoint.*?<text>(.*?)</text>.*?<content src=\"([^\"]*)\"", x, re.S):
                f = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(src.split("#")[0])))
                out.append((f, label.strip()))
    return out


def _split_chapter(blocks) -> tuple[str, str, list]:
    """(epigraph, source, scenes) from a chapter's paragraph blocks."""
    epi_end, src = 0, []
    for i, (cls, text) in enumerate(blocks[:25]):
        if _EPI_SOURCE.search(cls) or (not _EPI_QUOTE.search(cls) and text.startswith("—") and i < 12):
            j = i
            while j < len(blocks) and (j == i or _EPI_SOURCE.search(blocks[j][0])):
                src.append(blocks[j][1])
                j += 1
            epi_end = j
            break
    epigraph = "\n\n".join(t for _, t in blocks[:epi_end] if t)
    scenes, cur = [], []
    for cls, text in blocks[epi_end:]:
        if _SCENE_BREAK.search(cls):
            if cur:
                scenes.append("\n\n".join(cur))
            cur = []
        elif text:
            cur.append(text)
    if cur:
        scenes.append("\n\n".join(cur))
    source = " ".join(" ".join(src).replace("\n", " ").lstrip("—").split())
    return epigraph, source, scenes


def read_book(path: str) -> list[BookChapter]:
    """Story chapters in reading order, labelled from the book's TOC.

    Only TOC entries named Chapter/Prologue/Epilogue count as story; front and back matter
    (praise, introductions, appendices, glossary...) is dropped. Spine files that are not in
    the TOC are continuations and get merged into the preceding chapter.
    Returns [] if the TOC has no chapter entries (use read_epub + clean as a fallback).
    """
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", _NS).attrib["full-path"]
        opf = ET.fromstring(z.read(opf_path))
        base = posixpath.dirname(opf_path)
        manifest = {i.attrib["id"]: i.attrib["href"] for i in opf.findall(".//o:manifest/o:item", _NS)}
        toc = _toc(z, opf, base, manifest)
        labels = {}
        for f, label in toc:
            labels.setdefault(f, label)
        if not any(_CHAPTER_LABEL.match(l) for _, l in toc):
            return []
        groups, part, cur = [], "", None
        for ref in opf.findall(".//o:spine/o:itemref", _NS):
            href = manifest.get(ref.attrib["idref"])
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
            label = labels.get(name)
            if label is not None:
                if _PART_LABEL.match(label) and not _CHAPTER_LABEL.match(label):
                    part, cur = label, None
                    continue
                if re.search(r"excerpt", label, re.I) and not re.match(r"\s*appendix", label, re.I):
                    label = "Interlude"
                cur = [part, label, []] if _CHAPTER_LABEL.match(label) or label == "Interlude" else None
                if cur:
                    groups.append(cur)
            try:
                fp = _Blocks()
                fp.feed(z.read(name).decode("utf-8", errors="replace"))
                fp._flush()
            except KeyError:
                continue
            if label is None:
                first = next((c for c, txt in fp.blocks if txt), "")
                if re.search(r"head", first, re.I) or "excerpt" in name.lower():
                    # in-world document between chapters (e.g. a recovered journal excerpt)
                    groups.append([part, "Interlude", list(fp.blocks)])
                    cur = None
                    continue
                if sum(len(txt) for _, txt in fp.blocks) < 300:
                    continue  # divider page such as "APPENDIXES"
            if cur is not None:
                cur[2].extend(fp.blocks)
    out = []
    for i, (part, title, blocks) in enumerate(groups, 1):
        if title == "Interlude":   # in-world document: keep whole, no epigraph split
            epigraph, source, scenes = "", "", [t for _, t in blocks if t] and ["\n\n".join(t for _, t in blocks if t)]
        else:
            epigraph, source, scenes = _split_chapter(blocks)
        if not scenes and epigraph:   # e.g. an epilogue that is a single poem
            epigraph, scenes = "", [epigraph]
        out.append(BookChapter(i, part, title, epigraph, source, scenes))
    return out
