"""Baseline agents. Anything with .act(env) -> str works."""
import random

from engine import world


class RandomAgent:
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def act(self, env) -> str:
        return self.rng.choice(["MOVE N", "MOVE S", "MOVE E", "MOVE W", "GATHER", "DRINK", "REST"])


class ScriptedAgent:
    """Greedy heuristic: grab nearest spice, return to sietch, drink when low."""

    def act(self, env) -> str:
        s, sc = env.engine.state, env.scenario
        if s.form != "human":
            return "REST"
        if s.at_sietch and s.water < sc.start_water - 3:
            return "DRINK"
        target = tuple(s.sietch)
        dist_home = abs(s.x - s.sietch[0]) + abs(s.y - s.sietch[1])
        if s.spice < sc.goal_spice and s.water > dist_home + 8:
            spices = [(x, y) for y in range(sc.height) for x in range(sc.width)
                      if s.grid[y][x] == world.SPICE]
            if spices:
                if s.grid[s.y][s.x] == world.SPICE:
                    return "GATHER"
                target = min(spices, key=lambda p: abs(p[0] - s.x) + abs(p[1] - s.y))
        if (s.x, s.y) == target:
            return "REST"
        if s.x != target[0]:
            return "MOVE E" if target[0] > s.x else "MOVE W"
        return "MOVE S" if target[1] > s.y else "MOVE N"
