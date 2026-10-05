"""Smoke test: drive the story window headlessly from menu to ending."""
import os
import time

import pytest

pygame = pytest.importorskip("pygame")
os.environ["SDL_VIDEODRIVER"] = "dummy"


def _wait(g):
    for _ in range(200):
        g._poll_job()
        if not g.busy:
            break
        time.sleep(0.01)
    g.reveal_start = 0
    g.draw(0)


def _key(g, ch):
    g.handle(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=ch))
    _wait(g)


def test_window_plays_salt_exile_to_an_ending():
    from game.story_gui import StoryGUI
    g = StoryGUI("salt_exile")
    _wait(g)
    assert g.mode == "story" and any(kind == "scene" for kind, _ in g.page)
    for ch in "pray":
        g.handle(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=ch))
    g.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))
    _wait(g)
    assert ("you", "pray") in g.page and any("readier" in t for k, t in g.page if k == "message")
    for _ in range(20):
        if g.eng.done:
            break
        _key(g, "1")
    assert g.eng.done
    g.draw(0)
    assert g.end_buttons                              # ending screen drawn
    g.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=g.end_buttons[0][0].center))
    _wait(g)
    assert not g.eng.done                             # "Play again" restarted
    pygame.quit()


def test_ai_failure_never_crashes_the_window():
    from game.story_gui import StoryGUI
    g = StoryGUI("salt_exile")
    _wait(g)
    g.eng.choose = lambda i: (_ for _ in ()).throw(RuntimeError("boom"))
    g.run_job("x", lambda: 1 / 0, lambda r: None)
    _wait(g)
    assert any("went wrong" in m for m, _ in g.toasts)
    pygame.quit()
