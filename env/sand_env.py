"""Gymnasium-style env with text observations for LLM agents.

Gymnasium is optional: if installed we subclass gym.Env, otherwise a plain
class with the same reset()/step() API is used.
"""
from __future__ import annotations

from engine import Engine, load_scenario

try:
    import gymnasium as gym
    _Base = gym.Env
except ImportError:  # keep the core dependency-free
    _Base = object

VIEW = 3  # radius of the local map crop
ACTIONS_HELP = (
    "Actions (reply with exactly one):\n"
    "  MOVE N|S|E|W   GATHER   DRINK   REST   FREEFORM \"<anything you try>\""
)


def render_text(state, scenario, view: int = VIEW) -> str:
    rows = []
    worms = set(state.worms)
    for y in range(state.y - view, state.y + view + 1):
        row = ""
        for x in range(state.x - view, state.x + view + 1):
            if not (0 <= x < scenario.width and 0 <= y < scenario.height):
                row += "#"
            elif (x, y) == (state.x, state.y):
                row += "@"
            elif (x, y) in worms:
                row += "W"
            else:
                row += state.grid[y][x]
        rows.append(row)
    sx, sy = state.sietch
    return (
        f"Turn {state.turn}/{scenario.max_turns} | form={state.form} hp={state.hp} "
        f"water={state.water} spice={state.spice}/{scenario.goal_spice}\n"
        f"Sietch (safe, water) is at dx={sx - state.x} dy={sy - state.y}.\n"
        f"Map ({2 * view + 1}x{2 * view + 1}; @=you W=worm S=spice ^=rock H=sietch .=sand #=edge):\n"
        + "\n".join(rows)
        + "\n" + ACTIONS_HELP
    )


class SandEnv(_Base):
    def __init__(self, scenario: str = "worm_path", seed: int = 0, interpreter=None):
        self.scenario = load_scenario(scenario)
        self.engine = Engine(self.scenario, seed=seed, interpreter=interpreter)
        self._seed = seed

    def reset(self, seed: int | None = None, options=None):
        if seed is not None:
            self._seed = seed
        self.engine.reset(self._seed)
        return self._obs(), {}

    def step(self, action: str):
        info = self.engine.step(action)
        s = self.engine.state
        terminated = s.done and s.ending != f"survived_as_{s.form}"
        truncated = s.done and not terminated
        info["ending"] = s.ending
        return self._obs(), info["reward"], terminated, truncated, info

    def _obs(self) -> str:
        return render_text(self.engine.state, self.scenario)
