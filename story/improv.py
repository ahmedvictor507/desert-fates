"""Improvised scenes: when the player goes off-script, the AI writes the next scene.

The model proposes a scene as JSON; `validate_scene` turns it into an ordinary beat or rejects
it. Only characters who exist and are alive may appear, the text must be a sensible length,
and there are always exactly two choices:

  * "continue" — keep going down this new path (choosing it improvises another scene), and
  * "return"   — a way back toward the original story, wired to the canon beat the player
                 left (so a story can wander off forever, or come home).

The engine inserts the beat with `StoryEngine.add_improvised` and plays it like any other.
"""
from __future__ import annotations

import json
import re

from .cast import present

IMPROVISE = "__improvise__"     # a choice "next" meaning: ask the AI for the next scene


def return_target(pack, beat_id: str) -> str:
    """Where 'back to the original story' leads from here: the canon continuation of the
    last pack beat (improvised beats remember theirs)."""
    beat = pack.beats[beat_id]
    if beat.get("improvised"):
        return beat["return_to"]
    choices = beat.get("choices", [])
    canon = [c for c in choices if c.get("canon", True) and c["next"] != IMPROVISE]
    if canon or choices:
        return (canon or choices)[0]["next"]
    return beat_id


def _seen_text(beat: dict, state) -> str:
    """The beat's text as the player saw it (its first matching variant, if any)."""
    from .effects import conditions_met
    return next((v["text"] for v in beat.get("variants", []) if conditions_met(v.get("when"), state)),
                beat.get("text", ""))


def director_prompt(pack, state, beat_id: str, action: str) -> str:
    """Shared by inference and training so what is trained is what is run."""
    beat = pack.beats[beat_id]
    alive = {c: pack.characters[c].get("name", c) for c, a in state.alive.items() if a}
    dead = [pack.characters[c].get("name", c) for c, a in state.alive.items() if not a]
    recent = [label for _, label in state.history[-6:]]
    home = pack.beats.get(return_target(pack, beat_id), {})
    home_hint = re.split(r"(?<=[.!?])\s", home.get("text", "").strip(), maxsplit=1)[0][:200]
    if home.get("ending"):
        back = "<one short sentence: an option that lets the story come to rest here>"
    else:
        back = ("<one short sentence: an option that steers back toward the original story, "
                f"which next goes: {home_hint}>")
    if beat.get("ending"):
        situation = (f"The written story has ended here (\"{beat['ending']}\"), but the player wants it to "
                     f"go on: \"{action}\"\n\nWrite the NEXT scene: what happens after this ending. ")
    else:
        situation = (f"The player does something the story never planned: \"{action}\"\n\n"
                     "Write the NEXT scene. Start with the immediate result of that exact action (it may "
                     "succeed or fail, but it happens), then what it changes. ")
    player = pack.characters.get(pack.player, {}).get("name", "the player")
    here = [pack.characters[c].get("name", c) for c in present(pack, beat, state) if c != pack.player]
    return (
        f"You are the game master of an interactive story: {pack.title}.\n{pack.intro}\n"
        f"The player is {player}. Characters alive (id: name): {json.dumps(alive)}\n"
        + (f"Dead (they cannot appear or speak): {', '.join(dead)}\n" if dead else "")
        + (f"Recent choices: {' / '.join(recent)}\n" if recent else "")
        + (f"With the player right now: {', '.join(here)}. Keep them in the scene unless it says why they "
           "are gone.\n" if here else "")
        + f"Current scene: {_seen_text(beat, state)[:500]}\n"
        + situation +
        "Stay true to this world's tone, politics and rules. "
        "Consequences can be large: alliances, betrayals, deaths, discoveries.\n"
        "Reply with ONLY a JSON object:\n"
        '{"place": "<where, a few words>", '
        '"text": "<the scene, 80-140 words, second person, present tense, ending at a decision>", '
        '"cast": ["<ids of characters present>"], '
        '"choice_continue": "<one short sentence: a bold option that pushes further down this new path>", '
        f'"choice_return": "{back}"}}'
    )


def _label(value) -> str:
    """A choice label: first sentence, at most 140 characters."""
    s = re.split(r"(?<=[.!?])\s", str(value or "").strip(), maxsplit=1)[0].strip()
    return s if len(s) <= 140 else s[:137].rsplit(" ", 1)[0] + "…"


def _extract_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def validate_scene(data, pack, state, return_to: str) -> dict | None:
    """Turn a model proposal into a beat, or None if it doesn't hold up."""
    if not isinstance(data, dict):
        return None
    text = str(data.get("text", "")).strip()
    a, b = _label(data.get("choice_continue")), _label(data.get("choice_return"))
    if not (60 <= len(text) <= 2000 and a and b):
        return None
    home = pack.beats.get(return_to, {}).get("text", "")
    if b and b.rstrip(".…") in home:            # copied the next canon scene instead of an option
        b = "Let events return to the course they were on."
    if pack.beats.get(return_to, {}).get("ending"):
        b = b or "Let the story end here."
    proposed = [c for c in data.get("cast", []) if isinstance(c, str) and c in pack.characters
                and state.alive.get(c, True)]
    # small models often list everyone; keep people the scene names or who were already here
    here = set(present(pack, pack.beats.get(state.beat, {}), state))
    named = set(present(pack, {"text": text}, state))
    cast = [c for c in proposed if c in named or c in here] or [c for c in named if c in pack.characters]
    if len(cast) <= 1:                          # nobody listed: the people already here stay
        cast = cast + [c for c in present(pack, pack.beats.get(state.beat, {}), state) if c not in cast]
    if pack.player and state.alive.get(pack.player, True):
        cast = [pack.player] + [c for c in cast if c != pack.player]     # the player always leads
    return {
        "text": text,
        "place": str(data.get("place", "")).strip()[:120],
        "stage": {"cast": cast[:6]},
        "improvised": True,
        "return_to": return_to,
        "choices": [
            {"label": a, "next": IMPROVISE, "canon": False},
            {"label": b, "next": return_to, "canon": False},
        ],
    }


class Improviser:
    """Asks a model (any generate(prompt) -> str) for the next scene. Returns a beat or None."""

    def __init__(self, generate, retries: int = 1):
        self.generate = generate
        self.retries = retries
        self.last_error: str | None = None

    def scene(self, engine, action: str) -> dict | None:
        pack, state = engine.pack, engine.state
        prompt = director_prompt(pack, state, state.beat, action)
        target = return_target(pack, state.beat)
        for _ in range(1 + self.retries):
            try:
                beat = validate_scene(_extract_json(self.generate(prompt)), pack, state, target)
            except Exception as e:          # model offline etc.
                self.last_error = str(e)
                return None
            if beat:
                return beat
        self.last_error = "the AI's scene didn't hold together; try again or pick a choice"
        return None
