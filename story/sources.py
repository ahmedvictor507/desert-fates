"""Local source text for beats that carry a "source" pointer.

A beat like {"source": {"book": "dune", "chapters": [15]}} refers to
packs/dune/chapters.json, produced by ingest.py from the player's own copy of
the book. Nothing here is shipped with the repo; if the file is missing every
lookup simply returns nothing and the game runs on the pack's own text.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .pack import ROOT

PACKS = ROOT / "packs"
_WORD = re.compile(r"[a-z’']+")


@lru_cache(maxsize=None)
def load_book(book: str) -> dict:
    """{chapter index: chapter dict} for packs/<book>/chapters.json, or {} if absent."""
    p = PACKS / book / "chapters.json"
    if not p.exists():
        return {}
    return {c["index"]: c for c in json.loads(p.read_text())}


def _chapters(beat: dict) -> list[dict]:
    src = beat.get("source") or {}
    book = load_book(src.get("book", ""))
    return [book[i] for i in src.get("chapters", []) if i in book]


def epigraph(beat: dict) -> str:
    """The first source chapter's epigraph, if the book is available locally."""
    return next((c["epigraph"] for c in _chapters(beat) if c.get("epigraph")), "")


def style_excerpt(beat: dict, max_chars: int = 2000) -> str:
    """The source chunk that best overlaps the beat's own text, trimmed to max_chars.

    Chunks are ~3000-char pieces from ingest; the best match is the one sharing the
    most distinct words with the beat, so the model sees the actual scene's voice.
    """
    chunks = [ch for c in _chapters(beat) for ch in c.get("chunks", [])]
    if not chunks:
        return ""
    want = set(_WORD.findall(beat.get("text", "").lower()))
    best = max(chunks, key=lambda ch: len(want & set(_WORD.findall(ch.lower()))))
    if len(best) <= max_chars:
        return best
    cut = best.rfind("\n\n", 0, max_chars)
    return best[: cut if cut > max_chars // 2 else max_chars]


def copied_span(text: str, source: str, n: int = 12) -> str | None:
    """Return the first run of n words that `text` copies verbatim from `source`, if any."""
    src = _WORD.findall(source.lower())
    grams = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
    words = _WORD.findall(text.lower())
    for i in range(len(words) - n + 1):
        if tuple(words[i:i + n]) in grams:
            return " ".join(words[i:i + n])
    return None
