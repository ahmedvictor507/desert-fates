"""LLM player. `generate` is any callable str -> str (llama.cpp, Ollama, HF...).

The same prompt/parse path is used for inference and for RL rollouts, so what
you train is exactly what players run.
"""
import re

from env.sand_env import render_text

SYSTEM = ("You are an explorer on a desert planet with giant sandworms. Survive, "
          "gather spice, and reach your goal. Reply with exactly one action line.")
_ACTION = re.compile(r'(MOVE\s+[NSEW]|GATHER|DRINK|REST|FREEFORM\s+".*?")', re.I | re.S)


def parse_action(text: str) -> str:
    m = _ACTION.search(text)
    return m.group(1).strip() if m else "REST"


class LLMAgent:
    def __init__(self, generate):
        self.generate = generate

    def prompt(self, env) -> str:
        return f"{SYSTEM}\n\n{render_text(env.engine.state, env.scenario)}\n\nAction:"

    def act(self, env) -> str:
        return parse_action(self.generate(self.prompt(env)))
