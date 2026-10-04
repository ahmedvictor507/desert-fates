import pytest

from engine import Engine, load_scenario
from engine.effects import EffectError, validate


def make(seed=0, name="worm_path"):
    return Engine(load_scenario(name), seed=seed)


def test_determinism():
    a, b = make(3), make(3)
    for act in ["MOVE E", "MOVE S", "REST", "MOVE E"]:
        a.step(act), b.step(act)
    assert (a.state.x, a.state.y, a.state.worms) == (b.state.x, b.state.y, b.state.worms)


def test_invalid_action_penalised():
    e = make()
    assert e.step("DANCE")["valid"] is False
    assert e.step("GATHER")["valid"] is False  # no spice at sietch


def test_transform_needs_spice():
    e = make()
    e.step('FREEFORM "become the worm"')
    assert e.state.form == "human"
    e.state.spice = 3
    e.step('FREEFORM "I become the worm"')
    assert e.state.form == "worm" and "sand_swimming" in e.state.abilities


def test_worm_form_is_safe_and_cannot_gather():
    e = make()
    e.state.spice = 3
    e.step('FREEFORM "become the worm"')
    e.state.x, e.state.y = e.state.worms[0]
    e.step("REST")
    assert e.state.hp > 0
    assert e.step("GATHER")["valid"] is False


def test_effect_validation_rejects_bad_proposals():
    forms = {"human", "worm"}
    with pytest.raises(EffectError):
        validate({"teleport": 1}, forms)
    with pytest.raises(EffectError):
        validate({"transform": "god"}, forms)
    with pytest.raises(EffectError):
        validate({"stats": {"gold": 5}}, forms)
    assert validate({"stats": {"hp": 999}}, forms)["stats"]["hp"] == 10


def test_episode_terminates():
    e = make()
    for _ in range(200):
        e.step("REST")
    assert e.state.done


def test_llm_agent_parsing():
    from agents.llm_agent import parse_action
    assert parse_action("I think I should MOVE e now") == "MOVE e"
    assert parse_action('FREEFORM "become the worm"') == 'FREEFORM "become the worm"'
    assert parse_action("???") == "REST"
