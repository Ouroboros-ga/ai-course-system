"""Spark-X2.5 基座 vs 微调 评测(基准 10 问 contains + 评测集样例)。

用法(在 pack 根目录):
  python scripts/eval_spark.py --model XHToken/Spark-X2.5-4B [--adapter saves/spark-x25-4b/lora/sft]
                               [--baseline ../../eval_baseline.json]
                               [--eval-jsonl ../../data/instruction_eval_v2.jsonl]
                               [--out eval_spark_out.txt] [--samples 6]
"""
import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def load_baseline(path):
    return json.load(open(path, encoding="utf-8"))["cases"]


def load_samples(path, n):
    out = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def check(case, ans):
    t = case["check"]["type"]
    if t == "contains":
        return all(m in ans for m in case["check"].get("markers", []))
    if t == "exact":
        return ans.strip() == case["check"].get("expected", "")
    return None  # judge0_manual / contains_grouped -> 人工


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="XHToken/Spark-X2.5-4B")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--baseline", default="../../eval_baseline.json")
    ap.add_argument("--eval-jsonl", default="../../data/instruction_eval_v2.jsonl")
    ap.add_argument("--out", default="eval_spark_out.txt")
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--max-new", type=int, default=384)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.model, trust_remote_code=True, torch_dtype=torch.bfloat16
    ).cuda()

    baseline = load_baseline(args.baseline)
    samples = load_samples(args.eval_jsonl, args.samples)
    prompts = [("B:" + c["id"], c["question"]) for c in baseline]
    prompts += [(f"S{i+1}", next(m["content"] for m in s["messages"] if m["role"] == "user"))
                for i, s in enumerate(samples)]

    def gen_all(m):
        res = {}
        m.eval()
        with torch.no_grad():
            for pid, q in prompts:
                text = tok.apply_chat_template([{"role": "user", "content": q}],
                                               tokenize=False, add_generation_prompt=True)
                ids = tok(text, return_tensors="pt").to("cuda")
                out = m.generate(**ids, max_new_tokens=args.max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
                res[pid] = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        return res

    base_ans = gen_all(model)
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter, torch_dtype=torch.bfloat16)
        lora_ans = gen_all(model)
    else:
        lora_ans = None

    lines, bp = [], {"n": 0, "base": 0, "lora": 0}
    for c in baseline:
        ba = base_ans.get("B:" + c["id"], "")
        la = (lora_ans or {}).get("B:" + c["id"], "")
        rb, rl = check(c, ba), (check(c, la) if lora_ans else None)
        lines.append(f"B:{c['id']} type={c['check']['type']} base_pass={rb} lora_pass={rl}")
        if rb is not None:
            bp["n"] += 1
            bp["base"] += 1 if rb else 0
            bp["lora"] += 1 if rl else 0
    lines.append(f"SUMMARY auto_count={bp['n']} base_pass={bp['base']}/{bp['n']} lora_pass={bp['lora']}/{bp['n']}")
    for i, s in enumerate(samples):
        q = next(m["content"] for m in s["messages"] if m["role"] == "user")
        gold = s["messages"][-1]["content"]
        lines += [f"Q{i+1}: {q[:120]}", f"  base: {base_ans[f'S{i+1}'][:300]}"]
        if lora_ans:
            lines.append(f"  lora: {lora_ans[f'S{i+1}'][:300]}")
        lines.append(f"  gold: {gold[:160]}")
    open(args.out, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(l for l in lines if l.startswith(("B:", "SUMMARY"))))
    print("WROTE", args.out)


if __name__ == "__main__":
    main()
