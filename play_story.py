"""Play a story pack in the terminal.

  python play_story.py                 # starter story
  python play_story.py --pack my_pack  # a pack from stories/ or packs/ (private, git-ignored)

At each decision type 1 or 2, or write anything else you want to try.
"""
import argparse
import textwrap

from story import StoryEngine, load_pack


def show(text):
    print(textwrap.fill(text, 88))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="salt_exile")
    ap.add_argument("--llm", help="Ollama model name to narrate/interpret (optional)")
    a = ap.parse_args()

    pack = load_pack(a.pack)
    kwargs = {}
    if a.llm:
        from story.llm import OllamaInterpreter, OllamaNarrator
        kwargs = {"interpreter": OllamaInterpreter(a.llm), "narrator": OllamaNarrator(a.llm)}
    eng = StoryEngine(pack, **kwargs)

    print(f"\n=== {pack.title} ===")
    show(pack.intro)
    while True:
        for m in eng.messages:
            print()
            show(f"* {m}")
        print()
        show(eng.text())
        if eng.done:
            print(f"\n--- THE END: {eng.state.ending} (drift from canon: {eng.state.drift}) ---")
            break
        opts = eng.choices()
        print()
        for i, c in enumerate(opts, 1):
            show(f"  [{i}] {c['label']}")
        print("  [or type anything else you want to try, 'q' to quit]")
        raw = input("> ").strip()
        if raw.lower() == "q":
            break
        if raw.isdigit() and 1 <= int(raw) <= len(opts):
            eng.choose(int(raw) - 1)
        elif raw:
            eng.freeform(raw)


if __name__ == "__main__":
    main()
