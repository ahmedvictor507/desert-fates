"""Optional local-LLM hooks via Ollama (http://localhost:11434). stdlib only.

Both classes take any `generate(prompt) -> str` callable, so tests and other
backends (llama.cpp, HF) can be swapped in. Output is always validated by
story.effects before it touches game state.
"""
from __future__ import annotations

import json
import urllib.request

STYLE = ("Write in a terse, brooding, aristocratic voice: short aphorisms, political "
         "undertones, a sense of inevitability. Do not add or remove plot facts.")


class OllamaUnavailable(RuntimeError):
    pass


def ollama_generate(model: str, json_mode: bool = False, host: str = "http://localhost:11434"):
    def gen(prompt: str) -> str:
        body = {"model": model, "prompt": prompt, "stream": False, "think": False}
        if json_mode:
            body["format"] = "json"
        req = urllib.request.Request(f"{host}/api/generate", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())["response"]
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


def narrator_prompt(text, state, pack, last_choice, excerpt: str = "") -> str:
    """Shared by inference and training so what is trained is what is run."""
    ref = (f"Reference passage from the original book. Match its voice, rhythm and vocabulary. "
           f"Do NOT copy its sentences.\n<<<\n{excerpt}\n>>>\n\n" if excerpt else f"{STYLE}\n\n")
    choice = f"The player just chose: {last_choice}\n" if last_choice else ""
    state_txt = _state_summary(state, pack)
    return (
        "You are the narrator of an interactive story.\n" + ref +
        "Rewrite the scene below as second-person prose (\"you\" is the player character), "
        "150 words or fewer. Keep every fact in the scene. Add no new events, characters or outcomes. "
        "Do not offer choices; they are shown separately. Output only the prose.\n"
        + (state_txt + "\n" if state_txt else "") + choice +
        f"\nScene:\n{text}")


class OllamaNarrator:
    """Rewrites beat text in the source's voice. Falls back to the pack text on any failure,
    and rejects output that copies 12+ consecutive words from the book."""

    def __init__(self, model: str = "", generate=None):
        self.generate = generate or ollama_generate(model)
        self._cache: dict = {}
        self.last_error: str | None = None

    def narrate(self, text, state, pack, last_choice):
        from . import sources
        if not text:
            return text
        beat = pack.beats.get(state.beat, {})
        excerpt = sources.style_excerpt(beat)
        key = (state.beat, text, last_choice, tuple(sorted(k for k, v in state.alive.items() if not v)))
        if key in self._cache:
            return self._cache[key]
        try:
            out = self.generate(narrator_prompt(text, state, pack, last_choice, excerpt)).strip()
        except Exception as e:
            self.last_error = str(e)
            return text  # fall back to pack prose if the model is unavailable
        if excerpt and sources.copied_span(out, excerpt):
            self.last_error = "narration copied the source verbatim; using pack text"
            out = ""
        out = out or text
        self._cache[key] = out
        return out


def interpreter_prompt(text, state, pack, beat) -> str:
    """Shared by inference and RL training so what is trained is what is run."""
    return (
        "You are the rules arbiter of an interactive story. The player tries an "
        "action. Reply with ONLY a JSON object with optional keys: "
        '"flags" (str->bool), "stats" (str->int), "kill" (list of character ids), '
        f'"message" (one sentence of outcome), "next" (beat id).\n'
        f"Characters: {list(pack.characters)}; stats: {list(pack.stats)}; "
        f"beats you may jump to: {list(pack.beats)}\n"
        f"Current scene: {beat.get('text', '')[:400]}\nPlayer action: {text}\n"
        'Reply format: {"flags": {"<new_snake_case_flag>": true}, "message": "<one sentence of outcome>"}\n'
        "If the action is impossible or nonsensical, reply {}. Output the JSON object and nothing else.")


class OllamaInterpreter:
    def __init__(self, model: str, generate=None):
        self.generate = generate or ollama_generate(model, json_mode=True)

    def interpret(self, text, state, pack, beat):
        try:
            data = json.loads(self.generate(interpreter_prompt(text, state, pack, beat)))
        except Exception:
            return None
        return data or None
