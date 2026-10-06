# Training

The game uses one local model (via Ollama) for three jobs: **narrator** (scene notes → prose and
dialogue), **interpreter** (free text → a validated effect) and **director** (✦ new scenes). The
prompts for all three live in `story/llm.py` and `story/improv.py`, and every training script builds
its examples with those same functions, so what is trained is exactly what the game runs.

## Train on books you own: `colab_books.ipynb`

Open it in Google Colab (T4 GPU). It runs these steps, each resumable from your Google Drive:

| Step | Script | What it does |
|---|---|---|
| Passages | `book_data.py passages` | splits imported books (`packs/*/chapters.json`) into ~250-word passages, plus plain-text blocks |
| Teacher | `teacher.py` | Qwen3-4B describes each passage as the game needs it (summary, place, speakers, second-person version, choices) |
| Examples | `book_data.py tasks` | turns those into narrator and director examples in the game's prompt format; 2% held out |
| Stage A | `sft_train.py domain` | LoRA continued pretraining on the books: the world, the people, the voice |
| Stage B | `sft_train.py tasks` | the same adapter learns the game's jobs |
| Compare | `compare.py` | base model vs trained, side by side, on held-out scenes |
| Export | `export_model.py` + llama.cpp | merged model → `dune-q8_0.gguf` |

Then on your machine: `bash training/install_model.sh dune-q8_0.gguf dune` and play with `--llm dune`.

Book text and models trained on it are for your own use: keep them in your Drive, don't commit them,
don't publish the model.

## Reinforcement learning (next): `grpo_train.py`, `rewards.py`

GRPO with rewards from the game's own checks. Today it covers the interpreter
(`dataset.py` builds prompts from a story pack; `eval_interp.py` evaluates;
`colab_train.ipynb` runs it). The next step is director and narrator rewards (valid scene, living
cast only, follows the player's action, no copying from the books) applied on top of the
book-trained adapter.

The scripts that need a GPU were written against TRL/PEFT/transformers APIs but are checked here
only for syntax and data logic (`tests/test_book_data.py`); run each notebook step's short test first.
