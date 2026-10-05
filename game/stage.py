"""Characters and props on the scene, drawn procedurally (no image files).

A Stage is built from a beat: who is present (the beat's optional "stage": {"cast": [...],
"props": [...]} or, if absent, names and keywords found in the text), where they stand, and
how they move. When the player picks a choice, `Stage.exit(label)` turns the choice's verb
into motion: running off, lunging, walking out together, stepping back, or holding still.

Character looks come from the pack ("characters": {"id": {"look": {...}}}), falling back to a
stable look derived from the id, so any story gets a cast without extra work.
"""
from __future__ import annotations

import math
import re
import zlib

import pygame

from story.cast import TITLES, present

DEFAULT_LOOK = {"robe": (90, 80, 70), "trim": (180, 150, 90), "skin": (225, 190, 160), "hair": (60, 45, 35),
                "hood": False, "build": 1.0, "height": 1.0, "float": False, "hunch": False,
                "cape": False, "weapon": None, "long_robe": True}
ROBES = [(70, 90, 70), (90, 60, 50), (60, 70, 100), (100, 90, 60), (80, 60, 90), (50, 50, 55), (120, 100, 80)]
HAIRS = [(40, 30, 25), (90, 60, 35), (150, 120, 80), (20, 20, 20), (120, 50, 30), (170, 170, 170)]
SKINS = [(235, 200, 170), (210, 170, 135), (180, 135, 100), (140, 100, 70)]

PROP_WORDS = {
    "box": ["the box", "small box"], "seeker": ["hunter-seeker"], "globe": ["globe"],
    "table": ["dinner", "banquet", "chained to a table", "dining"], "ornithopter": ["ornithopter", "'thopter"],
    "crawler": ["crawler"], "worm": ["wormsign", "leviathan", "the worm "], "tent": ["stilltent"],
    "fire": ["burn", "flames", "on fire"], "shield": ["shield"],
}
GROUND, FIG_H = 0.76, 0.22   # feet line and figure height, as fractions of window height

# choice verbs -> exit motion
MOTIONS = [
    ("run", r"\b(run|flee|escape|slip (out|away)|vanish|leave|walk away|go renegade|take the fleet)\b"),
    ("lunge", r"\b(attack|fight|strike|stab|kill|bite|snatch|grab|catch|stand and fight|rush)\b"),
    ("together", r"\b(go with|follow|ride|save|accept|join|escape into|together|go to|take the)\b"),
    ("back", r"\b(pull|withdraw|surrender|turn from|step back|refuse|hide)\b"),
    ("speak", r"\b(tell|ask|beg|urge|warn|bargain|speak|draw .* aside|report|offer)\b"),
    ("still", r"\b(wait|freeze|endure|keep|watch|listen|let it pass|pretend|stay|hold)\b"),
]


def motion_for(label: str) -> str:
    low = label.lower()
    for name, pat in MOTIONS:
        if re.search(pat, low):
            return name
    return "walk"


def look_for(cid: str, char: dict) -> dict:
    h = zlib.crc32(cid.encode())
    look = dict(DEFAULT_LOOK, robe=ROBES[h % len(ROBES)], hair=HAIRS[(h >> 4) % len(HAIRS)],
                skin=SKINS[(h >> 8) % len(SKINS)])
    for k, v in (char.get("look") or {}).items():
        look[k] = tuple(v) if isinstance(v, list) else v
    return look


def short_name(cid: str, char: dict) -> str:
    """Name tag text: the pack's "short" name, the full name if short, else its last real word."""
    name = char.get("name", cid)
    if char.get("short"):
        return char["short"]
    if len(name) <= 14:
        return name
    toks = [t for t in re.split(r"\s+", name) if t.strip(".,").lower() not in TITLES]
    return toks[-1] if toks else name


def detect_props(beat: dict) -> list[str]:
    low = f" {beat.get('text', '').lower()} {beat.get('place', '').lower()} "
    return [p for p, words in PROP_WORDS.items() if any(w in low for w in words)]


# ------------------------------------------------------------------- drawing
def _darker(c, f=0.65):
    return tuple(int(v * f) for v in c)


def draw_figure(surf, x, y, h, look, t, mode="idle", facing=1, alpha=255, phase=0.0):
    """Draw a robed figure standing with feet at (x, y), `h` pixels tall."""
    s = h / 180 * look["height"]
    b = look["build"]
    W, H = int(140 * s * max(1, b)), int(220 * s)
    fig = pygame.Surface((W, H), pygame.SRCALPHA)
    cx, fy = W // 2, H - int(8 * s)
    if look["float"]:
        fy -= int((10 + 4 * math.sin(t * 2 + phase)) * s)
    walk = mode in ("walk", "run")
    speed = 9 if mode == "run" else 6
    stride = math.sin(t * speed + phase) if walk else 0.0
    lean = {"run": 10, "lunge": 16, "back": -6}.get(mode, 0) * s
    breath = math.sin(t * 1.6 + phase) * 1.2 * s
    top = fy - 150 * s + breath + (8 * s if look["hunch"] else 0)

    # legs (hidden under long robes unless moving fast)
    if not look["float"]:
        for side in (-1, 1):
            off = side * stride * 10 * s
            pygame.draw.line(fig, _darker(look["robe"], 0.45), (cx + side * 6 * s, fy - 45 * s),
                             (cx + side * 6 * s + off, fy - 2), max(2, int(9 * s)))
    # cape behind
    if look["cape"]:
        sway = math.sin(t * 2 + phase) * 4 * s - lean * 0.5
        pygame.draw.polygon(fig, _darker(look["trim"], 0.55), [
            (cx - 18 * s * b, top + 22 * s), (cx + 18 * s * b, top + 22 * s),
            (cx + 26 * s * b - sway, fy - 12 * s), (cx - 26 * s * b - sway, fy - 12 * s)])
    # robe body
    hem = fy - (6 if look["long_robe"] else 40) * s
    body = [(cx - 17 * s * b + lean * 0.3, top + 22 * s), (cx + 17 * s * b + lean * 0.3, top + 22 * s),
            (cx + 27 * s * b, hem), (cx - 27 * s * b, hem)]
    pygame.draw.polygon(fig, look["robe"], body)
    pygame.draw.line(fig, look["trim"], (cx - 20 * s * b, top + 70 * s), (cx + 20 * s * b, top + 70 * s),
                     max(2, int(4 * s)))
    pygame.draw.line(fig, look["trim"], (cx + lean * 0.3, top + 24 * s), (cx, hem), max(1, int(2 * s)))
    # arms
    for side in (-1, 1):
        sh = (cx + side * 16 * s * b + lean * 0.3, top + 28 * s)
        if mode == "lunge" and side == 1:
            hand = (sh[0] + 52 * s, sh[1] + 6 * s)
        elif mode == "speak" and side == 1:
            hand = (sh[0] + 34 * s, sh[1] + 18 * s + math.sin(t * 5) * 4 * s)
        else:
            sw = -side * stride * 14 * s
            hand = (sh[0] + side * 4 * s + sw, sh[1] + 52 * s)
        pygame.draw.line(fig, _darker(look["robe"], 0.8), sh, hand, max(3, int(9 * s)))
        pygame.draw.circle(fig, look["skin"], hand, max(2, int(5 * s)))
        if side == 1 and look["weapon"]:
            tip = (hand[0] + (34 if look["weapon"] == "sword" else 16) * s, hand[1] - 10 * s)
            col = (230, 235, 240) if look["weapon"] != "crysknife" else (235, 225, 200)
            pygame.draw.line(fig, col, hand, tip, max(1, int(3 * s)))
    # head
    hx, hy = cx + lean * 0.5 + (6 * s if look["hunch"] else 0), top + 6 * s
    r = 15 * s
    if look["hood"]:
        pygame.draw.circle(fig, _darker(look["robe"], 0.8), (hx, hy), r * 1.35)
    pygame.draw.circle(fig, look["skin"], (hx, hy), r)
    if look["hood"]:
        pygame.draw.arc(fig, _darker(look["robe"], 0.8), (hx - r * 1.35, hy - r * 1.35, r * 2.7, r * 2.7),
                        0.2, math.pi - 0.2, max(3, int(9 * s)))
    elif look["hair"]:
        pygame.draw.ellipse(fig, look["hair"], (hx - r, hy - r * 1.05, r * 2, r * 1.1))
    pygame.draw.circle(fig, (30, 30, 40) if not look.get("blue_eyes") else (40, 90, 220),
                       (hx + 6 * s, hy - 1 * s), max(1, int(2.2 * s)))
    if look["float"]:
        glow = pygame.Surface((int(70 * s * b), int(16 * s)), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (120, 200, 255, 90), glow.get_rect())
        fig.blit(glow, (cx - glow.get_width() // 2, H - int(16 * s)))
    if facing < 0:
        fig = pygame.transform.flip(fig, True, False)
    if alpha < 255:
        fig.set_alpha(alpha)
    # ground shadow
    sh = pygame.Surface((int(70 * s * b), int(14 * s)), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, int(70 * alpha / 255)), sh.get_rect())
    surf.blit(sh, (x - sh.get_width() // 2, y - sh.get_height() // 2))
    surf.blit(fig, (x - W // 2, y - fy))


class Actor:
    def __init__(self, cid, name, look, x, y, h, facing=1):
        self.cid, self.name, self.look = cid, name, look
        self.x, self.y, self.h, self.facing = x, y, h, facing
        self.tx = x
        self.speed = 160.0
        self.alpha, self.ta = 0.0, 255.0
        self.mode = "idle"
        self.pose = None          # forced pose (lunge/back/speak) overriding idle
        self.phase = (zlib.crc32(cid.encode()) % 100) / 15

    def update(self, dt):
        d = self.tx - self.x
        if abs(d) > 1:
            step = math.copysign(min(abs(d), self.speed * dt), d)
            self.x += step
            self.facing = 1 if d > 0 else -1
            self.mode = "run" if self.speed > 250 else "walk"
        else:
            self.mode = self.pose or "idle"
        self.alpha += (self.ta - self.alpha) * min(1, dt * 4)

    def draw(self, surf, t, font=None):
        draw_figure(surf, int(self.x), int(self.y), self.h, self.look, t, self.mode, self.facing,
                    int(self.alpha), self.phase)
        if font and self.alpha > 200 and self.mode == "idle":
            tag = font.render(self.name, True, (235, 225, 205))
            tag.set_alpha(int(self.alpha * 0.8))
            surf.blit(tag, (self.x - tag.get_width() // 2, self.y + 8))


# --------------------------------------------------------------------- props
def draw_prop(surf, name, w, ground, t, stage):
    p = stage.player_actor()
    if name == "box":
        x = int((p.x if p else w * 0.4) + 70)
        pygame.draw.rect(surf, (60, 40, 30), (x - 26, ground - 40, 52, 40), border_radius=4)
        pygame.draw.rect(surf, (200, 160, 80), (x - 26, ground - 40, 52, 40), 2, border_radius=4)
        pygame.draw.rect(surf, (25, 15, 10), (x - 10, ground - 30, 20, 8))
    elif name == "seeker" and p:
        if stage.seeker_down:
            pygame.draw.line(surf, (200, 200, 210), (p.x + 30, p.y - 2), (p.x + 44, p.y - 6), 2)
            return
        hx = p.x + 70 * math.sin(t * 2.3) + 20
        hy = p.y - p.h - 30 + 22 * math.sin(t * 3.7)
        glow = pygame.Surface((30, 30), pygame.SRCALPHA)
        pygame.draw.circle(glow, (180, 220, 255, 70), (15, 15), 14)
        surf.blit(glow, (hx - 15, hy - 15))
        pygame.draw.line(surf, (220, 230, 240), (hx - 8, hy), (hx + 8, hy - 2), 3)
    elif name == "globe":
        x, y = int(w * 0.5), ground - 120
        pygame.draw.line(surf, (90, 70, 50), (x, y + 40), (x, ground), 6)
        pygame.draw.circle(surf, (170, 130, 80), (x, y), 40)
        for i in range(3):
            off = int(((t * 20 + i * 27) % 80) - 40)
            pygame.draw.line(surf, (140, 100, 60), (x + off, y - 36 + abs(off) // 3), (x + off, y + 36 - abs(off) // 3), 2)
        pygame.draw.circle(surf, (230, 200, 140), (x, y), 40, 2)
    elif name == "table":
        x0, x1 = int(w * 0.25), int(w * 0.75)
        pygame.draw.rect(surf, (70, 45, 30), (x0, ground - 60, x1 - x0, 14), border_radius=3)
        for x in (x0 + 20, x1 - 30):
            pygame.draw.rect(surf, (55, 35, 25), (x, ground - 46, 10, 46))
        for i in range(5):
            cx = x0 + 60 + i * (x1 - x0 - 120) // 4
            pygame.draw.rect(surf, (230, 220, 200), (cx - 3, ground - 82, 6, 22))
            fl = 6 + 2 * math.sin(t * 9 + i)
            pygame.draw.ellipse(surf, (255, 190, 80), (cx - 4, ground - 82 - fl * 1.6, 8, fl * 1.6))
    elif name == "ornithopter":
        span = w + 400
        x = ((t * 140) % span) - 200
        y = ground - 330 + 20 * math.sin(t * 0.8)
        pygame.draw.ellipse(surf, (60, 60, 65), (x - 40, y - 10, 80, 22))
        pygame.draw.line(surf, (60, 60, 65), (x - 40, y), (x - 80, y - 4), 5)
        flap = 18 * math.sin(t * 22)
        pygame.draw.line(surf, (110, 110, 120), (x - 10, y - 4), (x - 50, y - 20 - flap), 3)
        pygame.draw.line(surf, (110, 110, 120), (x + 10, y - 4), (x + 50, y - 20 - flap), 3)
    elif name == "crawler":
        x, y = int(w * 0.62), ground - 150
        pygame.draw.rect(surf, (110, 95, 80), (x - 60, y - 34, 120, 34), border_radius=4)
        pygame.draw.rect(surf, (60, 50, 45), (x - 66, y - 6, 132, 14), border_radius=6)
        for i in range(6):
            puff = (t * 30 + i * 17) % 60
            pygame.draw.circle(surf, (220, 180, 130), (x + 70 + puff, y - 20 - puff * 0.6), int(6 + puff * 0.25))
    elif name == "worm":
        # rears up out of the sand: thick ringed body curving up to an open, toothed maw
        rise = min(1.0, (t - stage.t0) / 4.0) if stage.t0 is not None else 1.0
        bx, by = w * 0.86, ground - 140
        sway = 10 * math.sin(t * 0.9)
        n = 16
        pts = []
        for i in range(n):
            f = i / (n - 1)
            px = bx - 170 * f * f + sway * f
            py = by - 300 * rise * math.sin(f * math.pi * 0.55)
            pts.append((px, py, 58 - 14 * f))
        pygame.draw.ellipse(surf, (175, 125, 75), (bx - 90, by - 18, 180, 40))       # sand spray at the base
        for i, (px, py, r) in enumerate(pts):
            col = (150, 108, 68) if i % 2 else (128, 92, 58)
            pygame.draw.circle(surf, col, (int(px), int(py)), int(r))
            pygame.draw.circle(surf, (105, 75, 48), (int(px), int(py)), int(r), 2)
        hx, hy, hr = pts[-1]
        maw = pygame.Rect(0, 0, int(hr * 2.2), int(hr * 1.5))
        maw.center = (int(hx - hr * 0.6), int(hy - hr * 0.2))
        pygame.draw.ellipse(surf, (40, 20, 18), maw)
        for k in range(10):
            a = k / 10 * 2 * math.pi
            tx, ty = maw.centerx + math.cos(a) * maw.width * 0.42, maw.centery + math.sin(a) * maw.height * 0.42
            pygame.draw.circle(surf, (235, 220, 190), (int(tx), int(ty)), 3)
    elif name == "tent":
        x = int(w * 0.62)
        pygame.draw.ellipse(surf, (120, 105, 85), (x - 90, ground - 80, 180, 120))
        pygame.draw.line(surf, (90, 75, 60), (x, ground - 80), (x, ground - 30), 2)
    elif name == "fire":
        for i in range(0, w, 40):
            fh = 40 + 30 * abs(math.sin(t * 3 + i))
            pygame.draw.polygon(surf, (230, 110, 40), [(i, ground - 170), (i + 20, ground - 170 - fh), (i + 40, ground - 170)])
    elif name == "shield" and p:
        sh = pygame.Surface((int(p.h * 0.7), int(p.h * 1.15)), pygame.SRCALPHA)
        a = 50 + int(25 * math.sin(t * 4))
        pygame.draw.ellipse(sh, (150, 200, 255, a), sh.get_rect(), 3)
        surf.blit(sh, (p.x - sh.get_width() // 2, p.y - sh.get_height()))


# --------------------------------------------------------------------- stage
class Stage:
    def __init__(self, pack, beat_id, state, size, t):
        self.pack, self.beat_id = pack, beat_id
        beat = pack.beats[beat_id]
        self.w, self.h = size
        self.ground = int(self.h * GROUND)
        self.t0 = t
        self.seeker_down = False
        self.speech_queue: list = []
        self.bubble = None          # (character id, line, start time, duration)
        spec = beat.get("stage") or {}
        self.player = pack.player or next(iter(pack.characters), "")
        cast = spec.get("cast")
        if cast is None:
            cast = present(pack, beat, state)
        cast = [c for c in cast if c in pack.characters and state.alive.get(c, True)]
        self.props = spec.get("props", detect_props(beat))
        fig_h = int(self.h * FIG_H)
        self.actors = []
        slots = self._slots(len(cast))
        for i, cid in enumerate(cast):
            c = pack.characters[cid]
            x = slots[i]
            a = Actor(cid, short_name(cid, c), look_for(cid, c), x, self.ground, fig_h,
                      facing=1 if x < self.w / 2 else -1)
            # enter: a short walk in from the nearest side while fading in
            a.x = x - 220 if x < self.w / 2 else x + 220
            a.tx = x
            a.speed = 200
            self.actors.append(a)

    def _slots(self, n):
        if n == 0:
            return []
        if n == 1:
            return [self.w * 0.42]
        if n == 2:
            return [self.w * 0.3, self.w * 0.7]
        left = self.w * 0.18
        right = self.w * 0.82
        return [left + i * (right - left) / (n - 1) for i in range(n)]

    def player_actor(self):
        return next((a for a in self.actors if a.cid == self.player), self.actors[0] if self.actors else None)

    def resize(self, size):
        sx = size[0] / self.w
        self.w, self.h = size
        self.ground = int(self.h * GROUND)
        for a in self.actors:
            a.x *= sx
            a.tx *= sx
            a.y = self.ground
            a.h = int(self.h * FIG_H)

    def exit(self, label: str) -> str:
        """Animate the reaction to a choice; returns the motion name."""
        motion = motion_for(label)
        p = self.player_actor()
        others = [a for a in self.actors if a is not p]
        near = min(others, key=lambda a: abs(a.x - p.x)) if (p and others) else None
        if not p:
            return motion
        if motion == "run":
            p.speed, p.tx = 520, -150 if p.x < self.w / 2 else self.w + 150
        elif motion == "lunge":
            if near:
                p.speed, p.tx = 420, near.x - 70 * (1 if near.x > p.x else -1)
            p.pose = "lunge"
            if "seeker" in self.props:
                self.seeker_down = True
        elif motion == "together":
            for i, a in enumerate([p] + others[:2]):
                a.speed, a.tx = 200, self.w + 150 + i * 60
        elif motion == "back":
            p.speed, p.tx = 140, p.x - 90
            p.pose = "back"
        elif motion == "speak":
            if near:
                p.speed, p.tx = 140, near.x - 120 * (1 if near.x > p.x else -1)
            p.pose = "speak"
        elif motion == "still":
            p.pose = None
        else:
            p.speed, p.tx = 200, self.w + 150
        return motion

    # ---- dialogue: one speech bubble at a time, the speaker steps into a "speak" pose
    def say(self, lines):
        """Queue [(character id, line)]; lines from people not on stage are skipped."""
        on = {a.cid for a in self.actors}
        self.speech_queue = getattr(self, "speech_queue", []) + [(c, l) for c, l in lines if c in on]

    @property
    def speaking(self):
        return bool(getattr(self, "speech_queue", None) or getattr(self, "bubble", None))

    def skip_line(self):
        if getattr(self, "bubble", None):
            self.bubble = (*self.bubble[:2], -1e9, 0)

    def _update_speech(self, t):
        b = getattr(self, "bubble", None)
        if b and t - b[2] > b[3]:
            actor = self.actor(b[0])
            if actor and actor.pose == "speak":
                actor.pose = None
            self.bubble = b = None
        if not b and getattr(self, "speech_queue", None):
            cid, line = self.speech_queue.pop(0)
            self.bubble = (cid, line, t, 1.6 + len(line) / 15)
            actor = self.actor(cid)
            if actor and actor.pose is None:
                actor.pose = "speak"

    def actor(self, cid):
        return next((a for a in self.actors if a.cid == cid), None)

    def draw_bubble(self, surf, font, t):
        b = getattr(self, "bubble", None)
        a = self.actor(b[0]) if b else None
        if not a:
            return
        words, lines, cur = b[1].split(), [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            if font.size(test)[0] <= 300 or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        lh = font.get_linesize()
        bw = max(font.size(ln)[0] for ln in lines) + 28
        bh = lh * len(lines) + 20
        head_y = a.y - a.h * a.look["height"] * 0.85
        side = 1 if a.x < self.w / 2 else -1                # bubble toward the middle of the screen
        bx = a.x + side * 40 if side > 0 else a.x - 40 - bw
        bx = max(8, min(self.w - bw - 8, bx))
        by = max(48, head_y - bh - 6)
        pop = min(1.0, (t - b[2]) * 6)                     # quick pop-in
        rect = pygame.Rect(int(bx), int(by + (1 - pop) * 10), bw, bh)
        pygame.draw.polygon(surf, (246, 238, 222), [(a.x + side * 14, head_y),
                                                    (rect.centerx - 10 * side, rect.bottom - 2),
                                                    (rect.centerx + 12 * side, rect.bottom - 2)])
        pygame.draw.rect(surf, (246, 238, 222), rect, border_radius=12)
        pygame.draw.rect(surf, (120, 95, 70), rect, 2, border_radius=12)
        for i, ln in enumerate(lines):
            surf.blit(font.render(ln, True, (35, 28, 22)), (rect.x + 14, rect.y + 10 + i * lh))

    def update(self, dt, t=None):
        for a in self.actors:
            a.update(dt)
        if t is not None:
            self._update_speech(t)

    def draw(self, surf, t, font=None):
        back = [p for p in self.props if p in ("ornithopter", "crawler", "worm", "fire", "globe", "tent", "table")]
        for name in back:
            draw_prop(surf, name, self.w, self.ground, t, self)
        for a in sorted(self.actors, key=lambda a: a.y):
            a.draw(surf, t, font)
        for name in self.props:
            if name not in back:
                draw_prop(surf, name, self.w, self.ground, t, self)
