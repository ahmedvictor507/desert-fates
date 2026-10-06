"""Teacher pass (Colab GPU): a bigger model describes every book passage as the game would.

  python -m training.teacher --passages runs/books/passages.jsonl \
      --out /content/drive/MyDrive/desert-fates/teacher.jsonl --model Qwen/Qwen3-4B

Resumable: rows already in --out are skipped, so re-run after a Colab disconnect. Uses vLLM if
installed (much faster), otherwise batched transformers generation.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from training.book_data import parse_teacher, teacher_prompt


def pending(passages_path: str, out_path: str, limit: int | None = None) -> list[dict]:
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                done.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    rows = [json.loads(line) for line in open(passages_path)]
    if limit:
        rows = rows[:limit]
    return [r for r in rows if r["id"] not in done]


def _chat(tok, prompt):
    return tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                   add_generation_prompt=True, enable_thinking=False)


def run(a):
    todo = pending(a.passages, a.out, a.limit)
    print(f"{len(todo)} passages to describe", flush=True)
    if not todo:
        return
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    try:
        from vllm import LLM, SamplingParams
        llm = LLM(a.model, dtype="half", max_model_len=4096, gpu_memory_utilization=0.9)
        params = SamplingParams(temperature=0.7, top_p=0.9, max_tokens=a.max_new_tokens)

        def generate(prompts):
            return [o.outputs[0].text for o in llm.generate([_chat(tok, p) for p in prompts], params)]
        print("using vLLM", flush=True)
    except Exception as e:                       # vLLM missing or unsupported: plain transformers
        import torch
        from transformers import AutoModelForCausalLM
        print(f"vLLM unavailable ({type(e).__name__}); using transformers", flush=True)
        tok.padding_side = "left"
        model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float16, device_map="auto")

        def generate(prompts):
            enc = tok([_chat(tok, p) for p in prompts], return_tensors="pt", padding=True).to(model.device)
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=a.max_new_tokens, do_sample=True,
                                     temperature=0.7, top_p=0.9, pad_token_id=tok.pad_token_id)
            return tok.batch_decode(out[:, enc["input_ids"].shape[1]:], skip_special_tokens=True)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    t0, ok = time.time(), 0
    with open(a.out, "a") as f:
        for i in range(0, len(todo), a.batch):
            batch = todo[i:i + a.batch]
            for r, text in zip(batch, generate([teacher_prompt(r["text"]) for r in batch])):
                parsed = parse_teacher(text)
                ok += parsed is not None
                f.write(json.dumps({"id": r["id"], "book": r["book"], "chapter": r["chapter"],
                                    "teacher": parsed}, ensure_ascii=False) + "\n")
            f.flush()
            n = i + len(batch)
            rate = n / (time.time() - t0)
            print(f"{n}/{len(todo)} done, {ok} usable, ~{(len(todo) - n) / rate / 60:.0f} min left", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passages", default="runs/books/passages.jsonl")
    ap.add_argument("--out", default="runs/books/teacher.jsonl")
    ap.add_argument("--model", default="Qwen/Qwen3-4B")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--max-new-tokens", type=int, default=700)
    ap.add_argument("--limit", type=int, help="only the first N passages (for a test run)")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
