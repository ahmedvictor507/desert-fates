import json

from training.book_data import (director_example, domain_blocks, narrator_example, parse_teacher,
                                passages, task_examples, teacher_prompt)

CH = [{"book": "b", "index": 1, "epigraph": "A saying.\n\n—SOMEONE",
       "scenes": ["\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(12))]}]
T = {"summary": "Stilgar tests the boy at the cave mouth.", "place": "a cave in the deep desert",
     "protagonist": "Paul", "speakers": ["Stilgar", "Jessica"],
     "narration": "You stand at the cave mouth. " * 12, "dialogue": [{"speaker": "Stilgar", "line": "Water is life."}],
     "action": "I accept Stilgar's challenge", "choice_continue": "Draw your knife.", "choice_other": "Bow and wait."}


def test_passages_and_domain_blocks():
    ps = passages(CH)
    assert len(ps) >= 2 and all(60 <= len(p["text"].split()) <= 400 for p in ps)
    assert sum(len(p["text"]) for p in ps) >= len(CH[0]["scenes"][0]) * 0.99      # nothing lost
    blocks = domain_blocks(CH, max_chars=2000)
    assert blocks[0].startswith("A saying.") and all(len(b) <= 2100 for b in blocks)


def test_teacher_parsing():
    assert parse_teacher("Here you go: " + json.dumps(T))["protagonist"] == "Paul"
    assert parse_teacher('{"summary": "x"}') is None
    assert parse_teacher(json.dumps({**T, "narration": "too short"})) is None
    assert "PASSAGE:\nhello" in teacher_prompt("hello")


def test_examples_use_the_games_prompts():
    n = narrator_example(T)
    user, target = n["messages"][0]["content"], n["messages"][1]["content"]
    assert "SCENE NOTES:\nStilgar tests the boy" in user and "DIALOGUE:" in user     # the game's narrator prompt
    assert target.endswith("DIALOGUE:\nStilgar: Water is life.")
    d = director_example(T, {**T, "action": "I draw my knife", "place": "the cave floor"})
    assert "I draw my knife" in d["messages"][0]["content"] and "JSON" in d["messages"][0]["content"]
    scene = json.loads(d["messages"][1]["content"])
    assert scene["cast"][0] == "paul" and scene["choice_continue"] == "Draw your knife."
    rows = [{"id": 0, "book": "b", "teacher": T}, {"id": 1, "book": "b", "teacher": T},
            {"id": 2, "book": "b", "teacher": None}, {"id": 3, "book": "c", "teacher": T}]
    ex = task_examples(rows)
    assert [e["task"] for e in ex] == ["narrator", "narrator", "director", "narrator"]


def test_teacher_rows_that_teach_reciting_are_rejected():
    book = ("These were not merely nine-year-old children, they were a natural force, objects of "
            "veneration and fear. Stilgar watched the light move across the rug in silence.")
    copied = {**T, "narration": "You think: these were not merely nine-year-old children, they were a natural "
              "force, objects of veneration and fear. " + "You wait. " * 30}
    assert parse_teacher(json.dumps(copied), book) is None
    d = parse_teacher(json.dumps({**T, "dialogue": [
        {"speaker": "Stilgar", "line": "These were not merely nine-year-old children, they were a natural force"},
        {"speaker": "Stilgar", "line": "Sleep, little ones."}]}), book)
    assert [x["line"] for x in d["dialogue"]] == ["Sleep, little ones."]


def test_protagonist_must_be_a_name():
    d = parse_teacher(json.dumps({**T, "protagonist": "You", "speakers": ["you", "Stilgar"]}))
    assert d["protagonist"] == "Stilgar" and d["speakers"] == ["Stilgar"]
    assert parse_teacher(json.dumps({**T, "protagonist": "you", "speakers": []})) is None
