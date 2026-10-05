"""Point-and-click window for story packs (pygame).

  python play_story.py --gui [--pack dune] [--llm qwen3:1.7b]

Layout: the scene fills the window, characters stand on the ground, the story text sits in a
translucent panel in the centre and the choices are at the bottom. Picking a choice animates the
cast (see game/stage.py), fades to the next scene and walks the new cast in. Cutaway beats (a
scene elsewhere, e.g. the villain's council) are staged as their own scenes with a Continue
button. Slow AI calls run in a background thread, started the moment a choice is made so the
narration is written while the transition plays.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from story import StoryEngine, load_pack, sources  # noqa: E402
from story.cast import present, scene_dialogue  # noqa: E402
from story.improv import IMPROVISE  # noqa: E402
from story.pack import list_packs  # noqa: E402

from .scene_art import draw_scene  # noqa: E402
from .stage import FIG_H, GROUND, Stage  # noqa: E402

INK = (240, 232, 215)
DIM = (175, 160, 140)
ACCENT = (232, 168, 88)
EPIGRAPH = (215, 198, 170)
PANEL = (14, 11, 9, 190)
BUTTON = (40, 32, 26, 225)
BUTTON_HOVER = (92, 66, 42, 240)
DEAD = (120, 105, 95)
REVEAL_CPS = 220        # typewriter speed, characters per second
EXIT_SECS, FADE_SECS, CARD_SECS = 1.1, 0.45, 3.0


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
        cur = ""
        for w in para.split(" "):
            test = f"{cur} {w}".strip()
            if font.size(test)[0] <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


_SPEECH = re.compile(r"^\s*(i\s+)?(say|shout|whisper|reply|answer|call out)\b|[\"“]", re.I)


def _is_speech(text: str) -> bool:
    return bool(_SPEECH.search(text))


def _spoken_words(text: str) -> str:
    m = re.search(r"[\"“]([^\"”]+)[\"”]", text)
    if m:
        return m.group(1)
    return re.sub(r"^\s*(i\s+)?(say|shout|whisper|reply|answer|call out)\s*(to \w+)?[,:]?\s*", "", text,
                  flags=re.I).strip()


def canon_path(pack) -> list[str]:
    """Beats of the original story, in order: always take the canon choice."""
    eng = StoryEngine(pack)
    path = list(eng.trail) or [pack.start]
    for _ in range(200):
        if eng.done:
            break
        opts = eng.choices()
        i = next((k for k, c in enumerate(opts) if c.get("canon", True) and c["next"] != IMPROVISE), 0)
        eng.choose(i)
        path += eng.trail
    return path


def _panel(surf, rect, color=PANEL, radius=14):
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, color, s.get_rect(), border_radius=radius)
    surf.blit(s, rect.topleft)


class StoryGUI:
    def __init__(self, pack_name: str | None = None, llm: str | None = None, book_style: bool = False):
        pygame.init()
        pygame.key.set_repeat(400, 35)
        self.screen = pygame.display.set_mode((1280, 820), pygame.RESIZABLE)
        pygame.display.set_caption("Desert Fates")
        serif = ["dejavuserif", "liberationserif", "freeserif", "georgia", "timesnewroman"]
        sans = ["dejavusans", "liberationsans", "freesans", "arial", "helvetica"]
        self.f_text = _font(serif, 19)
        self.f_ital = _font(serif, 19, italic=True)
        self.f_epi = _font(serif, 20, italic=True)
        self.f_title = _font(serif, 34, bold=True)
        self.f_place = _font(serif, 17, italic=True)
        self.f_ui = _font(sans, 16)
        self.f_small = _font(sans, 13)
        self.f_bubble = _font(sans, 15)
        self.clock = pygame.time.Clock()
        self.llm = llm
        self._startup_warning = None
        self.kwargs = self._ai_parts(llm, book_style)
        self.improviser = None
        if "narrator" in self.kwargs:
            from story.improv import Improviser
            from story.llm import ollama_generate
            self.improviser = Improviser(ollama_generate(llm, json_mode=True))
        self.toasts: list[tuple[str, float]] = []
        self.busy: str | None = None
        self._job_result = None
        self._warned: set = set()
        self.input = ""
        self.scroll = 0
        self.max_scroll = 0
        self.details = False
        self.show_map = False
        self.mode = "menu"
        self.packs = list_packs()
        self.t = 0.0
        self.place = ""
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
        self.pack_name = pack_name
        self.pack = load_pack(pack_name)
        self.eng = StoryEngine(self.pack, **self.kwargs)
        self.mode = "story"
        self.shown_epigraph = None
        self.final_text = None
        self.place = ""
        self.pending_msgs = [("intro", self.pack.intro)]
        self.queue = [self.eng.state.beat]
        self.phase, self.phase_t = "play", self.t
        self.stage = None
        self.showing = None
        self.visited = [self.eng.state.beat]
        self.pending_dialogue = []
        self.can_follow = None          # the last free-text action the AI could turn into a new scene
        if self._startup_warning:
            self.toast(self._startup_warning, 9)
            self._startup_warning = None
        self._narrate()
        self._show_next()

    # ---------------------------------------------------------- background jobs
    def toast(self, msg, secs=6):
        self.toasts.append((msg, time.time() + secs))

    def run_job(self, label, fn, then):
        """Run fn() off the main thread; then(result) runs on the main thread afterwards."""
        self.busy = label

        def work():
            try:
                self._job_result = ("ok", fn())
            except Exception as e:     # never crash the window because the AI failed
                self._job_result = ("err", e)
        self._job_then = then
        threading.Thread(target=work, daemon=True).start()

    def _poll_job(self):
        if self.busy is not None and self._job_result is not None:
            status, value = self._job_result
            self._job_result, self.busy = None, None
            if status == "err":
                self.toast(f"Something went wrong: {value}")
                value = None
            self._job_then(value)

    def _narrate(self):
        """Start writing the current (final) scene's text right away."""
        self.final_text = None
        beat_id = self.eng.state.beat

        def done(text):
            self.final_text = (beat_id, text or self.pack.beats[beat_id].get("text", ""))
            self._warn_ai()
            if self.showing == beat_id and not self.queue:
                self._reveal_final()
        self.run_job("The narrator is writing" if "narrator" in self.kwargs else "", self.eng.text, done)

    def _warn_ai(self):
        for part in self.kwargs.values():
            for note in (getattr(getattr(part, "generate", None), "notice", None), getattr(part, "last_error", None)):
                if note and note not in self._warned:
                    self._warned.add(note)
                    self.toast(f"AI narrator: {note}", 9)

    # ------------------------------------------------------------- scene flow
    def _show_next(self):
        """Put the next queued beat on stage (fading in)."""
        beat_id = self.queue.pop(0)
        self.showing = beat_id
        beat = self.pack.beats[beat_id]
        self.stage = Stage(self.pack, beat_id, self.eng.state, self.screen.get_size(), self.t)
        self.place = beat.get("place") or self.place or self.pack.title
        self.page = list(self.pending_msgs)
        self.pending_msgs = []
        self.scroll = 0
        self.reveal_t = self.t
        self.card = None
        epi = sources.epigraph(beat)
        if epi and epi != self.shown_epigraph:
            self.card, self.card_until = epi, self.t + CARD_SECS
            self.shown_epigraph = epi
        self.pending_dialogue = []
        if self.queue:                                  # a cutaway: its own text, then Continue
            self.page.append(("scene", beat.get("text", "")))
            self.pending_dialogue = [tuple(x) for x in beat.get("dialogue", [])]
        elif self.final_text and self.final_text[0] == beat_id:
            self._reveal_final()
        self.phase, self.phase_t = "fade_in", self.t

    def _reveal_final(self):
        if not any(k == "scene" for k, _ in self.page):
            prose, lines = scene_dialogue(self.final_text[1], self.pack, self.eng.beat, self.eng.state)
            self.page.append(("scene", prose))
            self.pending_dialogue = lines
            self.reveal_t = self.t

    @property
    def is_cutaway(self):
        return bool(self.queue)

    def choose(self, i):
        if self.phase != "play" or self.busy is not None or self.eng.done or self.card or self.is_cutaway:
            return
        opts = self.eng.choices()
        if not 0 <= i < len(opts):
            return
        label = opts[i]["label"]
        if self.eng.needs_improv(i):
            if not self.improviser:
                self.toast("This path needs the AI narrator (--llm).")
                return

            def done(beat):
                if not beat:
                    self.toast(f"The AI couldn't write that scene: {self.improviser.last_error}")
                    return
                self.stage.exit(label)
                self.eng.choose(i, improvised=beat)
                self._after_step()
            self.run_job("✦ The story is changing", lambda: self.improviser.scene(self.eng, label), done)
            return
        self.stage.exit(label)
        self.eng.choose(i)
        self._after_step()

    def continue_story(self):
        """✦ The written story ended; ask the AI for what happens next."""
        if not self.improviser:
            self.toast("Continuing past the written story needs the AI narrator: "
                       "python3 play_story.py --gui --llm qwen3:1.7b", 9)
            return
        if self.busy is not None or not self.eng.done:
            return
        action = "Continue the story past this ending."

        def done(beat):
            if not beat:
                self.toast(f"The AI couldn't write that scene: {self.improviser.last_error}")
                return
            self.stage.exit("walk")
            self.eng.continue_after_ending(beat)
            self._after_step()
        self.run_job("✦ The story goes on", lambda: self.improviser.scene(self.eng, action), done)

    def follow(self):
        """✦ Turn the player's last free-text action into a brand-new scene written by the AI."""
        action = self.can_follow
        if not action or not self.improviser or self.busy is not None or self.phase != "play":
            return

        def done(beat):
            if not beat:
                self.toast(f"The AI couldn't write that scene: {self.improviser.last_error}")
                return
            self.stage.exit(action)
            self.eng.follow(action, beat)
            self._after_step()
        self.run_job("✦ The story is changing", lambda: self.improviser.scene(self.eng, action), done)

    def _after_step(self):
        """After the engine moved: queue cutaways + the new scene, start narrating, play the exit."""
        eng = self.eng
        self.visited += eng.trail
        self.can_follow = None
        cut = [b for b in eng.trail[:-1] if self.pack.beats[b].get("text")]
        cut_texts = {self.pack.beats[b]["text"] for b in cut}
        self.pending_msgs = [("message", m) for m in eng.messages if m not in cut_texts]
        self.queue = cut + [eng.state.beat]
        self._narrate()
        self.phase, self.phase_t = "exit", self.t

    def advance(self):
        """Click/Enter/Space: dismiss the epigraph card, finish the typewriter, or leave a cutaway."""
        if self.phase != "play":
            return
        if self.card:
            if self.final_text or self.is_cutaway:
                self.card = None
                self.reveal_t = self.t
            return
        if self.revealing():
            self.reveal_t = -1e9
            return
        if self.stage and self.stage.speaking:
            self.stage.skip_line()
            return
        if self.is_cutaway:
            self.stage.exit("walk")
            self.phase, self.phase_t = "exit", self.t

    def submit(self):
        text = self.input.strip()
        if (not text or self.busy is not None or self.eng.done or self.phase != "play"
                or self.is_cutaway or self.card):
            return
        self.input = ""
        self.page.append(("you", text))
        self.reveal_t = self.t
        self.scroll = 10 ** 6

        def after(accepted):
            if self.eng.trail:                          # a pack rule moved the story on
                self.stage.exit(text)
                self._after_step()
                return
            self.page += [("message", m) for m in self.eng.messages]
            self.reveal_t = self.t
            self.scroll = 10 ** 6
            self._warn_ai()
            spoken = list(self.eng.speech)
            if _is_speech(text) and self.pack.player:
                spoken.insert(0, (self.pack.player, _spoken_words(text)))
            self.pending_dialogue += spoken
            if accepted and self.improviser:
                self.can_follow = text
        self.run_job("Considering what you tried" if "interpreter" in self.kwargs else "",
                     lambda: self.eng.freeform(text), after)

    def tick(self, dt):
        self.t += dt
        if self.mode != "story":
            return
        if self.stage:
            self.stage.update(dt, self.t)
            if (self.pending_dialogue and self.phase == "play" and not self.card and not self.revealing()):
                self.stage.say(self.pending_dialogue)
                self.pending_dialogue = []
        el = self.t - self.phase_t
        if self.phase == "exit" and el >= EXIT_SECS:
            self.phase, self.phase_t = "fade_out", self.t
        elif self.phase == "fade_out" and el >= FADE_SECS:
            self._show_next()
        elif self.phase == "fade_in" and el >= FADE_SECS:
            self.phase, self.phase_t = "play", self.t
        if self.card and self.t >= self.card_until and (self.final_text or self.is_cutaway):
            self.card = None
            self.reveal_t = self.t

    # ---------------------------------------------------------------- drawing
    def layout(self):
        w, h = self.screen.get_size()
        pw = min(880, w - 60)
        text = pygame.Rect((w - pw) // 2, 52, pw, int(h * (GROUND - FIG_H)) - 70)
        bottom = pygame.Rect((w - pw) // 2, int(h * GROUND) + 34, pw, h - int(h * GROUND) - 44)
        return text, bottom

    def draw(self):
        t = self.t
        if self.mode == "menu":
            self.draw_menu(t)
        else:
            w, h = self.screen.get_size()
            draw_scene(self.screen, pygame.Rect(0, 0, w, h), self.place, t, floor_y=int(h * GROUND) - 30)
            self.stage.draw(self.screen, t, self.f_small)
            text_r, bottom_r = self.layout()
            self.draw_topbar()
            if self.phase in ("play", "fade_in") and not self.card:
                self.draw_page(text_r)
                if self.eng.done and not self.is_cutaway and self._text_shown():
                    self.draw_ending(bottom_r)
                else:
                    self.draw_controls(bottom_r)
            if self.phase == "play" and not self.card:
                self.stage.draw_bubble(self.screen, self.f_bubble, t)
            if self.card and self.phase in ("play", "fade_in"):
                self.draw_card()
            self.draw_fade()
            if self.details:
                self.draw_details()
            if self.show_map:
                self.draw_map()
        self.draw_toasts()
        pygame.display.flip()

    def draw_fade(self):
        el = self.t - self.phase_t
        a = 0.0
        if self.phase == "fade_out":
            a = min(1, el / FADE_SECS)
        elif self.phase == "fade_in":
            a = 1 - min(1, el / FADE_SECS)
        elif self.phase == "exit":
            a = max(0.0, (el - EXIT_SECS * 0.6) / (EXIT_SECS * 0.4)) * 0.5
        if a > 0:
            veil = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            veil.fill((0, 0, 0, int(255 * a)))
            self.screen.blit(veil, (0, 0))

    def draw_menu(self, t):
        w, h = self.screen.get_size()
        draw_scene(self.screen, pygame.Rect(0, 0, w, h), "the open desert at dusk", t)
        _panel(self.screen, pygame.Rect(w // 2 - 320, h // 2 - 110, 640, 140 + 58 * len(self.packs)))
        title = self.f_title.render("Desert Fates", True, INK)
        self.screen.blit(title, title.get_rect(center=(w // 2, h // 2 - 70)))
        sub = self.f_place.render("Choose a story", True, DIM)
        self.screen.blit(sub, sub.get_rect(center=(w // 2, h // 2 - 30)))
        self.menu_buttons = []
        mouse = pygame.mouse.get_pos()
        for i, (name, title_) in enumerate(self.packs):
            r = pygame.Rect(0, 0, 540, 46)
            r.center = (w // 2, h // 2 + 20 + i * 58)
            self._button(r, f"{i + 1}.  {title_}", r.collidepoint(mouse))
            self.menu_buttons.append((r, name))

    def draw_topbar(self):
        w, _ = self.screen.get_size()
        _panel(self.screen, pygame.Rect(10, 8, w - 20, 34), (0, 0, 0, 120), 10)
        place = self.place.split(":")[0].split(",")[0]
        self.screen.blit(self.f_place.render(f"{self.pack.title}  ·  {place}", True, INK), (24, 14))
        right = f"Drift {self.eng.state.drift}   ·   M: story map   ·   Tab: details   ·   Esc: menu"
        surf = self.f_small.render(right, True, DIM)
        self.screen.blit(surf, (w - surf.get_width() - 24, 17))

    def _page_lines(self, items, width):
        out = []
        for kind, text in items:
            if kind == "message":
                out += [(self.f_text, ACCENT, ln) for ln in wrap(text.replace("*", ""), self.f_text, width)]
            elif kind == "you":
                out += [(self.f_text, DIM, ln) for ln in wrap(f"> {text}", self.f_text, width)]
            else:
                for para in re.split(r"\n", text):
                    para = para.strip()
                    if not para:
                        continue
                    italic = para.startswith("*") and para.endswith("*")
                    font = self.f_ital if italic else self.f_text
                    out += [(font, INK if kind == "scene" else DIM, ln)
                            for ln in wrap(para.replace("*", ""), font, width)]
                    out.append(None)
            out.append(None)
        while out and out[-1] is None:
            out.pop()
        return out

    def _text_shown(self):
        return any(k == "scene" for k, _ in self.page) and not self.revealing()

    def revealing(self):
        if not getattr(self, "page", None):
            return False
        last = self._page_lines(self.page[-1:], self.layout()[0].width - 48)
        chars = sum(len(ln[2]) for ln in last if ln)
        return (self.t - self.reveal_t) * REVEAL_CPS < chars

    def draw_page(self, rect):
        width = rect.width - 48
        lines = self._page_lines(self.page, width)
        lh = self.f_text.get_linesize() + 3
        content_h = sum(lh if ln else lh // 2 for ln in lines)
        extra = 30 if self.busy else 0
        box = pygame.Rect(rect.x, rect.y, rect.width, max(70, min(rect.height, content_h + 36 + extra)))
        _panel(self.screen, box)
        inner = pygame.Rect(box.x + 24, box.y + 18, width, box.height - 36 - extra)
        self.max_scroll = max(0, content_h - inner.height)
        self.scroll = max(0, min(self.scroll, self.max_scroll))
        last_n = len(self._page_lines(self.page[-1:], width)) if self.page else 0
        reveal_from = len(lines) - last_n
        budget = int((self.t - self.reveal_t) * REVEAL_CPS)
        self.screen.set_clip(inner)
        y = inner.y - self.scroll
        cursor = None
        for i, ln in enumerate(lines):
            if ln is None:
                y += lh // 2
                continue
            font, color, text = ln
            shown = text
            if i >= reveal_from:
                if budget <= 0:
                    break
                shown, budget = text[:budget], budget - len(text)
                cursor = y + lh
            if inner.y - lh <= y <= inner.bottom:
                self.screen.blit(font.render(shown, True, color), (inner.x, y))
            y += lh
        self.screen.set_clip(None)
        if cursor is not None and cursor > inner.bottom:
            self.scroll += cursor - inner.bottom
        if self.busy:
            dots = "." * (1 + int(self.t * 2) % 3)
            self.screen.blit(self.f_place.render(f"{self.busy}{dots}", True, DIM), (inner.x, box.bottom - 32))
        if self.max_scroll:
            frac = self.scroll / self.max_scroll
            pygame.draw.rect(self.screen, DIM, (box.right - 12, inner.y + int(frac * (inner.height - 36)), 4, 36),
                             border_radius=2)

    def draw_card(self):
        """The chapter epigraph, shown like a title card while the scene is prepared."""
        w, h = self.screen.get_size()
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 165))
        self.screen.blit(veil, (0, 0))
        width = min(760, w - 100)
        lines = []
        for para in self.card.split("\n\n"):
            lines += wrap(para, self.f_epi, width) + [""]
        lh = self.f_epi.get_linesize() + 4
        y = h // 2 - len(lines) * lh // 2 - 40
        for ln in lines:
            surf = self.f_epi.render(ln, True, EPIGRAPH)
            self.screen.blit(surf, ((w - surf.get_width()) // 2, y))
            y += lh
        if self.final_text or self.is_cutaway:
            hint = "click to continue"
        else:
            hint = f"{self.busy}…" if self.busy else ""
        if hint:
            s = self.f_small.render(hint, True, DIM)
            self.screen.blit(s, ((w - s.get_width()) // 2, y + 10))

    def _button(self, r, text, hover, enabled=True):
        _panel(self.screen, r, BUTTON_HOVER if hover and enabled else BUTTON, 10)
        pygame.draw.rect(self.screen, ACCENT if hover and enabled else (95, 76, 58), r, 1, border_radius=10)
        lines = wrap(text, self.f_ui, r.width - 28)[:2]
        lh = self.f_ui.get_linesize()
        y = r.centery - lh * len(lines) // 2
        for ln in lines:
            self.screen.blit(self.f_ui.render(ln, True, INK if enabled else DIM), (r.x + 14, y))
            y += lh

    def draw_controls(self, rect):
        mouse = pygame.mouse.get_pos()
        self.choice_buttons, self.continue_button = [], None
        enabled = self.phase == "play" and self.busy is None and not self.revealing()
        if self.is_cutaway:
            r = pygame.Rect(0, 0, 220, 46)
            r.midtop = (rect.centerx, rect.y + 6)
            self._button(r, "Continue  ▸", r.collidepoint(mouse), self.phase == "play")
            self.continue_button = r
            return
        opts = self.eng.choices()
        cols = 2 if len(opts) <= 4 else 3
        bw = (rect.width - (cols - 1) * 12) // cols
        y = rect.y
        for i, c in enumerate(opts):
            r = pygame.Rect(rect.x + (i % cols) * (bw + 12), y + (i // cols) * 56, bw, 50)
            mark = "✦ " if c["next"] == IMPROVISE else ""
            self._button(r, f"{i + 1}.  {mark}{c['label']}", r.collidepoint(mouse), enabled)
            self.choice_buttons.append(r)
        y += ((len(opts) + cols - 1) // cols) * 56
        self.follow_button = None
        if self.can_follow:
            r = pygame.Rect(rect.x, y, rect.width, 40)
            self._button(r, "✦  See where this leads: the AI writes a new scene from what you did",
                         r.collidepoint(mouse), enabled)
            self.follow_button = r
            y += 46
        box = pygame.Rect(rect.x, y, rect.width, 40)
        _panel(self.screen, box, (20, 16, 13, 215), 10)
        pygame.draw.rect(self.screen, ACCENT if self.input else (95, 76, 58), box, 1, border_radius=10)
        if self.input:
            shown, color = self.input, INK
            while self.f_ui.size(shown + "|")[0] > box.width - 28:
                shown = shown[1:]
            shown += "|" if int(self.t * 2) % 2 else " "
        else:
            shown, color = "Or type anything you want to try, then press Enter…", DIM
        self.screen.blit(self.f_ui.render(shown, True, color), (box.x + 14, box.centery - self.f_ui.get_linesize() // 2))

    def draw_ending(self, rect):
        mouse = pygame.mouse.get_pos()
        _panel(self.screen, rect.inflate(20, 10))
        title = self.f_title.render(f"THE END: {self.eng.state.ending}", True, ACCENT)
        self.screen.blit(title, (rect.x + 10, rect.y))
        drift = self.f_small.render(f"Choices away from the original story: {self.eng.state.drift}", True, DIM)
        self.screen.blit(drift, (rect.right - drift.get_width() - 4, rect.y + 16))
        self.end_buttons = []
        go_on = pygame.Rect(rect.x, rect.y + 46, rect.width, 40)
        label = ("✦  Continue the story: the AI writes what happens next" if self.improviser else
                 "✦  Continue the story (needs the AI narrator: start with --llm qwen3:1.7b)")
        self._button(go_on, label, go_on.collidepoint(mouse), self.improviser is not None and self.busy is None)
        self.end_buttons.append((go_on, "continue"))
        if self.busy:
            self.screen.blit(self.f_place.render(f"{self.busy}…", True, DIM), (go_on.right - 220, go_on.y + 10))
        bw = (rect.width - 36) // 4
        for i, (label, action) in enumerate([("Story map", "map"), ("Play again", "again"),
                                             ("Another story", "menu"), ("Quit", "quit")]):
            r = pygame.Rect(rect.x + i * (bw + 12), rect.y + 92, bw, 38)
            self._button(r, label, r.collidepoint(mouse))
            self.end_buttons.append((r, action))

    def draw_details(self):
        w, h = self.screen.get_size()
        r = pygame.Rect(0, 0, 440, min(h - 100, 580))
        r.center = (w // 2, h // 2)
        _panel(self.screen, r, (10, 8, 7, 235))
        x, y = r.x + 24, r.y + 20
        s = self.eng.state
        self.screen.blit(self.f_place.render(self.pack.title, True, INK), (x, y))
        y += 36
        self.screen.blit(self.f_small.render("CHARACTERS", True, ACCENT), (x, y))
        y += 22
        for cid, c in self.pack.characters.items():
            alive = s.alive.get(cid, True)
            surf = self.f_small.render(c.get("name", cid) + ("" if alive else "  †"), True, INK if alive else DEAD)
            self.screen.blit(surf, (x, y))
            if not alive:
                pygame.draw.line(self.screen, DEAD, (x, y + 9), (x + surf.get_width() - 16, y + 9))
            y += 19
        y += 12
        if s.stats:
            self.screen.blit(self.f_small.render("STANDING", True, ACCENT), (x, y))
            y += 22
            for k, v in s.stats.items():
                self.screen.blit(self.f_small.render(f"{k.replace('_', ' ').capitalize()}: {v:+d}", True, INK), (x, y))
                y += 19
        foot = f"AI narrator: {self.llm}" if "narrator" in self.kwargs else "Plain text (no AI)"
        self.screen.blit(self.f_small.render(f"Drift from the original: {s.drift}    ·    {foot}", True, DIM),
                         (x, r.bottom - 30))

    def draw_map(self):
        """The original story as a line, your path through it, and every scene the AI invented."""
        w, h = self.screen.get_size()
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((6, 5, 4, 252))
        self.screen.blit(veil, (0, 0))
        if getattr(self, "_canon_for", None) is not self.pack:
            self._canon, self._canon_for = canon_path(self.pack), self.pack
        canon = [b for b in self._canon if not self.pack.beats[b].get("ending")] + \
                [b for b in self._canon if self.pack.beats[b].get("ending")]
        title = self.f_title.render("Your story and the original", True, INK)
        self.screen.blit(title, (40, 30))
        x0, x1, y0 = 70, w - 70, 150
        step = (x1 - x0) / max(1, len(canon) - 1)
        pos = {b: (x0 + i * step, y0) for i, b in enumerate(canon)}
        # the original story
        pygame.draw.line(self.screen, (90, 80, 70), (x0, y0), (x1, y0), 3)
        for b, (x, y) in pos.items():
            pygame.draw.circle(self.screen, (120, 108, 95), (int(x), y), 7)
        self.screen.blit(self.f_small.render("THE ORIGINAL STORY", True, DIM), (x0, y0 - 34))
        # the player's path: canon beats sit on the line; others branch below it
        depth, last_x, pts, invented, off = 0, x0, [], 0, 0
        seen = []
        for b in self.visited:
            if seen and seen[-1] == b:
                continue
            seen.append(b)
            beat = self.pack.beats[b]
            if b in pos and not beat.get("improvised"):
                x, y = pos[b]
                depth = 0
            else:
                depth = min(depth + 1, 7)
                x, y = min(x1, last_x + step * 0.8), y0 + 60 * depth
                off += 1
                invented += bool(beat.get("improvised"))
            pts.append((x, y, b))
            last_x = x
        for (xa, ya, _), (xb, yb, _) in zip(pts, pts[1:]):
            pygame.draw.line(self.screen, ACCENT, (int(xa), int(ya)), (int(xb), int(yb)), 3)
        for i, (x, y, b) in enumerate(pts):
            beat = self.pack.beats[b]
            if beat.get("improvised"):
                r = 9 + 2 * math.sin(self.t * 4 + i)
                pygame.draw.circle(self.screen, (255, 210, 120), (int(x), int(y)), int(r))
                pygame.draw.circle(self.screen, (255, 245, 210), (int(x), int(y)), 4)
            elif beat.get("ending"):
                pygame.draw.rect(self.screen, ACCENT, (int(x) - 8, int(y) - 8, 16, 16))
            else:
                pygame.draw.circle(self.screen, ACCENT, (int(x), int(y)), 8)
        if pts:
            x, y, _ = pts[-1]
            here = self.f_small.render("you are here", True, INK)
            self.screen.blit(here, (int(x) - here.get_width() // 2, int(y) + 14))
        endings = [b for b in self.pack.beats if self.pack.beats[b].get("ending")]
        reached = {b for b in seen if b in endings}
        stats = [f"Scenes you have seen: {len(seen)}",
                 f"Off the original path: {off}",
                 f"Scenes the AI invented for you: {invented}  (no one else has read them)",
                 f"Endings written by the author: {len(endings)}  ·  found: {len(reached)}",
                 "Endings the AI can invent: unlimited. Type anything, then press ✦."]
        yy = h - 40 - 26 * len(stats)
        for s in stats:
            self.screen.blit(self.f_ui.render(s, True, INK if "AI" not in s else ACCENT), (40, yy))
            yy += 26
        hint = self.f_small.render("click or press M to close", True, DIM)
        self.screen.blit(hint, (w - hint.get_width() - 40, h - 36))

    def draw_toasts(self):
        now = time.time()
        self.toasts = [(m, e) for m, e in self.toasts if e > now]
        w, _ = self.screen.get_size()
        y = 50
        for msg, _ in self.toasts[-3:]:
            lines = wrap(msg, self.f_small, 520)
            r = pygame.Rect(w - 560, y, 540, 16 + 18 * len(lines))
            _panel(self.screen, r, (70, 30, 25, 230), 8)
            for i, ln in enumerate(lines):
                self.screen.blit(self.f_small.render(ln, True, INK), (r.x + 10, r.y + 8 + i * 18))
            y = r.bottom + 8

    # ----------------------------------------------------------------- events
    def handle(self, e) -> bool:
        """Returns False to quit."""
        if e.type == pygame.QUIT:
            return False
        if e.type == pygame.VIDEORESIZE and self.mode == "story" and self.stage:
            self.stage.resize(self.screen.get_size())
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
            if self.eng.done and not self.is_cutaway and self._text_shown() and not self.card:
                if self.show_map:
                    self.show_map = False
                    return True
                for r, action in getattr(self, "end_buttons", []):
                    if r.collidepoint(e.pos):
                        return self._end_action(action)
                return True
            if self.show_map:
                self.show_map = False
                return True
            for i, r in enumerate(getattr(self, "choice_buttons", [])):
                if r.collidepoint(e.pos) and not self.revealing():
                    self.choose(i)
                    return True
            fb = getattr(self, "follow_button", None)
            if fb and fb.collidepoint(e.pos):
                self.follow()
                return True
            self.advance()                       # click anywhere else: skip / continue
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.mode = "menu"
            elif e.key == pygame.K_TAB:
                self.details = not self.details
            elif e.unicode in ("m", "M") and not self.input:
                self.show_map = not self.show_map
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.input:
                    self.submit()
                else:
                    self.advance()
            elif e.key == pygame.K_SPACE and not self.input:
                self.advance()
            elif e.key == pygame.K_BACKSPACE:
                self.input = self.input[:-1]
            elif e.key in (pygame.K_PAGEUP, pygame.K_UP) and not self.input:
                self.scroll -= 120
            elif e.key in (pygame.K_PAGEDOWN, pygame.K_DOWN) and not self.input:
                self.scroll += 120
            elif e.unicode and e.unicode.isprintable():
                if not self.input and e.unicode.isdigit() and not self.eng.done:
                    if not self.revealing():
                        self.choose(int(e.unicode) - 1)
                elif not self.eng.done:
                    self.input += e.unicode
        return True

    def _end_action(self, action):
        if action == "quit":
            return False
        if action == "map":
            self.show_map = True
            return True
        if action == "continue":
            self.continue_story()
            return True
        if action == "again":
            self.start(self.pack_name)
        else:
            self.mode = "menu"
        return True

    def run(self):
        last = time.time()
        running = True
        while running:
            for e in pygame.event.get():
                running = self.handle(e) and running
            now = time.time()
            self._poll_job()
            self.tick(min(0.1, now - last))
            last = now
            self.draw()
            self.clock.tick(30)
        pygame.quit()


def main(pack=None, llm=None, book_style=False):
    StoryGUI(pack, llm, book_style).run()


if __name__ == "__main__":
    main()
