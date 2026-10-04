"""Turns free-form text into an effect dict.

RuleInterpreter is deterministic and ships with the game. To use an LLM,
implement the same `interpret(text, state, scenario) -> dict | None` method
and pass it to Engine(interpreter=...); output is validated either way.
"""
from __future__ import annotations


class RuleInterpreter:
    def interpret(self, text: str, state, scenario) -> dict | None:
        low = text.lower()
        for rule in scenario.freeform_rules:
            if not any(k in low for k in rule["keywords"]):
                continue
            if self._requirements_met(rule.get("requires", {}), state):
                return rule["effect"]
            return {"message": rule.get("fail_message", "You can't do that now.")}
        return None

    @staticmethod
    def _requirements_met(req: dict, state) -> bool:
        if "form" in req and state.form != req["form"]:
            return False
        if "spice_min" in req and state.spice < req["spice_min"]:
            return False
        if "ability" in req and req["ability"] not in state.abilities:
            return False
        if req.get("at_sietch") and not state.at_sietch:
            return False
        return True
