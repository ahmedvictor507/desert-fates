"""Thin pygame viewer over the headless engine."""
import pygame

from engine import world

TILE = 24
COLORS = {world.SAND: (222, 190, 120), world.ROCK: (110, 100, 95),
          world.SPICE: (230, 120, 30), world.SIETCH: (70, 130, 190)}
HUD_H = 110


class Viewer:
    def __init__(self, env):
        pygame.init()
        sc = env.scenario
        self.env = env
        self.screen = pygame.display.set_mode((sc.width * TILE, sc.height * TILE + HUD_H))
        pygame.display.set_caption(f"Sand Planet - {sc.name}")
        self.font = pygame.font.SysFont("monospace", 15)

    def draw(self, messages=()):
        s, sc = self.env.engine.state, self.env.scenario
        self.screen.fill((20, 18, 15))
        for y in range(sc.height):
            for x in range(sc.width):
                pygame.draw.rect(self.screen, COLORS[s.grid[y][x]], (x * TILE, y * TILE, TILE - 1, TILE - 1))
        for wx, wy in s.worms:
            pygame.draw.circle(self.screen, (120, 40, 40), (wx * TILE + TILE // 2, wy * TILE + TILE // 2), TILE // 2)
        color = (240, 240, 240) if s.form == "human" else (170, 60, 200)
        pygame.draw.rect(self.screen, color, (s.x * TILE + 4, s.y * TILE + 4, TILE - 8, TILE - 8))
        lines = [f"turn {s.turn}/{sc.max_turns}  form={s.form}  hp={s.hp}  water={s.water}  spice={s.spice}/{sc.goal_spice}",
                 "arrows: move  g: gather  d: drink  r: rest  t: type free-form action",
                 *messages[-3:]]
        for i, line in enumerate(lines):
            self.screen.blit(self.font.render(line, True, (235, 225, 200)), (6, sc.height * TILE + 6 + i * 20))
        pygame.display.flip()

    def prompt(self, label="You try to: "):
        text = ""
        clock = pygame.time.Clock()
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return None
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_RETURN:
                        return text
                    if e.key == pygame.K_ESCAPE:
                        return ""
                    if e.key == pygame.K_BACKSPACE:
                        text = text[:-1]
                    else:
                        text += e.unicode
            self.draw([label + text + "_"])
            clock.tick(30)
