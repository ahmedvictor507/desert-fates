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


def _sourced_pack(tmp_path, monkeypatch):
    from story import sources
    book = [{"index": 1, "part": "", "title": "Chapter 1", "epigraph": "A quote.\n\n—SOMEONE",
             "source": "SOMEONE", "scenes": [],
             "chunks": ["The old woman held the needle at the boy's neck and waited in the dark room.",
                        "Elsewhere a fat man turned a globe of the desert world with his ringed hand."]}]
    (tmp_path / "bk").mkdir()
    (tmp_path / "bk" / "chapters.json").write_text(json.dumps(book))
    monkeypatch.setattr(sources, "PACKS", tmp_path)
    sources.load_book.cache_clear()
    beats = {"a": {"text": "A needle at your neck; an old woman waits.", "source": {"book": "bk", "chapters": [1]},
                   "choices": [{"label": "x", "next": "end"}, {"label": "y", "next": "end"}]},
             "end": {"text": "Done.", "ending": "E"}}
    return Pack(title="t", intro="", start="a", beats=beats, characters={"leto": {"name": "Leto", "alive": False}})


def test_narrator_gets_matching_excerpt_and_epigraph(tmp_path, monkeypatch):
    from story import sources
    pack = _sourced_pack(tmp_path, monkeypatch)
    prompts = []
    nar = OllamaNarrator(generate=lambda p: prompts.append(p) or "You feel the needle. She waits.", excerpt_chars=2000)
    e = StoryEngine(pack, narrator=nar)
    assert e.text() == "You feel the needle. She waits."
    assert "needle at the boy's neck" in prompts[0] and "globe" not in prompts[0]   # best-overlap chunk
    assert "Dead (never show them acting" in prompts[0] and "Leto" in prompts[0]
    e.text()
    assert len(prompts) == 1                                                         # cached
    assert sources.epigraph(e.beat).startswith("A quote.")


def test_narrator_rejects_verbatim_copy(tmp_path, monkeypatch):
    pack = _sourced_pack(tmp_path, monkeypatch)
    copy = "The old woman held the needle at the boy's neck and waited in the dark room."
    e = StoryEngine(pack, narrator=OllamaNarrator(generate=lambda p: copy, excerpt_chars=2000))
    assert e.text() == pack.beats["a"]["text"]


def test_missing_book_is_harmless(tmp_path, monkeypatch):
    from story import sources
    pack = _sourced_pack(tmp_path, monkeypatch)
    monkeypatch.setattr(sources, "PACKS", tmp_path / "nowhere")
    sources.load_book.cache_clear()
    assert sources.epigraph(pack.beats["a"]) == "" and sources.style_excerpt(pack.beats["a"]) == ""


def test_check_ollama_reports_missing_server():
    from story.llm import check_ollama
    assert "not running" in check_ollama("x", host="http://127.0.0.1:9")


def test_excerpt_off_by_default(tmp_path, monkeypatch):
    pack = _sourced_pack(tmp_path, monkeypatch)
    prompts = []
    StoryEngine(pack, narrator=OllamaNarrator(generate=lambda p: prompts.append(p) or "ok")).text()
    assert "needle at the boy's neck" not in prompts[0]


def test_gpu_out_of_memory_falls_back_to_cpu(monkeypatch):
    import io
    import urllib.error
    from story import llm
    sent = []

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data)
        sent.append(body["options"].get("num_gpu"))
        if body["options"].get("num_gpu") != 0:
            raise urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b'{"error": "cudaMalloc failed: out of memory"}'))
        return io.BytesIO(b'{"response": "fine"}')
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    gen = llm.ollama_generate("m")
    assert gen("p") == "fine" and gen.notice and "CPU" in gen.notice
    assert gen("p") == "fine" and sent == [None, 0, 0]   # stays on CPU after the first failure


def test_interpreter_cleans_flag_names():
    from story.llm import clean_flags
    assert clean_flags({"throw Pillow": True, "new_snake_case_flag": True, "1bad": True}) == {"throw_pillow": True}


def test_pack_rules_take_priority_over_llm():
    from story.engine import ChainInterpreter, RuleInterpreter
    calls = []
    llm = OllamaInterpreter("x", generate=lambda p: calls.append(p) or '{"message": "llm"}')
    e = StoryEngine(load_pack("salt_exile"), interpreter=ChainInterpreter(RuleInterpreter(), llm))
    e.freeform("I pray")
    assert calls == [] and "readier" in e.messages[0]       # pack rule handled it
    e.freeform("I juggle three knives")
    assert calls and e.messages == ["llm"]                    # LLM handles the rest
