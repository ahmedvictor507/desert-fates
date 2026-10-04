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
