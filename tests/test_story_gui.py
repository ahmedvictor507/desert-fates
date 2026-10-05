"""Smoke tests: drive the story window headlessly, including transitions and cutaways."""
import os

import pytest

pygame = pytest.importorskip("pygame")
os.environ["SDL_VIDEODRIVER"] = "dummy"


def settle(g, max_steps=400):
    """Advance simulated time until the window waits for the player (choices or ending)."""
    for _ in range(max_steps):
        g._poll_job()
        g.tick(0.1)
        if g.phase == "play" and g.busy is None:
            if g.card or g.revealing():
                g.advance()
            elif g.is_cutaway:
                g.advance()
            else:
                break
    g.draw()


def key(g, ch):
    g.handle(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=ch))


def test_window_plays_salt_exile_to_an_ending():
    from game.story_gui import StoryGUI
    g = StoryGUI("salt_exile")
    settle(g)
    assert g.mode == "story" and any(kind == "scene" for kind, _ in g.page)
    assert g.stage.actors                                # someone is on stage
    for ch in "pray":
        key(g, ch)
    g.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))
    settle(g)
    assert ("you", "pray") in g.page and any("readier" in t for k, t in g.page if k == "message")
    for _ in range(20):
        if g.eng.done:
            break
        key(g, "1")
        assert g.phase == "exit"                          # choosing starts the exit animation
        settle(g)
    assert g.eng.done and g.end_buttons
    buttons = dict((action, r) for r, action in g.end_buttons)
    g.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=buttons["map"].center))
    assert g.show_map
    g.draw()                                              # the story map renders
    g.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5)))
    assert not g.show_map
    g.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=buttons["again"].center))
    settle(g)
    assert not g.eng.done                                 # "Play again" restarted
    pygame.quit()


def test_cutaway_is_its_own_scene(tmp_path):
    import json
    from game.story_gui import StoryGUI
    from story.pack import SEARCH_DIRS
    pack = {"title": "Cut", "intro": "", "start": "a", "player": "hero",
            "characters": {"hero": {"name": "Hero"}, "villain": {"name": "Villain Grim"}},
            "beats": {"a": {"text": "Start.", "choices": [{"label": "Run away", "next": "c"},
                                                           {"label": "Stay", "next": "c"}]},
                      "c": {"text": "[Far away] Villain Grim plots.", "auto": [{"next": "end"}]},
                      "end": {"text": "Done.", "ending": "E"}}}
    p = SEARCH_DIRS[1] / "_test_cutaway.json"
    p.write_text(json.dumps(pack))
    try:
        g = StoryGUI("_test_cutaway")
        settle(g)
        key(g, "1")
        assert g.stage.player_actor().tx < 0 or g.stage.player_actor().tx > g.stage.w   # ran off stage
        for _ in range(40):                       # play the transition, stop at the cutaway
            g._poll_job()
            g.tick(0.1)
        assert g.is_cutaway and g.showing == "c"
        assert [a.cid for a in g.stage.actors] == ["villain"]
        settle(g)
        assert g.showing == "end" and g.eng.done
    finally:
        p.unlink()
        pygame.quit()


def test_ai_failure_never_crashes_the_window():
    from game.story_gui import StoryGUI
    g = StoryGUI("salt_exile")
    settle(g)
    g.run_job("x", lambda: 1 / 0, lambda r: None)
    settle(g)
    assert any("went wrong" in m for m, _ in g.toasts)
    pygame.quit()


def test_choice_verbs_map_to_motions():
    from game.stage import motion_for
    assert motion_for("Run for the door.") == "run"
    assert motion_for("Bite now, while you still can.") == "lunge"
    assert motion_for("Go with him.") == "together"
    assert motion_for("Pull your hand free.") == "back"
    assert motion_for("Tell Thufir Hawat that Yueh is hiding something.") == "speak"
    assert motion_for("Endure. Keep your hand in the box.") == "still"


def test_short_names():
    from game.stage import short_name
    assert short_name("x", {"name": "Reverend Mother Gaius Helen Mohiam"}) == "Mohiam"
    assert short_name("x", {"name": "Gurney Halleck"}) == "Gurney Halleck"
    assert short_name("x", {"name": "Duke Leto Atreides", "short": "Duke Leto"}) == "Duke Leto"


def test_dialogue_bubbles_and_ai_paths(tmp_path):
    import json
    from game.story_gui import StoryGUI
    from story.improv import Improviser
    from story.pack import SEARCH_DIRS
    pack = {"title": "Talk", "intro": "", "start": "a", "player": "hero",
            "characters": {"hero": {"name": "Hero"}, "sage": {"name": "Old Sage"}},
            "beats": {"a": {"text": "The Old Sage waits.", "dialogue": [["sage", "Speak, child."], ["ghost", "boo"]],
                            "choices": [{"label": "Bow", "next": "end"}, {"label": "Leave", "next": "end"}]},
                      "end": {"text": "Done.", "ending": "E"}}}
    p = SEARCH_DIRS[1] / "_test_talk.json"
    p.write_text(json.dumps(pack))
    try:
        g = StoryGUI("_test_talk")
        settle_until_speech = 0
        for _ in range(60):
            g._poll_job()
            g.tick(0.1)
            if g.stage.bubble:
                settle_until_speech = 1
                break
            if g.phase == "play" and (g.card or g.revealing()):
                g.advance()
        assert settle_until_speech and g.stage.bubble[0] == "sage"       # unknown speaker skipped
        g.draw()
        # free text accepted -> the ✦ follow button appears when an AI is available
        reply = json.dumps({"place": "a cave", "text": "The Old Sage leads you into a cave of echoes. " * 3,
                            "cast": ["sage"], "choice_continue": "Go deeper.", "choice_return": "Go back."})
        g.improviser = Improviser(lambda prompt: reply)
        g.eng.pack.freeform_rules.append({"keywords": ["sing"], "effect": {"message": "You sing."}})
        settle(g)
        for ch in "I sing":
            key(g, ch)
        g.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))
        settle(g)
        assert g.can_follow == "I sing"
        g.follow()
        settle(g)
        assert g.showing.startswith("improv_") and "cave" in g.place
        assert g.eng.needs_improv(0)                     # its first choice keeps improvising
        key(g, "1")
        settle(g)
        assert g.showing == "improv_2"
        g.show_map = True
        g.draw()
    finally:
        p.unlink()
        pygame.quit()
