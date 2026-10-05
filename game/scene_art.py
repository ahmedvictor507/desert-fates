"""Procedural scene banners: no image files, nothing copyrighted.

`draw_scene(surface, rect, place, t)` picks a world (sea world, desert world, industrial
world, space) and modifiers (night, indoors) from keywords in the beat's `place` text, then
paints a gently animated banner. Unknown places get a neutral dusk sky.
"""
from __future__ import annotations

import math
import random
import zlib

import pygame

WORLDS = {
    # keyword hints -> palette
    "sea": dict(words=("caladan", "ocean", "sea "), sky=((70, 110, 150), (170, 200, 210)),
                ground=((30, 70, 90), (40, 95, 110)), accent=(220, 235, 240)),
    "desert": dict(words=("arrakis", "arrakeen", "desert", "sand", "dune", "stilltent", "sietch",
                          "ornithopter", "spice"),
                   sky=((200, 120, 60), (245, 200, 140)), ground=((190, 120, 60), (225, 165, 95)),
                   accent=(255, 235, 200)),
    "industrial": dict(words=("giedi", "harkonnen keep", "baron"), sky=((25, 22, 25), (70, 55, 50)),
                       ground=((20, 18, 18), (45, 38, 35)), accent=(200, 80, 50)),
    "space": dict(words=("frigate", "ship", "heighliner", "aboard"), sky=((8, 8, 18), (25, 25, 45)),
                  ground=((40, 40, 50), (60, 60, 75)), accent=(150, 170, 220)),
}
NEUTRAL = dict(sky=((60, 50, 70), (180, 140, 120)), ground=((80, 60, 50), (120, 90, 70)), accent=(240, 220, 200))
INDOOR_WORDS = ("room", "hall", "study", "house", "residence", "castle", "bedroom", "keep",
                "chamber", "aboard", "floor of")
NIGHT_WORDS = ("night", "dark", "moon")


def classify(place: str) -> tuple[dict, bool, bool]:
    low = f" {place.lower()} "
    world = next((w for w in WORLDS.values() if any(k in low for k in w["words"])), NEUTRAL)
    return world, any(k in low for k in INDOOR_WORDS), any(k in low for k in NIGHT_WORDS)


def _lerp(a, b, f):
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


def _darken(c, f):
    return tuple(int(v * f) for v in c)


def _gradient(surf, rect, top, bottom):
    for y in range(rect.height):
        pygame.draw.line(surf, _lerp(top, bottom, y / max(1, rect.height - 1)),
                         (rect.x, rect.y + y), (rect.right - 1, rect.y + y))


def _outdoor(surf, rect, world, night, t, seed):
    rng = random.Random(seed)
    sky_top, sky_bot = world["sky"]
    if night:
        sky_top, sky_bot = _darken(sky_top, 0.18), _darken(sky_bot, 0.3)
    _gradient(surf, rect, sky_top, sky_bot)
    if night or world is WORLDS["space"]:
        for _ in range(90):
            x, y = rect.x + rng.randrange(rect.width), rect.y + rng.randrange(int(rect.height * 0.7))
            tw = 150 + int(80 * math.sin(t * 2 + x))
            surf.set_at((x, y), (tw, tw, min(255, tw + 30)))
    if world is WORLDS["desert"]:
        # two moons at night, a white sun by day
        if night:
            pygame.draw.circle(surf, (230, 225, 210), (rect.right - 140, rect.y + 45), 18)
            pygame.draw.circle(surf, (200, 195, 185), (rect.right - 90, rect.y + 70), 10)
        else:
            pygame.draw.circle(surf, (255, 250, 230), (rect.right - 160, rect.y + 50), 26)
        base = rect.y + int(rect.height * 0.55)
        for layer in range(4):
            col = world["ground"][0] if layer % 2 else world["ground"][1]
            col = _lerp(col, (255, 230, 190), 0.25 - layer * 0.07)
            if night:
                col = _darken(col, 0.35)
            amp, freq, ph = 14 + layer * 6, 0.006 + layer * 0.002, rng.random() * 6
            pts = [(x, base + layer * 22 + amp * math.sin(x * freq + ph + t * 0.03 * (layer + 1)))
                   for x in range(rect.x, rect.right + 8, 8)]
            pygame.draw.polygon(surf, col, [(rect.x, rect.bottom)] + pts + [(rect.right, rect.bottom)])
    elif world is WORLDS["sea"]:
        horizon = rect.y + int(rect.height * 0.55)
        sea_top, sea_bot = world["ground"]
        if night:
            sea_top, sea_bot = _darken(sea_top, 0.35), _darken(sea_bot, 0.35)
        _gradient(surf, pygame.Rect(rect.x, horizon, rect.width, rect.bottom - horizon), sea_top, sea_bot)
        # cliff and castle silhouette
        cliff = _darken(world["ground"][0], 0.5)
        pygame.draw.polygon(surf, cliff, [(rect.x, rect.bottom), (rect.x, horizon - 40),
                                          (rect.x + 220, horizon - 30), (rect.x + 300, rect.bottom)])
        for i, h in enumerate((70, 95, 60, 80)):
            pygame.draw.rect(surf, cliff, (rect.x + 40 + i * 38, horizon - 30 - h, 26, h))
        for row in range(6):
            y = horizon + 12 + row * 16
            for x in range(rect.x + 320, rect.right, 60):
                off = int(8 * math.sin(t * 1.2 + x * 0.05 + row))
                pygame.draw.line(surf, _lerp(sea_top, world["accent"], 0.35), (x + off, y), (x + off + 22, y), 2)
    elif world is WORLDS["industrial"]:
        base = rect.y + int(rect.height * 0.5)
        for x in range(rect.x, rect.right, 70):
            h = rng.randint(40, 120)
            pygame.draw.rect(surf, world["ground"][1], (x, base - h, 50, rect.bottom - base + h))
            if rng.random() < 0.6:
                glow = 120 + int(60 * math.sin(t * 3 + x))
                pygame.draw.rect(surf, (glow, 50, 30), (x + 18, base - h + 12, 10, 6))
        pygame.draw.rect(surf, world["ground"][0], (rect.x, base + 40, rect.width, rect.bottom - base))
    elif world is WORLDS["space"]:
        pygame.draw.circle(surf, (190, 130, 70), (rect.x + 160, rect.bottom + 60), 140)  # a planet below
    else:
        base = rect.y + int(rect.height * 0.65)
        pygame.draw.rect(surf, world["ground"][0], (rect.x, base, rect.width, rect.bottom - base))


def _indoor_frame(surf, rect, world):
    """Dark wall with an arched window onto the outdoor scene."""
    wall = _darken(world["ground"][0], 0.35)
    win = pygame.Rect(0, 0, int(rect.width * 0.42), int(rect.height * 0.8))
    win.center = (rect.centerx, rect.centery + 10)
    mask = pygame.Surface(rect.size, pygame.SRCALPHA)
    mask.fill((*wall, 255))
    local = win.move(-rect.x, -rect.y)
    pygame.draw.rect(mask, (0, 0, 0, 0), local.inflate(0, -local.width // 2).move(0, local.width // 4))
    pygame.draw.ellipse(mask, (0, 0, 0, 0), (local.x, local.y, local.width, local.width // 2 + 2))
    surf.blit(mask, rect.topleft)
    pygame.draw.line(surf, _darken(wall, 0.6), (win.centerx, win.y + 10), (win.centerx, win.bottom), 4)


def _floor(surf, rect, world, floor_y):
    """A floor for indoor scenes so figures stand on something."""
    base = _darken(world["ground"][0], 0.55)
    _gradient(surf, pygame.Rect(rect.x, floor_y, rect.width, rect.bottom - floor_y), _lerp(base, (90, 80, 70), 0.3), _darken(base, 0.6))
    pygame.draw.line(surf, _lerp(base, (200, 180, 150), 0.35), (rect.x, floor_y), (rect.right, floor_y), 2)
    cx = rect.centerx
    for i in range(-8, 9):          # floor boards in perspective
        pygame.draw.line(surf, _darken(base, 0.75), (cx + i * 60, floor_y), (cx + i * 160, rect.bottom), 1)


def draw_scene(surf: pygame.Surface, rect: pygame.Rect, place: str, t: float, floor_y: int | None = None) -> None:
    world, indoor, night = classify(place or "")
    old_clip = surf.get_clip()
    surf.set_clip(rect)
    _outdoor(surf, rect, world, night, t, seed=zlib.crc32(place.encode()))
    if indoor:
        _indoor_frame(surf, rect, world)
        if floor_y:
            _floor(surf, rect, world, floor_y)
    shade = pygame.Surface((rect.width, 60), pygame.SRCALPHA)
    for y in range(60):
        pygame.draw.line(shade, (0, 0, 0, int(160 * y / 60)), (0, y), (rect.width, y))
    surf.blit(shade, (rect.x, rect.bottom - 60))
    surf.set_clip(old_clip)
