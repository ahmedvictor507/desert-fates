"""Turn imported books (packs/<book>/chapters.json, made by ingest.py) into training data.

Three outputs, all built from the player's own copies of the books:

  domain   plain text blocks for continued pretraining (stage A: the world, its people, the voice)
  teacher  prompts asking a bigger "teacher" model to describe each passage as the game would
           (summary, place, speakers, a second-person game-style version, two next choices)
  tasks    chat examples in the game's EXACT narrator and director prompt formats (stage B),
           built from the teacher's answers, so what is trained is what the game runs

No GPU or ML libraries needed here; training/teacher.py and training/sft_train.py do the
heavy parts on Colab. The data contains book text: keep it private (your Drive), never commit
or publish it, and never publish a model trained on it.

  python -m training.book_data passages --books packs --out runs/books
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from story.engine import StoryState
from story.improv import director_prompt
from story.llm import narrator_prompt
from story.pack import Pack

WORLD_INTRO = ("The desert planet Arrakis, sole source of the spice melange, in a far-future feudal "
               "interstellar empire of Great Houses, the Spacing Guild, the Bene Gesserit sisterhood, "
               "and the Fremen of the deep desert.")


# ------------------------------------------------------------------ passages
def load_chapters(books_dir: str | Path) -> list[dict]:
    """Every chapter of every imported book, in reading order, tagged with its book name."""
    out = []
    for f in sorted(Path(books_dir).glob("*/chapters.json")):
        for c in json.loads(f.read_text()):
            out.append({**c, "book": f.parent.name})
    return out


def passages(chapters: list[dict], target_words: int = 250, max_words: int = 400) -> list[dict]:
    """Split chapters into ~target_words passages on paragraph boundaries (never across chapters)."""
    out = []
    for c in chapters:
        paras = [p.strip() for s in c.get("scenes", []) for p in s.split("\n\n") if p.strip()]
        cur, n = [], 0
        for p in paras:
            w = len(p.split())
            if cur and n + w > max_words:
                out.append(_passage(c, cur, len(out)))
                cur, n = [], 0
            cur.append(p)
            n += w
            if n >= target_words:
                out.append(_passage(c, cur, len(out)))
                cur, n = [], 0
        if cur and (n >= 60 or not out or out[-1]["chapter"] != c["index"]):
            out.append(_passage(c, cur, len(out)))
        elif cur:
            out[-1]["text"] += "\n\n" + "\n\n".join(cur)
    return out


def _passage(c, paras, i):
    return {"id": i, "book": c["book"], "chapter": c["index"], "title": c.get("title", ""),
            "text": "\n\n".join(paras)}


def domain_blocks(chapters: list[dict], max_chars: int = 4000) -> list[str]:
    """Plain book text in ~1k-token blocks for continued pretraining. Epigraphs are kept: they
    carry a lot of the books' voice."""
    blocks = []
    for c in chapters:
        text = "\n\n".join([c.get("epigraph", "")] + list(c.get("scenes", []))).strip()
        cur = ""
        for p in text.split("\n\n"):
            if cur and len(cur) + len(p) > max_chars:
                blocks.append(cur)
                cur = ""
            cur = f"{cur}\n\n{p}" if cur else p
        if cur:
            blocks.append(cur)
    return blocks


# ------------------------------------------------------------------- teacher
TEACHER_KEYS = ("summary", "place", "protagonist", "speakers", "narration", "dialogue", "action",
                "choice_continue", "choice_other")


def teacher_prompt(passage: str) -> str:
    return (
        "You are preparing training data for an interactive-fiction game set in the world of this novel.\n"
        "Read the passage, then reply with ONLY a JSON object with these keys:\n"
        '"summary": 2-3 plain sentences: what happens, who is there, what changes.\n'
        '"place": where it happens, a few words.\n'
        '"protagonist": the name of the point-of-view character.\n'
        '"speakers": names of everyone present who could speak.\n'
        '"narration": the passage rewritten as 100-150 words in SECOND person, present tense, addressed '
        'to the protagonist as "you". Keep the author\'s voice, imagery, vocabulary and inner thoughts, '
        "but do not copy whole sentences. Stop before the protagonist's next decision.\n"
        '"dialogue": 1-3 short spoken lines from the passage (paraphrased), as [{"speaker": name, "line": words}].\n'
        '"action": the most important thing the protagonist DOES in this passage, as a first-person '
        'command, e.g. "I refuse the Baron\'s offer".\n'
        '"choice_continue": one short sentence: a bold thing the protagonist could do next.\n'
        '"choice_other": one short sentence: a cautious alternative.\n\n'
        f"PASSAGE:\n{passage}\n"
    )


def parse_teacher(text: str) -> dict | None:
    """The teacher's JSON, checked enough to train on; None if unusable."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not all(k in d for k in ("summary", "narration", "protagonist")):
        return None
    nar = str(d["narration"]).strip()
    if not 40 <= len(nar.split()) <= 260:
        return None
    d["speakers"] = [str(s) for s in d.get("speakers", []) if isinstance(s, (str, int))][:8]
    d["dialogue"] = [x for x in d.get("dialogue", []) if isinstance(x, dict) and x.get("speaker") and x.get("line")][:3]
    for k in ("summary", "place", "protagonist", "action", "choice_continue", "choice_other"):
        d[k] = str(d.get(k, "")).strip()
    return d


# --------------------------------------------------------------- task examples
def _cid(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "someone"


def _world(d: dict, beat_text: str) -> tuple[Pack, StoryState]:
    """A one-scene pack + state whose characters are the people in this passage, so prompts look
    exactly like the game's (same builders), without needing the hand-written story pack."""
    names = [d["protagonist"]] + [s for s in d["speakers"] if s and s != d["protagonist"]]
    chars = {}
    for n in names:
        chars.setdefault(_cid(n), {"name": n})
    player = _cid(d["protagonist"])
    pack = Pack(title="Dune", intro=WORLD_INTRO, start="scene", player=player, characters=chars,
                beats={"scene": {"text": beat_text, "place": d.get("place", ""),
                                 "stage": {"cast": list(chars)},
                                 "choices": [{"label": d.get("choice_continue") or "Go on.", "next": "scene"},
                                             {"label": d.get("choice_other") or "Wait.", "next": "scene"}]}})
    state = StoryState(beat="scene", flags={}, stats={}, alive={c: True for c in chars})
    return pack, state


def narrator_example(d: dict) -> dict:
    """Input: the game's narrator prompt for these scene notes. Target: game-style prose + DIALOGUE."""
    pack, state = _world(d, d["summary"])
    prompt = narrator_prompt(d["summary"], state, pack, None, "", d.get("place", ""), list(pack.characters))
    lines = [f'{x["speaker"]}: {x["line"]}' for x in d["dialogue"] if x["speaker"] != d["protagonist"]]
    lines += [f'{x["speaker"]}: {x["line"]}' for x in d["dialogue"] if x["speaker"] == d["protagonist"]]
    target = d["narration"] + ("\n\nDIALOGUE:\n" + "\n".join(lines) if lines else "")
    return {"messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": target}],
            "task": "narrator"}


def director_example(prev: dict, d: dict) -> dict | None:
    """Input: the game's ✦ director prompt (previous scene + the protagonist's action).
    Target: the next scene as the game's JSON."""
    if not d.get("action") or not d.get("choice_continue"):
        return None
    pack, state = _world(prev, prev["summary"])
    for n in [d["protagonist"]] + d["speakers"]:          # people of the next scene exist too
        pack.characters.setdefault(_cid(n), {"name": n})
        state.alive.setdefault(_cid(n), True)
    prompt = director_prompt(pack, state, "scene", d["action"])
    cast = list(dict.fromkeys(_cid(n) for n in [d["protagonist"]] + d["speakers"]))[:6]
    target = json.dumps({"place": d.get("place", ""), "text": d["narration"], "cast": cast,
                         "choice_continue": d["choice_continue"],
                         "choice_return": d.get("choice_other") or "Let events take their course."},
                        ensure_ascii=False)
    return {"messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": target}],
            "task": "director"}


def task_examples(teacher_rows: list[dict]) -> list[dict]:
    """teacher_rows: [{"id", "book", "chapter", "teacher": {...parsed...}}] in reading order."""
    out, prev = [], None
    for r in teacher_rows:
        d = r.get("teacher")
        if not d:
            prev = None
            continue
        out.append(narrator_example(d))
        if prev and prev["book"] == r["book"]:
            ex = director_example(prev["teacher"], d)
            if ex:
                out.append(ex)
        prev = r
    return out


# ------------------------------------------------------------------------ cli
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["passages", "tasks"])
    ap.add_argument("--books", default="packs", help="folder containing <book>/chapters.json")
    ap.add_argument("--out", default="runs/books")
    ap.add_argument("--teacher", default="runs/books/teacher.jsonl", help="(tasks) teacher output")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.step == "passages":
        ch = load_chapters(a.books)
        ps = passages(ch)
        with open(out / "passages.jsonl", "w") as f:
            for p in ps:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        with open(out / "domain.jsonl", "w") as f:
            for b in domain_blocks(ch):
                f.write(json.dumps({"text": b}, ensure_ascii=False) + "\n")
        books = sorted({c["book"] for c in ch})
        print(f"{len(ch)} chapters from {books} -> {len(ps)} passages, domain blocks -> {out}")
    else:
        rows = [json.loads(line) for line in open(a.teacher)]
        rows.sort(key=lambda r: r["id"])
        ex = task_examples(rows)
        train, held = [e for i, e in enumerate(ex) if i % 50], [e for i, e in enumerate(ex) if not i % 50]
        for name, part in (("tasks.jsonl", train), ("holdout.jsonl", held)):   # holdout: never trained on
            with open(out / name, "w") as f:
                for e in part:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        n = {t: sum(e["task"] == t for e in train) for t in ("narrator", "director")}
        print(f"{len(rows)} teacher rows ({sum(bool(r.get('teacher')) for r in rows)} usable) -> train {n}, "
              f"holdout {len(held)} -> {out}")


if __name__ == "__main__":
    main()
