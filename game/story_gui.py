"""Point-and-click window for story packs (pygame).

  python play_story.py --gui [--pack dune] [--llm qwen3:1.7b]

Same StoryEngine as the terminal version. Slow AI calls run in a background thread so the
window never freezes; input is ignored while the narrator is writing.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from story import StoryEngine, load_pack, sources  # noqa: E402
from story.pack import list_packs  # noqa: E402

from .scene_art import draw_scene  # noqa: E402

BG = (18, 15, 13)
PANEL = (30, 25, 21)
INK = (236, 226, 208)
DIM = (160, 145, 125)
ACCENT = (226, 160, 80)
EPIGRAPH = (200, 180, 150)
BUTTON = (52, 42, 34)
BUTTON_HOVER = (86, 64, 44)
DEAD = (110, 95, 85)
SIDEBAR_W = 290
BANNER_H = 210
REVEAL_CPS = 220   # typewriter speed, characters per second


def _font(names, size, italic=False, bold=False):
    for n in names:
        path = pygame.font.match_font(n, bold=bold, italic=italic)
        if path:
            return pygame.font.Font(path, size)
    f = pygame.font.Font(None, int(size * 1.3))   # pygame's bundled font always exists
    f.set_italic(italic)
    f.set_bold(bold)
    return f


def wrap(text: str, font, width: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            test = f"{cur} {w}".strip()
            if font.size(test)[0] <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


class StoryGUI:
    def __init__(self, pack_name: str | None = None, llm: str | None = None, book_style: bool = False):
        pygame.init()
        pygame.key.set_repeat(400, 35)
        self.screen = pygame.display.set_mode((1280, 820), pygame.RESIZABLE)
        pygame.display.set_caption("Desert Fates")
        serif, sans = ["dejavuserif", "liberationserif", "freeserif", "georgia", "timesnewroman"], \
                      ["dejavusans", "liberationsans", "freesans", "arial", "helvetica"]
        self.f_text = _font(serif, 20)
        self.f_epi = _font(serif, 17, italic=True)
        self.f_title = _font(serif, 34, bold=True)
        self.f_place = _font(serif, 18, italic=True)
        self.f_ui = _font(sans, 17)
        self.f_small = _font(sans, 14)
        self.clock = pygame.time.Clock()
        self.llm, self.book_style = llm, book_style
        self.kwargs = self._ai_parts(llm, book_style)
        self.toasts: list[tuple[str, float]] = []
        self.busy: str | None = None          # text shown while a background job runs
        self._job_result = None
        self.input = ""
        self.scroll = 0
        self.mode = "menu"
        self.packs = list_packs()
        if pack_name:
            self.start(pack_name)
        elif len(self.packs) == 1:
            self.start(self.packs[0][0])

    # ------------------------------------------------------------------ setup
    def _ai_parts(self, llm, book_style):
        if not llm:
            return {}
        from story.engine import ChainInterpreter, RuleInterpreter
        from story.llm import OllamaInterpreter, OllamaNarrator, check_ollama
        problem = check_ollama(llm)
        if problem:
            self._startup_warning = f"AI narrator off: {problem}"
            return {}
        return {"interpreter": ChainInterpreter(RuleInterpreter(), OllamaInterpreter(llm)),
                "narrator": OllamaNarrator(llm, excerpt_chars=1200 if book_style else 0)}

    def start(self, pack_name: str):
        self.pack = load_pack(pack_name)
        self.eng = StoryEngine(self.pack, **self.kwargs)
        self.mode = "story"
        self.page: list[tuple[str, str]] = [("intro", self.pack.intro)]
        self.last_place = ""
        self.shown_epigraph = None
        self.scene_key = None
        self.reveal_start = time.time()
        if getattr(self, "_startup_warning", None):
            self.toast(self._startup_warning, 9)
            self._startup_warning = None
        self.refresh(new_page=False)

    # ------------------------------------------------------------- story flow
    def toast(self, msg, secs=6):
        self.toasts.append((msg, time.time() + secs))

    def run_job(self, label, fn, then):
        """Run fn() off the main thread; call then(result) on the main thread afterwards."""
        self.busy = label

        def work():
            try:
                self._job_result = ("ok", fn())
            except Exception as e:  # never crash the window because the AI failed
                self._job_result = ("err", e)
        self._job_then = then
        threading.Thread(target=work, daemon=True).start()

    def _poll_job(self):
        if self.busy and self._job_result is not None:
            status, value = self._job_result
            self._job_result, self.busy = None, None
            if status == "err":
                self.toast(f"Something went wrong: {value}")
                value = None
            self._job_then(value)

    def refresh(self, new_page=True):
        """Show messages from the last action, then the (possibly new) scene."""
        eng = self.eng
        msgs = [("message", m) for m in eng.messages]
        key = (eng.state.beat, len([h for h in eng.state.history if not h[1].startswith("(you)")]))
        if key == self.scene_key and not eng.done:
            self.page += msgs          # same scene: just append the reaction
            self.scroll = 10 ** 6      # jump to bottom
            self.reveal_start = time.time()
            return
        self.scene_key = key
        if new_page:
            self.page = []
            self.scroll = 0
        self.page += msgs
        epi = sources.epigraph(eng.beat)
        if epi and epi != self.shown_epigraph:
            self.page.append(("epigraph", epi))
            self.shown_epigraph = epi
        self.run_job("The narrator is writing…" if "narrator" in self.kwargs else "…", eng.text, self._scene_ready)

    def _scene_ready(self, text):
        self.page.append(("scene", text or self.eng.beat.get("text", "")))
        self.reveal_start = time.time()
        for part in self.kwargs.values():
            for note in (getattr(getattr(part, "generate", None), "notice", None), getattr(part, "last_error", None)):
                if note and note not in getattr(self, "_warned", set()):
                    self._warned = getattr(self, "_warned", set()) | {note}
                    self.toast(f"AI narrator: {note}", 9)

    def choose(self, i):
        if self.busy or self.eng.done or not 0 <= i < len(self.eng.choices()):
            return
        self.eng.choose(i)
        self.refresh()

    def submit(self):
        text = self.input.strip()
        if not text or self.busy or self.eng.done:
            return
        self.input = ""
        self.page.append(("you", text))

        def after(_):
            self.refresh()
        self.run_job("Considering what you tried…" if "interpreter" in self.kwargs else "…",
                     lambda: self.eng.freeform(text), after)

    # ---------------------------------------------------------------- drawing
    def layout(self):
        w, h = self.screen.get_size()
        side = SIDEBAR_W if w >= 900 else 0
        banner = pygame.Rect(0, 0, w - side, BANNER_H if h >= 600 else 120)
        sidebar = pygame.Rect(w - side, 0, side, h)
        n = len(self.eng.choices()) if self.mode == "story" and not self.eng.done else 2
        bottom_h = 24 + n * 50 + 56
        text = pygame.Rect(30, banner.bottom + 12, banner.width - 60, h - banner.bottom - bottom_h - 20)
        bottom = pygame.Rect(30, h - bottom_h, banner.width - 60, bottom_h)
        return banner, sidebar, text, bottom

    def draw(self, t):
        self.screen.fill(BG)
        if self.mode == "menu":
            self.draw_menu(t)
        else:
            banner, sidebar, text, bottom = self.layout()
            self.draw_banner(banner, t)
            self.draw_page(text)
            if self.eng.done and not self.busy:
                self.draw_ending(bottom)
            else:
                self.draw_controls(bottom)
            if sidebar.width:
                self.draw_sidebar(sidebar)
        self.draw_toasts()
        pygame.display.flip()

    def draw_menu(self, t):
        w, h = self.screen.get_size()
        draw_scene(self.screen, pygame.Rect(0, 0, w, h // 2), "the open desert at dusk", t)
        title = self.f_title.render("Desert Fates", True, INK)
        self.screen.blit(title, title.get_rect(center=(w // 2, h // 2 - 50)))
        sub = self.f_place.render("Choose a story", True, DIM)
        self.screen.blit(sub, sub.get_rect(center=(w // 2, h // 2 + 10)))
        self.menu_buttons = []
        mouse = pygame.mouse.get_pos()
        for i, (name, title_) in enumerate(self.packs):
            r = pygame.Rect(0, 0, 520, 46)
            r.center = (w // 2, h // 2 + 70 + i * 58)
            self._button(r, f"{i + 1}.  {title_}", r.collidepoint(mouse))
            self.menu_buttons.append((r, name))

    def draw_banner(self, rect, t):
        place = self.eng.beat.get("place") or getattr(self, "last_place", "") or self.pack.title
        self.last_place = place
        draw_scene(self.screen, rect, place, t)
        label = self.f_place.render(place.split(":")[0].split(",")[0], True, INK)
        self.screen.blit(label, (rect.x + 30, rect.bottom - label.get_height() - 12))

    def _page_lines(self, width):
        """[(font, color, text, indent)] for the whole page, with blank spacer lines."""
        out = []
        for kind, text in self.page:
            if kind == "epigraph":
                for para in text.split("\n\n"):
                    out += [(self.f_epi, EPIGRAPH, ln, 40) for ln in wrap(para, self.f_epi, width - 80)]
            elif kind == "message":
                out += [(self.f_text, ACCENT, ln, 0) for ln in wrap(text, self.f_text, width)]
            elif kind == "you":
                out += [(self.f_text, DIM, ln, 0) for ln in wrap(f"> {text}", self.f_text, width)]
            else:
                for para in text.split("\n\n"):
                    out += [(self.f_text, INK, ln, 0) for ln in wrap(para.strip(), self.f_text, width)]
                    out.append(None)
            out.append(None)
        return out

    def draw_page(self, rect):
        lines = self._page_lines(rect.width)
        lh = self.f_text.get_linesize() + 2
        total = sum(lh if ln else lh // 2 for ln in lines)
        self.max_scroll = max(0, total - rect.height)
        self.scroll = max(0, min(self.scroll, self.max_scroll))
        budget = int((time.time() - self.reveal_start) * REVEAL_CPS)
        # typewriter: reveal only the newest page item gradually
        last_kind_lines = len(self._page_lines_for_last(rect.width))
        reveal_from = len(lines) - last_kind_lines
        self.screen.set_clip(rect)
        y = rect.y - self.scroll
        cursor = None
        for i, ln in enumerate(lines):
            if ln is None:
                y += lh // 2
                continue
            font, color, text, indent = ln
            if i >= reveal_from:
                if budget <= 0:
                    break
                shown = text[:budget]
                budget -= len(text)
                cursor = y + lh
            else:
                shown = text
            if y + lh >= rect.y and y <= rect.bottom:
                self.screen.blit(font.render(shown, True, color), (rect.x + indent, y))
            y += lh
        self.screen.set_clip(None)
        if cursor is not None and cursor > rect.bottom:
            self.scroll += cursor - rect.bottom      # follow the typewriter down the page
        if self.busy:
            dots = "." * (1 + int(time.time() * 2) % 3)
            msg = self.f_place.render(f"{self.busy.rstrip('…')}{dots}" if self.busy else dots, True, DIM)
            self.screen.blit(msg, (rect.x, min(y + 6, rect.bottom - 24)))
        if self.max_scroll:
            frac = self.scroll / self.max_scroll
            bar = pygame.Rect(rect.right + 12, rect.y + int(frac * (rect.height - 40)), 4, 40)
            pygame.draw.rect(self.screen, DIM, bar, border_radius=2)

    def _page_lines_for_last(self, width):
        if not self.page:
            return []
        saved = self.page
        self.page = saved[-1:]
        try:
            return self._page_lines(width)
        finally:
            self.page = saved

    def revealing(self):
        lines = self._page_lines_for_last(self.layout()[2].width)
        chars = sum(len(ln[2]) for ln in lines if ln)
        return (time.time() - self.reveal_start) * REVEAL_CPS < chars

    def _button(self, r, text, hover, enabled=True):
        pygame.draw.rect(self.screen, BUTTON_HOVER if hover and enabled else BUTTON, r, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT if hover and enabled else (80, 64, 50), r, 1, border_radius=8)
        color = INK if enabled else DIM
        lines = wrap(text, self.f_ui, r.width - 28)[:2]
        lh = self.f_ui.get_linesize()
        y = r.centery - lh * len(lines) // 2
        for ln in lines:
            self.screen.blit(self.f_ui.render(ln, True, color), (r.x + 14, y))
            y += lh

    def draw_controls(self, rect):
        mouse = pygame.mouse.get_pos()
        self.choice_buttons = []
        enabled = not self.busy
        y = rect.y + 8
        for i, c in enumerate(self.eng.choices()):
            r = pygame.Rect(rect.x, y, rect.width, 44)
            self._button(r, f"{i + 1}.  {c['label']}", r.collidepoint(mouse), enabled)
            self.choice_buttons.append(r)
            y += 50
        box = pygame.Rect(rect.x, y + 6, rect.width, 42)
        pygame.draw.rect(self.screen, PANEL, box, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT if self.input else (80, 64, 50), box, 1, border_radius=8)
        if self.input:
            shown, color = self.input, INK
            while self.f_ui.size(shown + "|")[0] > box.width - 28:
                shown = shown[1:]
            shown += "|" if int(time.time() * 2) % 2 else " "
        else:
            shown, color = "Or type anything you want to try, then press Enter…", DIM
        self.screen.blit(self.f_ui.render(shown, True, color), (box.x + 14, box.centery - self.f_ui.get_linesize() // 2))

    def draw_ending(self, rect):
        mouse = pygame.mouse.get_pos()
        title = self.f_title.render(f"THE END: {self.eng.state.ending}", True, ACCENT)
        self.screen.blit(title, (rect.x, rect.y + 4))
        drift = self.f_small.render(f"Choices away from the original story: {self.eng.state.drift}", True, DIM)
        self.screen.blit(drift, (rect.x, rect.y + 48))
        self.end_buttons = []
        for i, (label, action) in enumerate([("Play again", "again"), ("Choose another story", "menu"),
                                             ("Quit", "quit")]):
            r = pygame.Rect(rect.x + i * 230, rect.y + 76, 216, 44)
            self._button(r, label, r.collidepoint(mouse))
            self.end_buttons.append((r, action))

    def draw_sidebar(self, rect):
        pygame.draw.rect(self.screen, PANEL, rect)
        x, y = rect.x + 20, 24
        self.screen.blit(self.f_place.render(self.pack.title, True, INK), (x, y))
        y += 44
        s = self.eng.state
        self.screen.blit(self.f_small.render("CHARACTERS", True, ACCENT), (x, y))
        y += 24
        for cid, c in self.pack.characters.items():
            alive = s.alive.get(cid, True)
            name = c.get("name", cid)
            while self.f_small.size(name)[0] > rect.width - 60:
                name = name[:-2] + "…"
            surf = self.f_small.render(name + ("" if alive else "  †"), True, INK if alive else DEAD)
            self.screen.blit(surf, (x, y))
            if not alive:
                pygame.draw.line(self.screen, DEAD, (x, y + 9), (x + surf.get_width() - 18, y + 9))
            y += 21
        y += 14
        if s.stats:
            self.screen.blit(self.f_small.render("STANDING", True, ACCENT), (x, y))
            y += 24
            for k, v in s.stats.items():
                self.screen.blit(self.f_small.render(f"{k.replace('_', ' ').capitalize()}: {v:+d}", True, INK), (x, y))
                y += 21
            y += 14
        self.screen.blit(self.f_small.render("DRIFT FROM THE ORIGINAL", True, ACCENT), (x, y))
        y += 24
        pygame.draw.rect(self.screen, BUTTON, (x, y, rect.width - 40, 10), border_radius=5)
        pygame.draw.rect(self.screen, ACCENT, (x, y, min(rect.width - 40, 18 * s.drift), 10), border_radius=5)
        y += 20
        self.screen.blit(self.f_small.render(f"{s.drift} choice{'s' if s.drift != 1 else ''}", True, DIM), (x, y))
        foot = f"AI narrator: {self.llm}" if "narrator" in self.kwargs else "Plain text (no AI)"
        self.screen.blit(self.f_small.render(foot, True, DIM), (x, rect.bottom - 52))
        self.screen.blit(self.f_small.render("Esc: menu   wheel: scroll", True, DIM), (x, rect.bottom - 30))

    def draw_toasts(self):
        now = time.time()
        self.toasts = [(m, e) for m, e in self.toasts if e > now]
        w, _ = self.screen.get_size()
        y = 14
        for msg, _ in self.toasts[-3:]:
            lines = wrap(msg, self.f_small, 520)
            r = pygame.Rect(w - 560, y, 540, 16 + 18 * len(lines))
            pygame.draw.rect(self.screen, (60, 30, 25), r, border_radius=8)
            for i, ln in enumerate(lines):
                self.screen.blit(self.f_small.render(ln, True, INK), (r.x + 10, r.y + 8 + i * 18))
            y = r.bottom + 8

    # ----------------------------------------------------------------- events
    def handle(self, e) -> bool:
        """Returns False to quit."""
        if e.type == pygame.QUIT:
            return False
        if self.mode == "menu":
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                for r, name in getattr(self, "menu_buttons", []):
                    if r.collidepoint(e.pos):
                        self.start(name)
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    return False
                if e.unicode.isdigit() and 1 <= int(e.unicode) <= len(self.packs):
                    self.start(self.packs[int(e.unicode) - 1][0])
            return True
        if e.type == pygame.MOUSEWHEEL:
            self.scroll -= e.y * 40
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.revealing():
                self.reveal_start = 0          # click skips the typewriter
            elif self.eng.done:
                for r, action in getattr(self, "end_buttons", []):
                    if r.collidepoint(e.pos):
                        return self._end_action(action)
            else:
                for i, r in enumerate(getattr(self, "choice_buttons", [])):
                    if r.collidepoint(e.pos):
                        self.choose(i)
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.mode = "menu"
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.revealing():
                    self.reveal_start = 0
                else:
                    self.submit()
            elif e.key == pygame.K_BACKSPACE:
                self.input = self.input[:-1]
            elif e.key in (pygame.K_PAGEUP, pygame.K_UP) and not self.input:
                self.scroll -= 120
            elif e.key in (pygame.K_PAGEDOWN, pygame.K_DOWN) and not self.input:
                self.scroll += 120
            elif e.unicode and e.unicode.isprintable():
                if not self.input and e.unicode.isdigit() and not self.eng.done:
                    self.choose(int(e.unicode) - 1)
                elif not self.eng.done:
                    self.input += e.unicode
        return True

    def _end_action(self, action):
        if action == "quit":
            return False
        if action == "again":
            self.start(self.pack_name_of(self.pack))
        else:
            self.mode = "menu"
        return True

    def pack_name_of(self, pack):
        return next((n for n, t in self.packs if t == pack.title), self.packs[0][0])

    def run(self):
        t0 = time.time()
        running = True
        while running:
            for e in pygame.event.get():
                running = self.handle(e) and running
            self._poll_job()
            self.draw(time.time() - t0)
            self.clock.tick(30)
        pygame.quit()


def main(pack=None, llm=None, book_style=False):
    StoryGUI(pack, llm, book_style).run()


if __name__ == "__main__":
    main()
