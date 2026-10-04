"""Seeded procedural world generation."""
from __future__ import annotations

import random

SAND, ROCK, SPICE, SIETCH = ".", "^", "S", "H"
WORM_BLOCKED = {ROCK, SIETCH}


def generate(width: int, height: int, spice_patches: int, rng: random.Random):
    grid = [[SAND] * width for _ in range(height)]
    # rock outcrops
    for _ in range(max(3, width * height // 60)):
        cx, cy = rng.randrange(width), rng.randrange(height)
        for _ in range(rng.randint(3, 8)):
            x = min(width - 1, max(0, cx + rng.randint(-2, 2)))
            y = min(height - 1, max(0, cy + rng.randint(-2, 2)))
            grid[y][x] = ROCK
    # sietch (safe base with water) in a corner region
    sx, sy = rng.randint(1, 3), rng.randint(1, 3)
    grid[sy][sx] = SIETCH
    # spice, away from sietch
    placed = 0
    while placed < spice_patches:
        x, y = rng.randrange(width), rng.randrange(height)
        if grid[y][x] == SAND and abs(x - sx) + abs(y - sy) > 5:
            grid[y][x] = SPICE
            placed += 1
    return grid, (sx, sy)
