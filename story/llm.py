"""Optional local-LLM hooks via Ollama (http://localhost:11434). stdlib only.

Both classes take any `generate(prompt) -> str` callable, so tests and other
backends (llama.cpp, HF) can be swapped in. Output is always validated by
story.effects before it touches game state.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

STYLE = ("Write in a terse, brooding, aristocratic voice: short aphorisms, political "
         "undertones, a sense of inevitability. Do not add or remove plot facts.")


class OllamaUnavailable(RuntimeError):
    pass


def ollama_generate(model: str, json_mode: bool = False, host: str = "http://localhost:11434",
                    num_ctx: int = 4096, max_tokens: int = 700):
    """Returns generate(prompt) -> str. If the GPU runs out of memory (common on small boards
    with a desktop open), retries on the CPU and stays there; `gen.notice` says so."""
    options = {"num_ctx": num_ctx, "num_predict": max_tokens}   # cap: JSON mode can run away

    def call(prompt):
        body = {"model": model, "prompt": prompt, "stream": False, "think": False, "options": options}
        if json_mode:
            body["format"] = "json"
        req = urllib.request.Request(f"{host}/api/generate", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())["response"]
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", str(e))
            except Exception:
                msg = str(e)
            raise OllamaUnavailable(msg) from None

    def gen(prompt: str) -> str:
        try:
            return call(prompt)
        except OllamaUnavailable as e:
            if "out of memory" not in str(e) or options.get("num_gpu") == 0:
                raise
            options["num_gpu"] = 0
            gen.notice = ("Not enough GPU memory for the model, so it is running on the CPU (slower). "
                          "Closing other apps (e.g. the web browser) and restarting the game may fix it.")
            return call(prompt)

    gen.notice = None
    return gen


def check_ollama(model: str, host: str = "http://localhost:11434") -> str | None:
    """None if `model` is ready to use, else a human-readable fix."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as r:
            names = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return ("Ollama is not running. Install it from https://ollama.com/download "
                "(Linux: curl -fsSL https://ollama.com/install.sh | sh), then start it with: ollama serve")
    if not any(n == model or n.split(":")[0] == model or n == f"{model}:latest" for n in names):
        return f"Model {model!r} is not downloaded yet. Run: ollama pull {model}"
    return None


def _state_summary(state, pack) -> str:
    dead = [pack.characters[c].get("name", c) for c, alive in state.alive.items() if not alive]
    flags = [k for k, v in state.flags.items() if v]
    parts = []
    if dead:
        parts.append("Dead (never show them acting or speaking now): " + ", ".join(dead))
    if flags:
        parts.append("Story so far has these facts: " + ", ".join(flags))
    return "\n".join(parts)


def _pending(pack, state) -> str:
    beat = pack.beats.get(state.beat, {})
    labels = [c["label"] for c in beat.get("choices", [])]
    if not labels:
        return ""
    return ("The player has NOT decided yet between: " + " / ".join(labels) +
            ". Do not describe the player doing any of these.\n")


def _names(pack, ids):
    return ", ".join(pack.characters[c].get("short") or pack.characters[c].get("name", c) for c in ids)


def narrator_prompt(text, state, pack, last_choice, excerpt: str = "", place: str = "",
                    speakers: list | None = None) -> str:
    """Shared by inference and training so what is trained is what is run."""
    state_txt = _state_summary(state, pack)
    others = [c for c in (speakers or []) if c != pack.player]
    first = _names(pack, others[:1])
    me = _names(pack, [pack.player]) if pack.player else ""
    dialogue = (
        "\nAfter the prose, write DIALOGUE: on its own line, then 2 or 3 short lines spoken aloud, one per "
        f"line, like this:\nDIALOGUE:\n{first}: <what {first} says>\n" + (f"{me}: <what you say>\n" if me else "")
        + f"Only these people may speak: {_names(pack, others)}" + (f" and {me}" if me else "")
        + (f". They call the player {me}" if me else "") + ". The words must fit the scene notes.\n"
    ) if others else ""
    return (
        "You are the narrator of an interactive novel. Turn the SCENE NOTES into a vivid scene "
        "of 100-150 words in second person (\"you\" is the player character), present tense.\n"
        "- Describe the place with the senses: light, heat, smell, sound. Stay true to the PLACE.\n"
        "- Include one private thought of the player character, written in italics.\n"
        "- Turn reported speech into one or two short lines of dialogue.\n"
        "- Keep every event in the notes and who does what to whom. Add no events, people or decisions.\n"
        "- Stop before the player acts: do not describe what the player does next. Do not list choices.\n"
        + (f"- Match the voice of this passage from the original book (tone only, never copy its sentences):"
           f"\n<<<\n{excerpt[:1200]}\n>>>\n" if excerpt else f"- {STYLE}\n")
        + (state_txt + "\n" if state_txt else "")
        + (f"The player just chose: {last_choice}\n" if last_choice else "")
        + _pending(pack, state)
        + (f"\nPLACE: {place}" if place else "")
        + dialogue
        + f"\nSCENE NOTES:\n{text}\n\nSCENE:\n")


class OllamaNarrator:
    """Rewrites beat text in the source's voice. Falls back to the pack text on any failure,
    and rejects output that copies 12+ consecutive words from the book."""

    def __init__(self, model: str = "", generate=None, excerpt_chars: int = 0):
        # excerpt_chars > 0 adds a passage from the imported book as a style reference. Small
        # models (< 4B) tend to retell the passage instead of the scene, so it is off by default.
        self.generate = generate or ollama_generate(model)
        self.excerpt_chars = excerpt_chars
        self._cache: dict = {}
        self.last_error: str | None = None

    def narrate(self, text, state, pack, last_choice):
        from . import sources
        from .cast import present
        if not text:
            return text
        beat = pack.beats.get(state.beat, {})
        speakers = present(pack, beat, state)
        excerpt = sources.style_excerpt(beat, self.excerpt_chars) if self.excerpt_chars else ""
        key = (state.beat, text, last_choice, tuple(sorted(k for k, v in state.alive.items() if not v)))
        if key in self._cache:
            return self._cache[key]
        try:
            out = self.generate(narrator_prompt(text, state, pack, last_choice, excerpt, beat.get("place", ""), speakers)).strip()
        except Exception as e:
            self.last_error = str(e)
            return text  # fall back to pack prose if the model is unavailable
        if excerpt and sources.copied_span(out, excerpt):
            self.last_error = "narration copied the source verbatim; using pack text"
            out = ""
        out = out or text
        self._cache[key] = out
        return out


def _present_ids(pack, beat, state):
    from .cast import present
    return [c for c in present(pack, beat, state) if c != pack.player]


def interpreter_prompt(text, state, pack, beat) -> str:
    """Shared by inference and RL training so what is trained is what is run."""
    return (
        "You are the rules arbiter of an interactive story. The player tries an "
        "action. Reply with ONLY a JSON object with optional keys: "
        '"flags" (str->bool), "stats" (str->int), "kill" (list of character ids), '
        '"message" (one sentence of outcome), '
        '"say" ({"who": id of a person present, "line": the words they answer aloud}).\n'
        f"Characters: {list(pack.characters)}; stats: {list(pack.stats)}\n"
        f"Present in this scene: {_present_ids(pack, beat, state)}\n"
        f"Current scene: {beat.get('text', '')[:400]}\n"
        + _pending(pack, state) +
        f"Player action: {text}\n"
        "Describe only the direct result of this action. Never resolve the undecided choices above.\n"
        'Reply format: {"flags": {"<short_name_for_what_happened>": true}, "message": "<one sentence of outcome>"}\n'
        'If the player speaks to someone present, that person answers aloud, e.g. '
        '{"message": "<one sentence>", "say": {"who": "<their id>", "line": "<their answer>"}}\n'
        "The action must be physically possible right now, in this scene, with what is here. "
        "If it is impossible here (e.g. something that is not present), reply {}. "
        "Output the JSON object and nothing else.")


class OllamaInterpreter:
    def __init__(self, model: str, generate=None):
        self.generate = generate or ollama_generate(model, json_mode=True)

    def interpret(self, text, state, pack, beat):
        try:
            data = json.loads(self.generate(interpreter_prompt(text, state, pack, beat)))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        if isinstance(data.get("flags"), dict):
            data["flags"] = clean_flags(data["flags"])
        # Only the pack's own choices and rules move the story between scenes; a model
        # picking a beat id skips whole scenes (seen in play: jumped past two beats).
        data.pop("next", None)
        say = data.get("say")
        if say is not None and not (isinstance(say, dict) and say.get("who") in _present_ids(pack, beat, state)):
            data.pop("say")                          # only people in the scene can answer
        if "say" not in data and isinstance(data.get("message"), str):
            from .cast import present, speech_from_message
            rest, spoken = speech_from_message(data["message"], text, pack, present(pack, beat, state))
            if spoken:
                data["message"], data["say"] = rest or data["message"], {"who": spoken[0], "line": spoken[1]}
        return data or None


_PLACEHOLDER_FLAGS = {"new_snake_case_flag", "short_name_for_what_happened", "flag", "flag_name"}


def clean_flags(flags: dict) -> dict:
    """Normalise model-invented flag names to snake_case and drop copied placeholders."""
    out = {}
    for k, v in flags.items():
        name = re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")[:40]
        if name and name not in _PLACEHOLDER_FLAGS and not name[0].isdigit():
            out[name] = v
    return out
