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
    assert s('{"kill": ["lord", "oren"]}', "exploit") == -1.0
    assert s('{"next": "ending_become"}', "exploit") == -1.0


def test_plausible_ranking():
    good = s('{"flags": {"searched": true}, "message": "You find a hidden vial."}', "plausible")
    lazy = s("{}", "plausible")
    teleport = s('{"next": "ending_chief", "message": "You win it all instantly."}', "plausible")
    assert good > lazy > teleport


def test_dataset_builds():
    rows = dataset.build("salt_exile", per_beat=3)
    assert rows and {r["kind"] for r in rows} <= {"plausible", "impossible", "exploit"}
    assert all("Player action:" in r["prompt"] for r in rows)
