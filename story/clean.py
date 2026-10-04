"""Drop non-story matter and split chapter epigraphs. Works on local text only."""
from __future__ import annotations

import re

# Matched against the title and the first line of the chapter text.
_MATTER = re.compile(
    r"^\s*(praise for|other books by|the dune chronicles|contents\b|about the author|"
    r"introduction\b|appendix\b|terminology|cartographic|afterword|when i was writing|"
    r"acknowledg|copyright|title page|also by|ace\s*$|published by)", re.I)
# Attribution line after a quote: "—FROM ...", "—WORDS OF ...", optionally followed by
# uppercase "BY ..."/"FROM ..." continuation lines.
_ATTR = re.compile(r"^—")
_CONT = re.compile(r"^[A-Z0-9 ’'“”\".,:;()\-]{4,}$")


def matter_reason(title: str, text: str) -> str | None:
    first = text.lstrip().split("\n", 1)[0]
    if _MATTER.match(title) or _MATTER.match(first):
        return f"matter: {title or first[:40]}"
    return None


def split_epigraph(text: str) -> tuple[str, str]:
    """Return (epigraph, body). Epigraph = leading quote(s) up to and including the attribution."""
    paras = text.split("\n\n")
    for i, p in enumerate(paras[:16]):
        if _ATTR.match(p.strip()):
            # prose epigraphs are short blocks; verse is many short lines
            if i > 3 and any(len(q) > 160 for q in paras[:i]):
                return "", text
            j = i + 1
            while j < len(paras) and j <= i + 3 and _CONT.match(paras[j].strip()):
                j += 1
            return "\n\n".join(paras[:j]).strip(), "\n\n".join(paras[j:]).strip()
    return "", text
