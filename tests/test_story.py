import json

import pytest

from story import StoryEngine, load_pack
from story.effects import EffectError, validate
from story.llm import OllamaInterpreter, OllamaNarrator
from story.pack import PackError, Pack


def new():
    return StoryEngine(load_pack("salt_exile"))


def test_starter_pack_is_valid_and_every_ending_reachable():
    pack = load_pack("salt_exile")
    seen, frontier = set(), [pack.start]
    while frontier:
        b = frontier.pop()
        if b in seen:
            continue
        seen.add(b)
        beat = pack.beats[b]
        frontier += [c["next"] for c in beat.get("choices", [])] + [a["next"] for a in beat.get("auto", [])]
    endings = {b for b in pack.beats if pack.beats[b].get("ending")}
    assert endings <= seen


def test_every_decision_offers_at_least_two_options_in_all_states():
    pack = load_pack("salt_exile")
    for bid, beat in pack.beats.items():
        if beat.get("choices"):
            assert len(beat["choices"]) >= 2, bid


def test_canon_path_and_branch():
    e = new()
    e.choose(0)                       # accept
    assert e.state.beat == "arrival"
    e.choose(0)                       # trust Oren
    assert e.state.beat == "betrayal_oren"
    assert e.state.alive["lord"] is False
    assert e.state.drift == 0


def test_non_canon_choice_increments_drift():
    e = new()
    e.choose(1)                       # refuse
    assert e.state.drift == 1 and e.state.flags["defied_crown"]


def test_conditional_choices():
    e = new()
    for i in (0, 1, 0):               # accept, meet clans, ride with clans
        e.choose(i)
    assert e.state.beat == "clan_camp"
    e.choose(1)                       # take rite
    assert [c["next"] for c in e.choices()] == ["leviathan_verdict", "ending_chief"]
    e.choose(0)
    assert e.done and e.state.ending == "The Leviathan Within"


def test_without_rite_you_are_devoured():
    e = new()
    for i in (0, 0, 0, 1, 0):         # accept, trust Oren, flee, walk alone, reach out
        e.choose(i)
    assert e.state.ending == "Swallowed by the Salt"


def test_freeform_rule_and_rejection():
    e = new()
    assert e.freeform("I send a scout ahead") and e.state.flags["sent_scout"]
    assert e.state.beat == "arrival" and e.state.drift == 1
    assert e.freeform("sing a song to the moon") is False


def test_effect_validation():
    pack = load_pack("salt_exile")
    for bad in ({"teleport": 1}, {"kill": ["nobody"]}, {"stats": {"gold": 1}}, {"next": "nowhere"}):
        with pytest.raises(EffectError):
            validate(bad, pack)
    assert validate({"stats": {"trust_clans": 99}}, pack)["stats"]["trust_clans"] == 5


def test_llm_interpreter_output_is_validated():
    gen = lambda p: json.dumps({"kill": ["oren"], "message": "Oren collapses."})
    e = StoryEngine(load_pack("salt_exile"), interpreter=OllamaInterpreter("x", generate=gen))
    assert e.freeform("poison the physician") and e.state.alive["oren"] is False
    evil = lambda p: json.dumps({"kill": ["ghost"]})
    e2 = StoryEngine(load_pack("salt_exile"), interpreter=OllamaInterpreter("x", generate=evil))
    assert e2.freeform("do something") is False and e2.state.drift == 0


def test_narrator_falls_back_on_error():
    def boom(p):
        raise RuntimeError("no server")
    e = StoryEngine(load_pack("salt_exile"), narrator=OllamaNarrator("x", generate=boom))
    assert e.text().startswith("The Crown's seal")


def test_broken_pack_rejected():
    p = Pack(title="t", intro="", start="a", beats={"a": {"text": "x", "choices": [{"label": "l", "next": "zzz"}]}})
    with pytest.raises(PackError):
        p.validate()


def test_unreachable_beat_rejected():
    beats = {"a": {"text": "", "ending": "A"}, "orphan": {"text": "", "ending": "B"}}
    with pytest.raises(PackError, match="unreachable"):
        Pack(title="t", intro="", start="a", beats=beats).validate()


def test_global_freeform_target_counts_as_reachable():
    beats = {"a": {"text": "", "choices": [{"label": "x", "next": "b"}]}, "b": {"text": "", "ending": "B"},
             "secret": {"text": "", "ending": "S"}}
    Pack(title="t", intro="", start="a", beats=beats,
         freeform_rules=[{"keywords": ["x"], "next": "secret"}]).validate()


def test_freeform_ignored_after_ending():
    e = new()
    while not e.done:
        e.choose(0)
    assert e.freeform("pray") is False
