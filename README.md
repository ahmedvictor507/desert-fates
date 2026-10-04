# Desert Fates: a branching story engine (bring-your-own-universe)

An open-source, fully local interactive-fiction engine. Every decision offers **two options plus
free-text** ("do anything"), a validated effect system keeps the world consistent, and an optional
local LLM narrates and interprets your wild ideas. A second mode is an RL-trainable survival game.

A fan-made, unofficial engine for exploring "what if" branches of desert-planet epics such as *Dune*
(bring your own pack). Not affiliated with or endorsed by any rights holder.

The repo ships **only original content**. Stories are plain JSON "packs"; you can write your own
and keep them private in `packs/` (git-ignored).

## Play
```bash
pip install -r requirements.txt     # pygame only needed for the survival game
python play_story.py                          # starter story: Salt Exile
python play_story.py --pack my_pack           # any pack in stories/ or packs/
python play_story.py --llm qwen3:4b           # optional: local Ollama model narrates + interprets free text
python -m pytest
```

At each decision type `1`/`2`, or type anything else to try it. Non-canon choices increase *drift*.

## How it works
- **Story spine** (`story/`, packs in JSON): beats with choices, conditions (`when`), `on_enter`
  effects, `auto` re-routing (e.g. a dead character changes what happens next), endings.
- **Free text** -> interpreter proposes an effect -> `story/effects.py` validates it (known
  characters/stats/beats only, capped deltas) -> only then is state changed. The default interpreter
  is keyword rules in the pack; `--llm` swaps in a local model. Bad LLM output is rejected, never applied.
- **Narrator** optionally rewrites canon prose in a style; it falls back to the original text offline.

## Make a pack
Copy `stories/salt_exile.json`. Fields: `title`, `intro`, `start`, `characters`, `flags`, `stats`,
`freeform_rules`, `beats`. `Pack.validate()` catches dangling links and dead ends.

## Survival game / RL (WIP)
`engine/`, `env/`, `agents/`, `game/`, `play.py`, `evaluate.py`: a seeded 2D survival sandbox with a
Gymnasium-style env and baselines for training an LLM agent with RL. See `training/README.md`.

## Content policy
This repo contains no third-party copyrighted text, names, art or model weights trained on them.
Private packs live in `packs/` (git-ignored). Don't commit them.

License: MIT
