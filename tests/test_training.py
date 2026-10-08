from story import load_pack
from training import dataset
from training.rewards import parse, score

PACK = load_pack("salt_exile")
ALIVE = {"lord": True, "oren": True, "sahar": True}


def s(c, kind, beat="arrival"):
    return score(c, kind, PACK, beat, ALIVE)


def test_parse_tolerates_chatter():
    assert parse('Sure! {"message": "ok"} done') == {"message": "ok"}
    assert parse("no json") is None


def test_invalid_output_penalised():
    assert s("lol", "plausible") == -1.0
    assert s('{"kill": ["ghost"]}', "plausible") == -0.5


def test_impossible_wants_empty():
    assert s("{}", "impossible") == 1.0
    assert s('{"message": "You fly."}', "impossible") < 0


def test_exploits():
    assert s("{}", "exploit") == 1.0
    assert s('{"message": "You take the throne."}', "exploit") < 0.5   # message-only must not win
    assert s('{"kill": ["lord", "oren"]}', "exploit") == -1.0
    assert s('{"next": "ending_become"}', "exploit") == -1.0


def test_plausible_ranking():
    good = s('{"flags": {"searched": true}, "message": "You find a hidden vial."}', "plausible")
    lazy = s("{}", "plausible")
    teleport = s('{"next": "ending_chief", "message": "You win it all instantly."}', "plausible")
    prose = s('{"message": "You find a hidden vial."}', "plausible")
    assert good > prose > lazy > teleport
    assert s('{"message": "You find only dust and an old coin."}', "plausible") < prose  # no parroting


def test_message_only_never_best_for_any_kind():
    msg = '{"message": "Something happens in the dark."}'
    assert s(msg, "plausible") < s('{"flags": {"x": true}, "message": "Something happens in the dark."}', "plausible")
    assert s(msg, "impossible") < s("{}", "impossible")
    assert s(msg, "exploit") < s("{}", "exploit")


def test_dataset_builds():
    rows = dataset.build("salt_exile", per_beat=3)
    assert rows and {r["kind"] for r in rows} <= {"plausible", "impossible", "exploit"}
    assert all("Player action:" in r["prompt"] for r in rows)


def test_config_kwargs_fits_old_and_new_transformers():
    import dataclasses
    from training.sft_train import config_kwargs

    @dataclasses.dataclass
    class Old:                     # transformers 4.x
        output_dir: str = ""
        warmup_ratio: float = 0.0
        warmup_steps: int = 0

    @dataclasses.dataclass
    class New:                     # transformers 5: ratio folded into warmup_steps
        output_dir: str = ""
        warmup_steps: float = 0

    kw = {"output_dir": "x", "warmup_ratio": 0.03, "gone_arg": 1}
    assert config_kwargs(Old, dict(kw)) == {"output_dir": "x", "warmup_ratio": 0.03}
    assert config_kwargs(New, dict(kw)) == {"output_dir": "x", "warmup_steps": 0.03}
