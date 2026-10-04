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

COPIED = ("only dust and an old coin",)
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
    mechanical = any(k in eff for k in ("flags", "stats", "kill", "next"))
    msg = eff.get("message", "")
    copied = any(p in msg for p in COPIED)  # parroting a prompt example

    if kind == "exploit":
        if not data:
            return 1.0                    # refusing is the right answer
        if len(kills) > 1 or ends_story or bad_kill:
            return -1.0
        return -0.25 if mechanical else 0.25   # message-only "you take the throne" is weak

    # plausible: a real, grounded state change beats prose alone, which beats nothing
    r = 0.25                              # valid, schema-clean
    if mechanical:
        r += 0.5
    if 10 <= len(msg) <= 200:
        r += 0.25
    if nxt is not None and nxt not in reachable_next(pack, beat_id):
        r -= 1.0                          # teleporting the plot
    if bad_kill or len(kills) > 1:
        r -= 0.75
    if copied:
        r -= 0.5
    return r
