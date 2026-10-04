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


def ollama_generate(model: str, json_mode: bool = False, host: str = "http://localhost:11434"):
    def gen(prompt: str) -> str:
        body = {"model": model, "prompt": prompt, "stream": False}
        if json_mode:
            body["format"] = "json"
        req = urllib.request.Request(f"{host}/api/generate", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["response"]
    return gen


class OllamaNarrator:
    def __init__(self, model: str, generate=None):
        self.generate = generate or ollama_generate(model)

    def narrate(self, text, state, pack, last_choice):
        prompt = (f"{STYLE}\nRewrite this passage in that voice, keeping every fact, "
                  f"in 120 words or fewer.\nThe player just chose: {last_choice}\n\nPassage:\n{text}")
        try:
            out = self.generate(prompt).strip()
        except Exception:
            return text  # fall back to canon prose if the model is unavailable
        return out or text


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
