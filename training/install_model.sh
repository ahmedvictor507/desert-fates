#!/usr/bin/env bash
# Install a trained GGUF into Ollama under a name the game can use.
#
#   bash training/install_model.sh ~/Downloads/dune-q8_0.gguf dune
#   python3 play_story.py --gui --pack dune --llm dune
#
# Copies the chat template and sampling settings from the base model (qwen3:1.7b), so the
# trained model is prompted exactly like the base one.
set -euo pipefail
GGUF="${1:?usage: install_model.sh <model.gguf> [name] [base-model]}"
NAME="${2:-dune}"
BASE="${3:-qwen3:1.7b}"
[ -f "$GGUF" ] || { echo "No such file: $GGUF"; exit 1; }
command -v ollama >/dev/null || { echo "Ollama is not installed: https://ollama.com/download"; exit 1; }
ollama show "$BASE" --modelfile >/dev/null 2>&1 || ollama pull "$BASE"

MF="$(mktemp)"
{
  echo "FROM $(readlink -f "$GGUF")"
  # TEMPLATE block and PARAMETER lines from the base model (skip its FROM and LICENSE)
  ollama show "$BASE" --modelfile | awk '
    /^TEMPLATE """/ {t=1}
    t {print; if (NR>1 && /"""$/ && !/^TEMPLATE """$/) t=0; next}
    /^PARAMETER / {print}'
} > "$MF"
ollama create "$NAME" -f "$MF"
rm -f "$MF"
echo
echo "Installed as '$NAME'. Play with:  python3 play_story.py --gui --pack dune --llm $NAME"
