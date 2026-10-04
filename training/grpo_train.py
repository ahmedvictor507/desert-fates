"""GRPO fine-tune of the free-text interpreter (LoRA). Run on a 24GB GPU, not the Jetson.

  pip install "trl>=0.14" peft transformers datasets accelerate
  python -m training.dataset --pack salt_exile
  python -m training.grpo_train --model Qwen/Qwen3-1.7B --data runs/interp.jsonl

NOTE: written against TRL's GRPOTrainer API but not yet run end to end; expect to
adjust argument names for your installed TRL version. Reward logic itself is tested
(tests/test_training.py).
"""
import argparse
import json
from functools import lru_cache

from story import load_pack
from training.rewards import score


@lru_cache(maxsize=None)
def _pack(name):
    return load_pack(name)


def reward_fn(prompts, completions, kind, pack, beat, alive, **_):
    """TRL passes extra dataset columns as keyword lists aligned with completions."""
    out = []
    for c, k, pk, b, al in zip(completions, kind, pack, beat, alive):
        text = c if isinstance(c, str) else c[0]["content"]
        out.append(score(text, k, _pack(pk), b, al))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--data", default="runs/interp.jsonl")
    ap.add_argument("--out", default="runs/interp-lora")
    ap.add_argument("--steps", type=int, default=300)
    a = ap.parse_args()

    from datasets import Dataset
    from peft import LoraConfig
    from trl import GRPOConfig, GRPOTrainer

    import torch
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()  # T4 has no bf16
    rows = [json.loads(l) for l in open(a.data)]
    ds = Dataset.from_list(rows)
    cfg = GRPOConfig(output_dir=a.out, max_steps=a.steps, num_generations=8,
                     per_device_train_batch_size=8, learning_rate=1e-5,
                     max_completion_length=160, logging_steps=5, bf16=bf16, fp16=not bf16)
    trainer = GRPOTrainer(model=a.model, reward_funcs=reward_fn, args=cfg, train_dataset=ds,
                          peft_config=LoraConfig(r=16, lora_alpha=32, target_modules="all-linear"))
    trainer.train()
    trainer.save_model(a.out)


if __name__ == "__main__":
    main()
