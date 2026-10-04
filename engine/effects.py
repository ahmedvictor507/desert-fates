"""Validated effect schema.

The LLM (or a rule) may *propose* an effect, but only this module mutates
state, and only after validation. This keeps free-form actions safe and the
RL reward well defined.
"""
from __future__ import annotations

ALLOWED_KEYS = {"stats", "transform", "unlock", "lock", "flags", "message"}
ALLOWED_STATS = {"hp", "water", "spice"}
MAX_DELTA = 10


class EffectError(ValueError):
    pass


def validate(effect: dict, forms: set[str]) -> dict:
    if not isinstance(effect, dict):
        raise EffectError("effect must be an object")
    extra = set(effect) - ALLOWED_KEYS
    if extra:
        raise EffectError(f"unknown effect keys: {sorted(extra)}")
    out: dict = {}
    for stat, delta in effect.get("stats", {}).items():
        if stat not in ALLOWED_STATS:
            raise EffectError(f"unknown stat {stat!r}")
        if not isinstance(delta, int):
            raise EffectError("stat deltas must be ints")
        out.setdefault("stats", {})[stat] = max(-MAX_DELTA, min(MAX_DELTA, delta))
    t = effect.get("transform")
    if t is not None:
        if t not in forms:
            raise EffectError(f"unknown form {t!r}")
        out["transform"] = t
    for key in ("unlock", "lock"):
        vals = effect.get(key, [])
        if not all(isinstance(v, str) and len(v) <= 40 for v in vals):
            raise EffectError(f"{key} must be a list of short strings")
        if vals:
            out[key] = list(vals)
    flags = effect.get("flags", {})
    if not all(isinstance(k, str) and isinstance(v, (bool, int)) for k, v in flags.items()):
        raise EffectError("flags must map str -> bool/int")
    if flags:
        out["flags"] = dict(flags)
    if "message" in effect:
        out["message"] = str(effect["message"])[:200]
    return out


def apply(state, effect: dict) -> None:
    for stat, delta in effect.get("stats", {}).items():
        setattr(state, stat, getattr(state, stat) + delta)
    if "transform" in effect:
        state.form = effect["transform"]
    state.abilities |= set(effect.get("unlock", []))
    state.abilities -= set(effect.get("lock", []))
    state.flags.update(effect.get("flags", {}))
