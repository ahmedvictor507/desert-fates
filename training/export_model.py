"""Merge a LoRA adapter into its base model and save a plain Hugging Face model folder,
ready for llama.cpp's convert_hf_to_gguf.py (see the Colab notebook), then Ollama.

  python -m training.export_model --adapter $DRIVE/lora-dune --out /content/dune-merged
  python -m training.export_model --adapter $DRIVE/lora-dune --out /content/dune-merged --tokenizer-only
"""
import argparse
import glob
import os
import shutil

TOKENIZER_FILES = ["tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"]


def copy_tokenizer(model: str, out: str):
    """Training never changes the tokenizer, so ship the base model's original files. Re-saving
    them with a newer transformers writes a format that the (older) transformers llama.cpp's
    converter installs cannot read."""
    if os.path.isdir(model):
        src = model
    else:
        from huggingface_hub import snapshot_download
        src = snapshot_download(model, allow_patterns=TOKENIZER_FILES)
    for f in glob.glob(os.path.join(out, "*token*")) + glob.glob(os.path.join(out, "chat_template*")):
        os.remove(f)                             # anything a newer transformers wrote
    for name in TOKENIZER_FILES:
        if os.path.exists(os.path.join(src, name)):
            shutil.copy(os.path.join(src, name), out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tokenizer-only", action="store_true",
                    help="only (re)place the tokenizer files in an already merged --out folder")
    a = ap.parse_args()
    if a.tokenizer_only:
        copy_tokenizer(a.model, a.out)
        print(f"tokenizer files copied to {a.out}")
        return

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    base = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float16)
    merged = PeftModel.from_pretrained(base, a.adapter).merge_and_unload()
    merged.save_pretrained(a.out, safe_serialization=True)
    copy_tokenizer(a.model, a.out)
    print(f"merged model saved to {a.out}")


if __name__ == "__main__":
    main()
