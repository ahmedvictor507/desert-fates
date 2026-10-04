"""Scenario = data-driven description of a world: forms, goals, freeform rules.

Everything a modder needs lives in a JSON file under scenarios/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"

DEFAULT_FORM = {
    "move_speed": 1,
    "water_drain": 1,
    "can_gather": True,
    "worm_safe": False,
    "can_drink": True,
}


@dataclass
class Scenario:
    name: str
    description: str
    width: int = 24
    height: int = 24
    max_turns: int = 80
    worms: int = 2
    spice_patches: int = 10
    start_water: int = 30
    start_hp: int = 10
    goal_spice: int = 5
    forms: dict = field(default_factory=dict)
    freeform_rules: list = field(default_factory=list)
    # ending id -> reward
    endings: dict = field(default_factory=dict)

    def form(self, name: str) -> dict:
        return {**DEFAULT_FORM, **self.forms.get(name, {})}


def load_scenario(name_or_path: str) -> Scenario:
    p = Path(name_or_path)
    if not p.suffix:
        p = SCENARIO_DIR / f"{name_or_path}.json"
    data = json.loads(p.read_text())
    return Scenario(**data)
