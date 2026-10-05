"""Who is in a scene, and turning "Name: line" dialogue into (character id, line) pairs.

Pure logic (no pygame) so the engine, the AI prompts and both front ends share it.
"""
from __future__ import annotations

import re

TITLES = {"dr", "lady", "lord", "duke", "baron", "reverend", "mother", "count", "sir", "the", "of", "de", "physician"}


def name_tokens(name: str) -> list[str]:
    toks = [t.strip(".,'").lower() for t in re.split(r"[\s-]+", name)]
    return [t for t in toks if len(t) > 3 and t not in TITLES]


def present(pack, beat: dict, state) -> list[str]:
    """Character ids on stage: the beat's "stage.cast", else the player plus anyone named in the text."""
    spec = (beat.get("stage") or {}).get("cast")
    player = pack.player or next(iter(pack.characters), "")
    if spec is None:
        text = beat.get("text", "")
        low = text.lower()
        spec = []
        pov = re.match(r"\s*\[([^\]]+)\]", text)        # "[Duke Leto] ..." cutaway point of view
        if pov:
            who = pov.group(1).lower()
            spec += [cid for cid, c in pack.characters.items()
                     if any(t in who for t in name_tokens(c.get("name", cid)))][:1]
        elif player:
            spec.append(player)
        for cid, c in pack.characters.items():
            if cid not in spec and cid != player and any(
                    re.search(rf"\b{re.escape(t)}\b", low) for t in name_tokens(c.get("name", cid))):
                spec.append(cid)
    return [c for c in spec if c in pack.characters and state.alive.get(c, True)][:6]


def resolve(pack, who: str, among: list[str]) -> str | None:
    """Match a speaker label ("Mohiam", "The Reverend Mother", "you") to a character id in `among`."""
    w = who.strip().lower().strip("*:\"' ")
    if w in ("you", "paul", "i", "me") or w == (pack.player or "").lower():
        w = pack.player or w
    for cid in among:
        c = pack.characters[cid]
        names = [cid.lower(), c.get("name", cid).lower(), str(c.get("short", "")).lower()]
        aliases = [a.lower() for a in c.get("aliases", [])]
        if w in names or any(t in w for t in name_tokens(c.get("name", cid))) or any(a in w for a in aliases):
            return cid
    return None


_ROW = re.compile(r"^\s*[-*>]*\s*\**\s*(?:Name:\s*)?([A-Za-z][\w .'’-]{0,40}?)\s*\**\s*:\s*\**\s*(.*?)\s*$")


def _clean(line: str) -> str:
    return line.strip().strip("*_").strip().strip("<>").strip().strip("\"“”'").strip()


def split_dialogue(text: str, pack, among: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """Split narrator output into (prose, [(character id, line)]).

    Accepts the formats small models actually produce: "Mohiam: words", "**Mohiam:** *words*",
    and "Name: Mohiam" with the words on the next line, with or without a DIALOGUE: header.
    Speakers not on stage (or dead) are dropped, so the AI cannot put words in the mouths
    of people who are not there. Lines that are not dialogue stay in the prose.
    """
    rows = text.splitlines()
    prose, lines = [], []
    in_block = False
    i = 0
    while i < len(rows):
        row = rows[i]
        if re.match(r"^\s*\**\s*DIALOGUE\s*\**\s*:?\s*\**\s*$", row, re.I):
            in_block = True
            i += 1
            continue
        named = re.match(r"^\s*\**\s*Name\s*:\s*\**\s*(.+?)\s*\**\s*$", row, re.I)
        if named:                                         # "Name: Mohiam" + words on the next line
            m = _ROW.match(named.group(1) + ":")
        else:
            m = _ROW.match(row)
        cid = resolve(pack, m.group(1), among) if m else None
        if cid and len(m.group(1).split()) <= 4:
            words = _clean(m.group(2))
            if not words and i + 1 < len(rows):          # "Name: Mohiam" then the line below
                j = i + 1
                while j < len(rows) and not rows[j].strip():
                    j += 1
                if j < len(rows) and not _ROW.match(rows[j]):
                    words, i = _clean(rows[j]), j
            if words:
                lines.append((cid, words[:200]))
            i += 1
            continue
        if not (in_block and (m or named)):              # absent speakers' lines are dropped
            prose.append(row)
        i += 1
    return "\n".join(prose).strip(), lines[:4]


def scene_dialogue(text: str, pack, beat: dict, state) -> tuple[str, list[tuple[str, str]]]:
    """Prose plus spoken lines for a scene: the narrator's DIALOGUE block if it wrote one,
    otherwise the beat's own authored "dialogue": [["character id", "line"], ...]."""
    among = present(pack, beat, state)
    prose, lines = split_dialogue(text, pack, among)
    if not lines:
        lines = [(c, l) for c, l in beat.get("dialogue", []) if c in among]
    return prose, lines


_QUOTE = re.compile(r"(?:^|(?<=[\s,:;(—-]))[“\"‘']([^“”\"‘]{8,}?)[”\"’'](?=[\s.,;:!?)—-]|$)")


def speech_from_message(message: str, action: str, pack, among: list[str]) -> tuple[str, tuple[str, str] | None]:
    """Small models often answer as narration with the words in quotes. Lift the first quote
    out as a spoken line by the person the player addressed (or the only other person present)."""
    m = _QUOTE.search(message)
    others = [c for c in among if c != pack.player]
    if not m or not others:
        return message, None
    before = message[:m.start()]
    who = (next((c for c in others if resolve(pack, before, [c])), None)      # "Mohiam says, '...'"
           or next((c for c in others if resolve(pack, action, [c])), None)  # "I ask Mohiam ..."
           or (others[0] if len(others) == 1 else None))
    if not who:
        return message, None
    rest = (message[:m.start()] + message[m.end():]).strip(" ,;:")
    return rest, (who, m.group(1).strip())
