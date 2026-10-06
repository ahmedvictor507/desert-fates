"""Supervised fine-tuning on the books (Colab GPU). Two stages, one LoRA adapter.

  # stage A: read the books (continued pretraining on plain text)
  python -m training.sft_train domain --data runs/books/domain.jsonl --out $DRIVE/lora-books
  # stage B: learn the game's jobs (narrator + director prompts), continuing the same adapter
  python -m training.sft_train tasks --data runs/books/tasks.jsonl --init $DRIVE/lora-books \
      --out $DRIVE/lora-dune

Checkpoints go to --out and training resumes from the latest one if re-run after a disconnect.
Written against TRL's SFTTrainer (TRL >= 0.20); argument names drift between versions, so
check the first test run. The resulting adapter is trained on copyrighted books: keep it private.
"""
from __future__ import annotations

import argparse
import glob
import json
import os


def task_rows(path: str, tok) -> list[dict]:
    """Render chat examples exactly as the game sends them (thinking off), as prompt/completion
    text, so loss is taken only on the model's answer."""
    rows = []
    for line in open(path):
        ex = json.loads(line)
        user, answer = ex["messages"][0]["content"], ex["messages"][1]["content"]
        prompt = tok.apply_chat_template([{"role": "user", "content": user}], tokenize=False,
                                         add_generation_prompt=True, enable_thinking=False)
        rows.append({"prompt": prompt, "completion": answer + tok.eos_token})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["domain", "tasks"])
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--init", help="adapter to continue from (stage B continues stage A)")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=-1, help="cap steps for a quick test run")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--max-length", type=int, default=1024)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--save-steps", type=int, default=50)
    a = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float16, device_map="auto")
    model.config.use_cache = False
    peft_config = None
    if a.init:
        model = PeftModel.from_pretrained(model, a.init, is_trainable=True)
    else:
        peft_config = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, task_type="CAUSAL_LM",
                                 target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                                 "gate_proj", "up_proj", "down_proj"])

    if a.stage == "domain":
        ds = Dataset.from_list([json.loads(line) for line in open(a.data)])   # {"text": ...}
        extra = {"dataset_text_field": "text", "packing": True}
    else:
        ds = Dataset.from_list(task_rows(a.data, tok))                       # {"prompt", "completion"}
        extra = {"completion_only_loss": True}
    print(f"{a.stage}: {len(ds)} examples", flush=True)

    cfg = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs, max_steps=a.max_steps,
                    per_device_train_batch_size=a.batch, gradient_accumulation_steps=a.grad_accum,
                    learning_rate=a.lr, lr_scheduler_type="cosine", warmup_ratio=0.03,
                    logging_steps=10, save_steps=a.save_steps, save_total_limit=2,
                    fp16=True, gradient_checkpointing=True, max_length=a.max_length,
                    report_to="none", **extra)
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok,
                         peft_config=peft_config)
    resume = bool(glob.glob(os.path.join(a.out, "checkpoint-*")))
    trainer.train(resume_from_checkpoint=resume or None)
    trainer.save_model(a.out)
    tok.save_pretrained(a.out)
    print(f"saved adapter to {a.out}", flush=True)


if __name__ == "__main__":
    main()
