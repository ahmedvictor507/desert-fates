"""Play a story in the terminal.

  python play_story.py                       # pick a story from a menu
  python play_story.py --pack salt_exile     # a pack from stories/ or packs/
  python play_story.py --llm qwen3:4b        # optional: a local Ollama model narrates + handles free text

At each decision type 1 or 2, or write anything else you want to try.
"""
import argparse
import sys
import textwrap

from story import StoryEngine, load_pack
from story.pack import list_packs
from story import sources

WIDTH = 88


def show(text, indent=""):
    for para in text.split("\n\n"):
        print(textwrap.fill(para, WIDTH, initial_indent=indent, subsequent_indent=indent))


def pick_pack() -> str:
    packs = list_packs()
    if len(packs) == 1:
        return packs[0][0]
    print("\nWhich story?")
    for i, (_, title) in enumerate(packs, 1):
        print(f"  [{i}] {title}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(packs):
            return packs[int(raw) - 1][0]
        if raw.lower() in {"q", "quit"}:
            sys.exit(0)


def check_setup(model: str) -> int:
    """Print a friendly setup report. Returns 0 if the basics work."""
    from story.llm import check_ollama
    ok = sys.version_info >= (3, 10)
    print(f"[{'ok' if ok else '!!'}] Python {sys.version.split()[0]}" + ("" if ok else " (need 3.10 or newer)"))
    packs = list_packs()
    print(f"[ok] {len(packs)} stories found: " + ", ".join(n for n, _ in packs))
    problem = check_ollama(model)
    if problem:
        print(f"[--] Optional AI narrator ({model}) not ready. {problem}")
    else:
        print(f"[ok] AI narrator ready: python play_story.py --llm {model}")
    books = sorted(p.parent.name for p in sources.PACKS.glob("*/chapters.json"))
    if books:
        print(f"[ok] Your own books imported (used for epigraphs and narrator style): {', '.join(books)}")
    else:
        print("[--] No books imported (optional). If you own an EPUB: python ingest.py book.epub --name <name>")
    import importlib.util
    if importlib.util.find_spec("pygame"):
        print("[ok] pygame installed (survival mini-game: python play.py)")
    else:
        print("[--] pygame not installed (only needed for the survival mini-game: pip install pygame)")
    print("\nYou can play now: python play_story.py" if ok else "")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Play a branching story.")
    ap.add_argument("--pack", help="story name (default: choose from a menu)")
    ap.add_argument("--llm", metavar="MODEL", help="Ollama model to narrate and interpret free text, e.g. qwen3:4b")
    ap.add_argument("--book-style", action="store_true",
                    help="show the AI a passage of your imported book to copy its voice (best with 8B+ models)")
    ap.add_argument("--gui", action="store_true", help="play in a window instead of the terminal")
    ap.add_argument("--list", action="store_true", help="list available stories and exit")
    ap.add_argument("--check", action="store_true", help="check your setup and say what to fix")
    a = ap.parse_args()

    if a.check:
        sys.exit(check_setup(a.llm or "qwen3:4b"))

    if a.list:
        for name, title in list_packs():
            print(f"{name:24} {title}")
        return

    if a.gui:
        try:
            from game.story_gui import main as gui_main
        except ImportError:
            sys.exit("The window version needs pygame: pip install pygame  (or play in the terminal without --gui)")
        return gui_main(a.pack, a.llm, a.book_style)

    pack = load_pack(a.pack or pick_pack())
    kwargs = {}
    if a.llm:
        from story.engine import ChainInterpreter, RuleInterpreter
        from story.llm import OllamaInterpreter, OllamaNarrator, check_ollama
        problem = check_ollama(a.llm)
        if problem:
            print(f"\n[!] Can't use the AI narrator: {problem}")
            print("[!] Playing without it (the story still works; you just get the plain text).\n")
        else:
            kwargs = {"interpreter": ChainInterpreter(RuleInterpreter(), OllamaInterpreter(a.llm)), "narrator": OllamaNarrator(a.llm, excerpt_chars=1200 if a.book_style else 0)}
            print(f"(AI narrator: {a.llm}. The first scene can take a while on small machines.)")
    eng = StoryEngine(pack, **kwargs)
    warned = set()

    def warn_once():
        """Tell the player (once per problem) when the AI had trouble, instead of failing silently."""
        for part in kwargs.values():
            notes = [getattr(getattr(part, "generate", None), "notice", None), getattr(part, "last_error", None)]
            for n in notes:
                if n and n not in warned:
                    warned.add(n)
                    print(f"\n[!] AI narrator: {n}")

    print(f"\n=== {pack.title} ===")
    show(pack.intro)
    shown_epigraph = None
    shown_scene = None   # (beat, history length) whose text is already on screen
    while True:
        for m in eng.messages:
            print()
            show(f"* {m}")
        epi = sources.epigraph(eng.beat)
        if epi and epi != shown_epigraph:
            print()
            show(epi, indent="    ")
            shown_epigraph = epi
        scene = (eng.state.beat, len([h for h in eng.state.history if not h[1].startswith("(you)")]))
        if scene != shown_scene or eng.done:
            text = eng.text()
            warn_once()
            print()
            show(text)
            shown_scene = scene
        if eng.done:
            print(f"\n--- THE END: {eng.state.ending} (choices away from the original story: {eng.state.drift}) ---")
            break
        opts = eng.choices()
        print()
        for i, c in enumerate(opts, 1):
            show(f"  [{i}] {c['label']}")
        print("  [or type anything else you want to try, 'q' to quit]")
        raw = input("> ").strip()
        if raw.lower() in {"q", "quit"}:
            break
        if raw.isdigit() and 1 <= int(raw) <= len(opts):
            eng.choose(int(raw) - 1)
        elif raw:
            eng.freeform(raw)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
