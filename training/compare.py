"""Side by side: the base model vs the book-trained adapter on held-out game prompts (Colab GPU).

  python -m training.compare --adapter $DRIVE/lora-dune --data runs/books/holdout.jsonl --n 4
"""
import argparse
import json
import textwrap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--data", default="runs/books/holdout.jsonl")
    ap.add_argument("--n", type=int, default=4)
    a = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.float16, device_map="auto")
    model = PeftModel.from_pretrained(model, a.adapter)
    rows = [json.loads(line) for line in open(a.data)][:a.n]

    def gen(prompt):
        text = tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                       add_generation_prompt=True, enable_thinking=False)
        ids = tok(text, return_tensors="pt").to(model.device)
        out = model.generate(**ids, max_new_tokens=400, do_sample=True, temperature=0.7, top_p=0.9)
        return tok.decode(out[0, ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    for r in rows:
        prompt = r["messages"][0]["content"]
        with model.disable_adapter():
            base = gen(prompt)
        trained = gen(prompt)
        print("=" * 100, f"\nTASK: {r['task']}\n" + textwrap.shorten(prompt.split("SCENE NOTES:")[-1], 300))
        for label, text in (("BASE MODEL", base), ("TRAINED ON THE BOOKS", trained)):
            print(f"\n--- {label} ---\n{textwrap.fill(text, 100)}")


if __name__ == "__main__":
    main()
