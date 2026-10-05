# Desert Fates

A choose-your-own-adventure engine where **every decision gives you two options, or you can type
anything you want to try**. The world keeps track of what happened (who's dead, who trusts you,
what you've done), so wild choices have real consequences instead of breaking the story.

It runs **entirely on your own computer**. No account, no internet, no GPU needed. An optional local
AI model can narrate the story in a richer voice and react to anything you type.

> A fan-made, unofficial engine for exploring "what if" branches of desert-planet epics such as
> *Dune*. Not affiliated with or endorsed by any rights holder. This repo ships only original
> content. See [Using your own books](#using-your-own-books).

## Play in 1 minute

You need **Python 3.10 or newer** ([download](https://www.python.org/downloads/)). Nothing else.

```bash
git clone <this repo's URL> desert-fates
cd desert-fates
python3 play_story.py
```

(On Windows, type `python` instead of `python3`.)

Pick a story, then at each decision type `1` or `2`, or type whatever you want to try, e.g.
*"spy on the physician"* or *"walk into the desert"*. Type `q` to quit.

**Prefer a window?** `pip install pygame`, then:

```bash
python3 play_story.py --gui
```

Characters appear in each scene and react to your choices (running off, stepping forward,
leaving together) before the story fades to the next scene. Click a choice (or press `1`/`2`),
or just start typing and press Enter. `Tab` shows who is alive and your standing; `Esc` goes
back to the story menu.

Not working? Run `python3 play_story.py --check`. It tells you what's missing and how to fix it.

## Add the AI narrator (optional)

With a local AI model, scenes are rewritten as proper prose that reacts to your choices, and much
more of what you type is understood.

1. Install [Ollama](https://ollama.com/download) (Linux: `curl -fsSL https://ollama.com/install.sh | sh`).
2. Download a model: `ollama pull qwen3:4b` (about 2.5 GB, one time).
3. Play with it: `python3 play_story.py --llm qwen3:4b` (add `--gui` for the window)

| Your computer | Suggested model | Notes |
|---|---|---|
| Small board / 8 GB RAM (e.g. Jetson Orin Nano) | `qwen3:1.7b` | Measured: 5–8 s per scene on the GPU, ~25 s if it falls back to CPU |
| 16 GB RAM or a modest GPU | `qwen3:4b` | Recommended default |
| Gaming GPU (8 GB+ VRAM) | `qwen3:8b` | Best prose; try `--book-style` |

Small models write decent atmosphere but sometimes get details wrong; larger models follow the
scene more closely. If your GPU runs out of memory the game switches to the CPU and tells you;
closing the web browser usually frees enough memory.

`--book-style` also shows the model a passage from a book you imported, to copy its voice. It
works poorly with small models (they retell the passage instead of the scene), so it's off by default.

Whatever the AI says is checked by the game's rules before it changes anything, so a confused model
can't break your save or bring dead characters back.

## Using your own books

If you own a book as an EPUB file, you can import it **locally** so stories based on it show the
book's chapter epigraphs and the narrator can match the author's voice:

```bash
python3 ingest.py "path/to/your book.epub" --name dune
```

This writes to `packs/`, a folder that is never uploaded or committed. Please keep it that way:
don't share imported text, or AI models trained on it.

## Write your own story

A story is one JSON file. Copy `stories/salt_exile.json` into `packs/` (private) or `stories/`
(to share), and edit it. Run `python3 play_story.py --list` to see it appear.

- **beats**: the scenes. Each has `text` and either two `choices`, an `auto` route, or an `ending`.
- **choices**: `label`, `next` (beat id), optional `effects` and `when` conditions. Mark the
  "what if" option with `"canon": false`; the game counts how far you drift from the original story.
- **effects**: set `flags`, change `stats`, `kill` or `revive` characters, show a `message`.
- **variants**: alternate text for a beat when conditions hold (e.g. a character is dead).
- **freeform_rules**: keywords that make typed actions work without an AI model.
- **source** (optional): `{"book": "dune", "chapters": [15]}` links a beat to an imported book.
- **place** (optional): where the scene happens, e.g. `"a stilltent in the deep desert, night"`.
  It picks the window's backdrop (sea world, desert, night, indoors…) and keeps the AI on setting.
- **stage** (optional): `{"cast": ["hero", "guard"], "props": ["worm", "ornithopter"]}`. Without
  it, the window finds characters named in the text. Props: box, seeker, globe, table,
  ornithopter, crawler, worm, tent, fire, shield.
- **player** (top level) is the character you play; characters can have a `short` name for tags
  and a `look` (`robe`, `trim`, `hair` colours; `hood`, `cape`, `float`, `hunch`; `build`,
  `height`; `weapon`).

The game checks your file when it loads: broken links, dead ends and unreachable scenes are reported
with the beat's name.

## Install as a command (optional)

```bash
pip install -e .        # from the cloned folder
desert-fates            # same as python3 play_story.py
```

## For developers

```bash
pip install -e ".[dev,game]"
python3 -m pytest
```

- `story/`: the story engine (pure logic), validated effects, local sources, LLM hooks.
- `engine/`, `env/`, `agents/`, `game/`, `play.py`: a 2D survival mini-game with a Gymnasium-style
  environment for training AI players with reinforcement learning.
- `training/`: fine-tuning and RL scripts. See [training/README.md](training/README.md).

License: MIT
