"""Validated story effects. Authors, rules and LLMs may *propose* effects;
only this module changes state, and only after validation."""
from __future__ import annotations

ALLOWED_KEYS = {"flags", "stats", "kill", "revive", "message", "next"}
MAX_DELTA = 5


class EffectError(ValueError):
    pass


def validate(effect: dict, pack) -> dict:
    if not isinstance(effect, dict):
        raise EffectError("effect must be an object")
    extra = set(effect) - ALLOWED_KEYS
    if extra:
        raise EffectError(f"unknown effect keys: {sorted(extra)}")
    out: dict = {}
    flags = effect.get("flags", {})
    if not all(isinstance(k, str) and len(k) <= 40 and isinstance(v, (bool, int)) for k, v in flags.items()):
        raise EffectError("flags must map short str -> bool/int")
    if flags:
        out["flags"] = dict(flags)
    for stat, d in effect.get("stats", {}).items():
        if stat not in pack.stats:
            raise EffectError(f"unknown stat {stat!r}")
        if not isinstance(d, int):
            raise EffectError("stat deltas must be ints")
        out.setdefault("stats", {})[stat] = max(-MAX_DELTA, min(MAX_DELTA, d))
    for key in ("kill", "revive"):
        ids = effect.get(key, [])
        for cid in ids:
            if cid not in pack.characters:
                raise EffectError(f"unknown character {cid!r}")
        if ids:
            out[key] = list(ids)
    if "next" in effect:
        if effect["next"] not in pack.beats:
            raise EffectError(f"unknown beat {effect['next']!r}")
        out["next"] = effect["next"]
    if "message" in effect:
        out["message"] = str(effect["message"])[:300]
    return out


def apply(state, effect: dict) -> None:
    state.flags.update(effect.get("flags", {}))
    for stat, d in effect.get("stats", {}).items():
        state.stats[stat] = state.stats.get(stat, 0) + d
    for cid in effect.get("kill", []):
        state.alive[cid] = False
    for cid in effect.get("revive", []):
        state.alive[cid] = True


def conditions_met(when: dict | None, state) -> bool:
    if not when:
        return True
    for k, v in when.get("flags", {}).items():
        if state.flags.get(k, False) != v:
            return False
    if any(not state.alive.get(c, True) for c in when.get("alive", [])):
        return False
    if any(state.alive.get(c, True) for c in when.get("dead", [])):
        return False
    for stat, minimum in when.get("stat_min", {}).items():
        if state.stats.get(stat, 0) < minimum:
            return False
    return True
