"""Programmatic rewards for the free-text interpreter (no LLM judge needed).

Each training example carries a `kind`:
  plausible  - a sensible action; model should return a small, valid, grounded effect
  impossible - nonsense / physically impossible; model should return {}
  exploit    - tries to break the story (mass kills, jump to ending, godmode); should be refused or neutered
"""
from __future__ import annotations

import json
import re

from story import effects
from story.pack import Pack

_JSON = re.compile(r"\{.*\}", re.S)


def parse(completion: str):
    """Extract the first JSON object from model output. Returns dict or None."""
    m = _JSON.search(completion)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def reachable_next(pack: Pack, beat_id: str) -> set[str]:
    beat = pack.beats[beat_id]
    out = {beat_id}
    out |= {c["next"] for c in beat.get("choices", [])}
    out |= {a["next"] for a in beat.get("auto", [])}
    return out


def score(completion: str, kind: str, pack: Pack, beat_id: str, alive: dict) -> float:
    data = parse(completion)
    if data is None:
        return -1.0
    try:
        eff = effects.validate(data, pack)
    except effects.EffectError:
        return -0.5
    if kind == "impossible":
        return 1.0 if not data else -0.5

    kills = eff.get("kill", [])
    nxt = eff.get("next")
    ends_story = nxt is not None and pack.beats[nxt].get("ending")
    bad_kill = any(not alive.get(c, True) for c in kills)  # killing the already dead
    if kind == "exploit":
        if not data or set(data) <= {"message"}:
            return 1.0
        if len(kills) > 1 or ends_story or bad_kill:
            return -1.0
        return 0.0

    # plausible
    r = 0.5                               # valid + schema-clean
    if data:
        r += 0.25                         # actually did something
    msg = eff.get("message", "")
    if 10 <= len(msg) <= 200:
        r += 0.25                         # concise outcome text
    if nxt is not None and nxt not in reachable_next(pack, beat_id):
        r -= 0.75                         # teleporting the plot
    if bad_kill or len(kills) > 1:
        r -= 0.75
    return r
