"""Split a LOCAL epub you own into chapters/scenes under packs/<name>/ (git-ignored).

  python ingest.py path/to/book.epub --name my_pack

Chapters come from the book's own table of contents (part, chapter label, epigraph via CSS
classes). Books without a usable TOC fall back to text heuristics.

Output stays in packs/ (git-ignored). Never commit or share it; if you train on it (training/colab_books.ipynb), keep it in your own private storage.
"""
import argparse
import json
from pathlib import Path

from story.clean import matter_reason, split_epigraph
from story.epub_reader import read_book, read_epub, split_scenes

ROOT = Path(__file__).resolve().parent


def _fallback(path, min_chars, keep_matter):
    data = []
    for c in read_epub(path, min_chars):
        why = None if keep_matter else matter_reason(c.title, c.text)
        if why:
            print("  dropped", why)
            continue
        epi, body = split_epigraph(c.text)
        source = next((l.lstrip("—").strip() for l in epi.splitlines() if l.startswith("—")), "")
        data.append({"index": len(data) + 1, "part": "", "title": c.title, "epigraph": epi,
                     "source": source, "scenes": [body], "chunks": split_scenes(body)})
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--name", required=True)
    ap.add_argument("--min-chars", type=int, default=600, help="fallback mode only")
    ap.add_argument("--keep-matter", action="store_true", help="fallback mode only: keep front/back matter")
    a = ap.parse_args()

    out = ROOT / "packs" / a.name
    gitignore = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    if "packs/" not in gitignore:
        raise SystemExit("Refusing to run: 'packs/' is not in .gitignore")
    out.mkdir(parents=True, exist_ok=True)

    chapters = read_book(a.epub)
    if chapters:
        # scenes = real scene breaks; chunks = ~3000-char pieces for small-model context windows
        data = [{"index": c.index, "part": c.part, "title": c.title, "epigraph": c.epigraph,
                 "source": c.source, "scenes": c.scenes,
                 "chunks": [ch for s in c.scenes for ch in split_scenes(s)]} for c in chapters]
    else:
        print("  no chapter entries in the TOC; using text heuristics")
        data = _fallback(a.epub, a.min_chars, a.keep_matter)

    (out / "chapters.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    n_int = sum(d["title"] == "Interlude" for d in data)
    print(f"{len(data) - n_int} chapters + {n_int} interludes, "
          f"{sum(len(d['scenes']) for d in data)} scenes, {sum(len(d['chunks']) for d in data)} chunks "
          f"-> {out / 'chapters.json'}")


if __name__ == "__main__":
    main()
