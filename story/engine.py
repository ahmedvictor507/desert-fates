"""Story runner: canon spine + two options + free-text, with drift tracking.

Pure logic, no I/O. Plug in a Narrator (rewrites beat prose) and an
Interpreter (turns free text into a proposed effect) to use an LLM; both
default to deterministic, offline behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import effects
from .pack import Pack


@dataclass
class StoryState:
    beat: str
    flags: dict
    stats: dict
    alive: dict
    drift: int = 0          # how many non-canon choices so far
    history: list = field(default_factory=list)  # (beat, choice label)
    ending: str | None = None


class RuleInterpreter:
    """Matches free text against beat-level then global keyword rules."""

    def interpret(self, text: str, state, pack: Pack, beat: dict) -> dict | None:
        low = text.lower()
        for rule in beat.get("freeform_rules", []) + pack.freeform_rules:
            if any(k in low for k in rule["keywords"]) and effects.conditions_met(rule.get("when"), state):
                return {**rule.get("effect", {}), **({"next": rule["next"]} if "next" in rule else {})}
        return None


class ChainInterpreter:
    """Tries each interpreter in order; the first proposal wins. Used so a pack's own
    keyword rules always take priority over an LLM's guess."""

    def __init__(self, *interpreters):
        self.interpreters = interpreters

    def interpret(self, text, state, pack, beat):
        for it in self.interpreters:
            proposal = it.interpret(text, state, pack, beat)
            if proposal is not None:
                return proposal
        return None


class IdentityNarrator:
    def narrate(self, text: str, state, pack: Pack, last_choice: str | None) -> str:
        return text


class StoryEngine:
    def __init__(self, pack: Pack, interpreter=None, narrator=None):
        self.pack = pack
        self.interpreter = interpreter or RuleInterpreter()
        self.narrator = narrator or IdentityNarrator()
        self.state = StoryState(
            beat=pack.start, flags=dict(pack.flags), stats=dict(pack.stats),
            alive={cid: c.get("alive", True) for cid, c in pack.characters.items()})
        self.messages: list[str] = []
        self.trail: list[str] = []   # beats entered during the last step, incl. auto pass-throughs
        self.speech: list[tuple[str, str]] = []   # (character id, line) spoken during the last step
        self._last_choice: str | None = None
        self._enter(pack.start)

    # ---------------------------------------------------------------- reading
    @property
    def beat(self) -> dict:
        return self.pack.beats[self.state.beat]

    @property
    def done(self) -> bool:
        return self.state.ending is not None

    def text(self) -> str:
        beat = self.beat
        text = beat["text"]
        for v in beat.get("variants", []):
            if effects.conditions_met(v.get("when"), self.state):
                text = v["text"]
                break
        return self.narrator.narrate(text, self.state, self.pack, self._last_choice)

    def choices(self) -> list[dict]:
        return [c for c in self.beat.get("choices", []) if effects.conditions_met(c.get("when"), self.state)]

    # ---------------------------------------------------------------- acting
    def needs_improv(self, index: int) -> bool:
        """True if this choice leads somewhere the AI has to write first (see story.improv)."""
        from .improv import IMPROVISE
        opts = self.choices()
        return 0 <= index < len(opts) and opts[index]["next"] == IMPROVISE

    def choose(self, index: int, improvised: dict | None = None) -> None:
        opts = self.choices()
        if self.done or not 0 <= index < len(opts):
            raise IndexError("no such choice")
        c = opts[index]
        nxt = c["next"]
        if self.needs_improv(index):
            if improvised is None:
                raise ValueError("this choice needs an improvised scene (story.improv.Improviser)")
            nxt = self._add_beat(improvised)
        if not c.get("canon", True):
            self.state.drift += 1
        self._take(c.get("effects", {}), nxt, c["label"])

    def continue_after_ending(self, improvised: dict) -> None:
        """The written story ended, but the player wants more: enter an AI-written scene."""
        if not self.done:
            raise ValueError("the story has not ended")
        self.state.ending = None
        self.state.drift += 1
        self._take({}, self._add_beat(improvised), "(the story continues)")

    def follow(self, action: str, improvised: dict) -> None:
        """Go where the player's own action leads: enter an AI-written scene."""
        self.state.drift += 1
        self._take({}, self._add_beat(improvised), f"(you) {action}")

    def _add_beat(self, beat: dict) -> str:
        n = sum(1 for b in self.pack.beats if b.startswith("improv_")) + 1
        bid = f"improv_{n}"
        self.pack.beats[bid] = beat
        return bid

    def freeform(self, text: str) -> bool:
        """Try a free-text action. Returns True if the world accepted it."""
        self.messages = []
        self.trail = []
        self.speech = []
        if self.done:
            return False
        proposal = self.interpreter.interpret(text, self.state, self.pack, self.beat)
        if proposal is None:
            self.messages.append("The story resists. Nothing comes of it.")
            return False
        try:
            eff = effects.validate(proposal, self.pack)
        except effects.EffectError as e:
            self.messages.append(f"The world rejects that ({e}).")
            return False
        self.state.drift += 1
        nxt = eff.pop("next", None)
        self._take(eff, nxt, f'(you) {text}')
        return True

    # -------------------------------------------------------------- internals
    def _take(self, effect: dict, nxt: str | None, label: str) -> None:
        """Apply an effect, then enter `nxt` (None = stay in the current scene without re-entering it)."""
        self.messages = []
        self.trail = []
        self.speech = []
        eff = effects.validate(effect, self.pack)
        effects.apply(self.state, eff)
        if "message" in eff:
            self.messages.append(eff["message"])
        say = eff.get("say")
        if say and self.state.alive.get(say["who"], True):   # the dead stay silent
            self.speech.append((say["who"], say["line"]))
        self.state.history.append((self.state.beat, label))
        self._last_choice = label
        if nxt is not None:
            self._enter(nxt)

    def _enter(self, beat_id: str) -> None:
        for _ in range(50):  # auto-route chain, guard against cycles
            self.state.beat = beat_id
            self.trail.append(beat_id)
            beat = self.pack.beats[beat_id]
            on_enter = effects.validate(beat.get("on_enter", {}), self.pack)
            effects.apply(self.state, on_enter)
            if "message" in on_enter:
                self.messages.append(on_enter["message"])
            if beat.get("auto"):
                route = next(a for a in beat["auto"] if effects.conditions_met(a.get("when"), self.state))
                if beat.get("text"):
                    self.messages.append(beat["text"])
                beat_id = route["next"]
                continue
            break
        if self.pack.beats[self.state.beat].get("ending"):
            self.state.ending = self.pack.beats[self.state.beat]["ending"]
