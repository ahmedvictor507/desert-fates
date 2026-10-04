"""Story packs: pure data (JSON), no code. Public examples live in stories/,
private/copyrighted ones in packs/ (git-ignored)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = [ROOT / "stories", ROOT / "packs"]


class PackError(ValueError):
    pass


@dataclass
class Pack:
    title: str
    intro: str
    start: str
    beats: dict
    characters: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    freeform_rules: list = field(default_factory=list)  # global keyword rules

    def validate(self) -> None:
        if self.start not in self.beats:
            raise PackError(f"start beat {self.start!r} missing")
        for bid, beat in self.beats.items():
            targets = [c["next"] for c in beat.get("choices", [])]
            targets += [a["next"] for a in beat.get("auto", [])]
            targets += [r["next"] for r in beat.get("freeform_rules", []) if "next" in r]
            for t in targets:
                if t not in self.beats:
                    raise PackError(f"beat {bid!r} points to unknown beat {t!r}")
            has_exit = beat.get("choices") or beat.get("auto") or beat.get("ending")
            if not has_exit:
                raise PackError(f"beat {bid!r} is a dead end (no choices/auto/ending)")
        orphans = sorted(set(self.beats) - self.reachable())
        if orphans:
            raise PackError(f"beats unreachable from {self.start!r}: {orphans}")

    def reachable(self) -> set:
        """Beat ids reachable from start (ignoring conditions)."""
        anywhere = {r["next"] for r in self.freeform_rules if "next" in r}  # global rules fire from any beat
        seen, todo = set(), [self.start, *anywhere]
        while todo:
            bid = todo.pop()
            if bid in seen:
                continue
            seen.add(bid)
            beat = self.beats[bid]
            todo += [c["next"] for c in beat.get("choices", [])]
            todo += [a["next"] for a in beat.get("auto", [])]
            todo += [r["next"] for r in beat.get("freeform_rules", []) if "next" in r]
        return seen


def load_pack(name_or_path: str) -> Pack:
    p = Path(name_or_path)
    if not p.suffix:
        for d in SEARCH_DIRS:
            if (d / f"{name_or_path}.json").exists():
                p = d / f"{name_or_path}.json"
                break
        else:
            raise FileNotFoundError(f"no pack named {name_or_path!r} in stories/ or packs/")
    pack = Pack(**json.loads(p.read_text()))
    pack.validate()
    return pack
