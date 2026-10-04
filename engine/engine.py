"""Deterministic rules engine. No rendering, no I/O: safe to run headless."""
from __future__ import annotations

import random
import re

from . import effects, world
from .interpreter import RuleInterpreter
from .scenario import Scenario
from .state import GameState

DIRS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
_FREEFORM = re.compile(r'^\s*FREEFORM\b\s*"?(.*?)"?\s*$', re.I | re.S)
_MOVE = re.compile(r"^\s*MOVE\s+([NSEW])\b", re.I)


class Engine:
    def __init__(self, scenario: Scenario, seed: int = 0, interpreter=None):
        self.scenario = scenario
        self.interpreter = interpreter or RuleInterpreter()
        self.reset(seed)

    # ------------------------------------------------------------------ setup
    def reset(self, seed: int | None = None) -> GameState:
        if seed is not None:
            self.seed = seed
        self.rng = random.Random(self.seed)
        sc = self.scenario
        grid, sietch = world.generate(sc.width, sc.height, sc.spice_patches, self.rng)
        s = GameState(grid=grid, sietch=sietch, x=sietch[0], y=sietch[1],
                      hp=sc.start_hp, water=sc.start_water)
        for _ in range(sc.worms):
            while True:
                wx, wy = self.rng.randrange(sc.width), self.rng.randrange(sc.height)
                if grid[wy][wx] not in world.WORM_BLOCKED and abs(wx - sietch[0]) + abs(wy - sietch[1]) > 8:
                    s.worms.append((wx, wy))
                    break
        self.state = s
        return s

    # ------------------------------------------------------------------- step
    def step(self, action: str) -> dict:
        """Apply one action. Returns {reward, events, valid}."""
        s, sc = self.state, self.scenario
        info = {"reward": -0.01, "events": [], "valid": True}
        if s.done:
            info["valid"] = False
            return info
        form = sc.form(s.form)
        ev = info["events"]
        spice_before = s.spice

        a = action.strip()
        up = a.upper()
        m_move, m_free = _MOVE.match(a), _FREEFORM.match(a)
        if m_move:
            dx, dy = DIRS[m_move.group(1).upper()]
            moved = 0
            for _ in range(form["move_speed"]):
                nx, ny = s.x + dx, s.y + dy
                if 0 <= nx < sc.width and 0 <= ny < sc.height:
                    s.x, s.y = nx, ny
                    moved += 1
            if not moved:
                self._invalid(info, "You hit the edge of the world.")
        elif up == "GATHER":
            if not form["can_gather"]:
                self._invalid(info, f"As a {s.form} you cannot gather spice.")
            elif s.grid[s.y][s.x] == world.SPICE:
                s.grid[s.y][s.x] = world.SAND
                s.spice += 1
                ev.append("You gather spice.")
            else:
                self._invalid(info, "There is no spice here.")
        elif up == "DRINK":
            if s.at_sietch and form["can_drink"]:
                s.water = sc.start_water
                ev.append("You drink deeply at the sietch.")
            else:
                self._invalid(info, "There is no water here.")
        elif up == "REST":
            s.hp = min(sc.start_hp, s.hp + 1)
        elif m_free:
            self._freeform(m_free.group(1), info)
        else:
            self._invalid(info, f"Unknown action: {a[:40]!r}")

        self._world_turn(form, info)
        info["reward"] += 0.5 * (s.spice - spice_before)
        self._check_end(info)
        s.log.extend(ev)
        return info

    # --------------------------------------------------------------- internals
    def _invalid(self, info, msg):
        info["valid"] = False
        info["reward"] -= 0.05
        info["events"].append(msg)

    def _freeform(self, text, info):
        proposal = self.interpreter.interpret(text, self.state, self.scenario)
        if proposal is None:
            self._invalid(info, "Nothing happens.")
            return
        try:
            eff = effects.validate(proposal, set(self.scenario.forms) | {"human"})
        except effects.EffectError as e:
            self._invalid(info, f"The world rejects that ({e}).")
            return
        effects.apply(self.state, eff)
        if "message" in eff:
            info["events"].append(eff["message"])

    def _world_turn(self, form, info):
        s, sc = self.state, self.scenario
        s.turn += 1
        s.water -= form["water_drain"]
        s.hp = min(s.hp, sc.start_hp)
        if s.water <= 0:
            s.hp -= 2
            info["events"].append("Thirst burns you.")
        s.water = max(0, min(sc.start_water, s.water))
        # worms hunt anything standing on open sand that is not kin
        on_sand = s.grid[s.y][s.x] not in world.WORM_BLOCKED
        hunting = on_sand and not form["worm_safe"]
        moved = []
        for wx, wy in s.worms:
            if hunting:
                step = ((s.x > wx) - (s.x < wx), 0) if s.x != wx else (0, (s.y > wy) - (s.y < wy))
            else:
                step = self.rng.choice(list(DIRS.values()) + [(0, 0)])
            nx = max(0, min(sc.width - 1, wx + step[0]))
            ny = max(0, min(sc.height - 1, wy + step[1]))
            blocked = s.grid[ny][nx] in world.WORM_BLOCKED
            moved.append((wx, wy) if blocked else (nx, ny))
        s.worms = moved
        if hunting and (s.x, s.y) in s.worms:
            s.hp = 0
            info["events"].append("A worm swallows you whole.")

    def _check_end(self, info):
        s, sc = self.state, self.scenario
        ending = None
        if s.hp <= 0:
            ending = "death"
        elif s.form == "human" and s.spice >= sc.goal_spice and s.at_sietch:
            ending = "sietch_escape"
        elif s.turn >= sc.max_turns:
            ending = f"survived_as_{s.form}"
        if ending:
            s.done, s.ending = True, ending
            info["reward"] += sc.endings.get(ending, 0.0)
            info["events"].append(f"Ending: {ending}")
