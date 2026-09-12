#!/usr/bin/env python3
"""新训练集接入管线(入库 → 校验 → 归一 → 统合清单)。

用途:收到新训练集后一条命令完成格式校验、统计画像、防污染检查、生成两种训练格式
(ChatML messages / Alpaca),并更新提交包的统合数据集目录与 DATASET_MANIFEST.md。

用法:
  python backend/finetune/intake_dataset.py --input <new.jsonl> --tag v3 \
      [--eval <eval.jsonl>] [--no-submission]

输入格式(每条一行 JSON,二选一):
  A) {"messages": [{"role": "user", ...}, {"role": "assistant", ...}, ...]}
  B) {"instruction": "...", "input": "...", "output": "..."}

输出:
  backend/finetune/data/<tag>_train_messages.jsonl   规范化 ChatML(训练用)
  backend/finetune/data/<tag>_train_alpaca.jsonl      Alpaca(LLaMA-Factory/MaaS)
  backend/finetune/data/<tag>_eval.jsonl              (可选)评测集副本
  competition/05-作品代码/finetune_提交包/dataset/     统合目录(含 manifest 重生成)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend/finetune/data"
SUB = ROOT / "competition/05-作品代码/finetune_提交包/dataset"
CJK = re.compile(r"[\u4e00-\u9fff]")


def sha12(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"[ERROR] 第 {i} 行不是合法 JSON: {e}")
    if not rows:
        raise SystemExit("[ERROR] 数据集为空")
    return rows


def to_messages(row: dict) -> list[dict]:
    if "messages" in row and row["messages"]:
        out = []
        for m in row["messages"]:
            role, content = m.get("role"), m.get("content", "")
            if role not in ("user", "assistant", "system"):
                raise SystemExit(f"[ERROR] 未知 role: {role}")
            out.append({"role": role, "content": content})
        return out
    q = row.get("instruction") or row.get("prompt")
    a = row.get("output") or row.get("response")
    if not q or not a:
        raise SystemExit("[ERROR] 每条需含 messages 或 instruction/output")
    extra = row.get("input") or row.get("query") or ""
    prompt = f"{q}\n\n{extra}".strip() if extra else q
    return [{"role": "user", "content": prompt}, {"role": "assistant", "content": a}]


def to_alpaca(msgs: list[dict]) -> dict:
    users = [m["content"] for m in msgs if m["role"] == "user"]
    assistants = [m["content"] for m in msgs if m["role"] == "assistant"]
    return {"instruction": users[0] if users else "",
            "input": "\n".join(users[1:]) if len(users) > 1 else "",
            "output": "\n".join(assistants)}


def stats(rows_msgs: list[list[dict]]) -> dict:
    n = len(rows_msgs)
    msgs = sum(len(m) for m in rows_msgs)
    chars = sum(len(x["content"]) for m in rows_msgs for x in m)
    maxc = max((sum(len(x["content"]) for x in m) for m in rows_msgs), default=0)
    multi = sum(1 for m in rows_msgs if sum(1 for x in m if x["role"] == "user") > 1)
    zh = sum(1 for m in rows_msgs if m and CJK.search(m[0]["content"]))
    return {"rows": n, "messages": msgs, "chars": chars, "max_content_chars": maxc,
            "multi_turn": multi, "zh_first": zh, "en_first": n - zh}


def contamination(rows_msgs: list[list[dict]], baseline: list[dict]) -> list[str]:
    train_q = {m[0]["content"].strip() for m in rows_msgs if m}
    hits = []
    for c in baseline:
        q = (c.get("question") or "").strip()
        if q and q in train_q:
            hits.append(c.get("id", "?"))
    return hits


def append_manifest(tag: str, st: dict, files: list[tuple[str, int]], extra_note: str) -> None:
    """在既有 DATASET_MANIFEST.md 末尾追加"新数据集接入记录",不覆盖既有 v2.2 内容。"""
    p = SUB / "DATASET_MANIFEST.md"
    lines = [
        "",
        f"---",
        "",
        f"## 新数据集接入记录 `{tag}`(由 `backend/finetune/intake_dataset.py` 生成)\n",
        "| 文件 | 条数 | 大小 | SHA256(前12) |",
        "|---|---|---|---|",
    ]
    for name, _ in files:
        f = SUB / name
        if not f.exists():
            continue
        rows = sum(1 for _ in f.open(encoding="utf-8"))
        lines.append(f"| `{name}` | {rows} | {f.stat().st_size/1e6:.2f} MB | `{sha12(f)}` |")
    lines += [
        "",
        "| 画像项 | 值 |",
        "|---|---|",
        f"| 条数 | {st['rows']} |",
        f"| 消息数 | {st['messages']}(多轮 {st['multi_turn']}) |",
        f"| 内容字符 | {st['chars']:,} |",
        f"| 单条上限 | {st['max_content_chars']} 字符 |",
        f"| 中文/英文起始 | {st['zh_first']} / {st['en_first']} |",
        "",
        extra_note,
        "",
    ]
    if not p.exists():
        p.write_text("# 数据集清单(统合版)——XH-202620 微调训练/评测集\n", encoding="utf-8", newline="\n")
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--tag", required=True, help="新数据集标签,如 v3")
    ap.add_argument("--eval", default=None)
    ap.add_argument("--no-submission", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    rows = load_rows(src)
    rows_msgs = [to_messages(r) for r in rows]
    st = stats(rows_msgs)

    baseline = []
    bp = ROOT / "backend/finetune/eval_baseline.json"
    if bp.exists():
        baseline = json.load(bp.open(encoding="utf-8")).get("cases", [])
    hits = contamination(rows_msgs, baseline)

    DATA.mkdir(parents=True, exist_ok=True)
    msg_p = DATA / f"{args.tag}_train_messages.jsonl"
    alp_p = DATA / f"{args.tag}_train_alpaca.jsonl"
    with msg_p.open("w", encoding="utf-8", newline="\n") as f1, alp_p.open("w", encoding="utf-8", newline="\n") as f2:
        for msgs in rows_msgs:
            f1.write(json.dumps({"messages": msgs}, ensure_ascii=False) + "\n")
            f2.write(json.dumps(to_alpaca(msgs), ensure_ascii=False) + "\n")

    print(f"[OK] {args.tag}: {st['rows']} 条 → {msg_p.name} / {alp_p.name}")
    print(f"     消息 {st['messages']} | 字符 {st['chars']:,} | 多轮 {st['multi_turn']} | "
          f"中文/英文 {st['zh_first']}/{st['en_first']} | 单条上限 {st['max_content_chars']}")
    print(f"     防污染检查:基准 10 问命中 {len(hits)} 条 {hits if hits else '(通过)'}")

    files: list[tuple[str, int]] = []
    if not args.no_submission:
        SUB.mkdir(parents=True, exist_ok=True)
        shutil.copy2(msg_p, SUB / f"{args.tag}_train_messages.jsonl")
        shutil.copy2(alp_p, SUB / f"{args.tag}_train_alpaca.jsonl")
        files += [(f"{args.tag}_train_messages.jsonl", st["rows"]),
                  (f"{args.tag}_train_alpaca.jsonl", st["rows"])]
        if args.eval:
            ev = Path(args.eval)
            shutil.copy2(ev, SUB / f"{args.tag}_eval.jsonl")
            files.append((f"{args.tag}_eval.jsonl", 0))
        extra = (f"防污染检查:基准 10 问命中 **{len(hits)}** 条(应为 0;命中须剔除后重跑)。"
                 if hits else "防污染检查:基准 10 问 **0 命中**(通过)。")
        legacy = [f for f in ["sft_train_v2.2_messages.jsonl", "sft_train_v2.2_alpaca.jsonl",
                              "sft_eval_v2.2.jsonl", "benchmark10_only.jsonl"] if (SUB / f).exists()]
        append_manifest(args.tag, st, files + [(f, 0) for f in legacy], extra)
        print(f"[OK] 统合目录已更新: {SUB}")
        print("     下一步训练示例(PEFT 路径):")
        print(f"     python backend/finetune/train_lora.py --base-model <基座> "
              f"--data-file {msg_p} --output-dir lora_output_{args.tag} "
              f"--epochs 3 --batch-size 2 --gradient-accumulation-steps 8 "
              f"--target-modules q_k_v_proj,out_proj,gate_proj,up_proj,down_proj,g_proj  # 星火用")
    if hits:
        print("[WARN] 存在防污染命中,请剔除后重新接入再训练")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
