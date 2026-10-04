"""Split a LOCAL epub you own into chapters/scenes under packs/<name>/ (git-ignored).

  python ingest.py path/to/book.epub --name my_pack

Output stays on your machine. Never commit it or upload it to Colab/cloud services.
"""
import argparse
import json
from pathlib import Path

from story.epub_reader import read_epub, split_scenes

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--name", required=True)
    ap.add_argument("--min-chars", type=int, default=600)
    a = ap.parse_args()

    out = ROOT / "packs" / a.name
    gitignore = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    if "packs/" not in gitignore:
        raise SystemExit("Refusing to run: 'packs/' is not in .gitignore")
    out.mkdir(parents=True, exist_ok=True)
    chapters = read_epub(a.epub, a.min_chars)
    data = [{"index": c.index, "title": c.title, "scenes": split_scenes(c.text)} for c in chapters]
    (out / "chapters.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"{len(chapters)} chapters, {sum(len(c['scenes']) for c in data)} scenes -> {out/'chapters.json'}")


if __name__ == "__main__":
    main()
