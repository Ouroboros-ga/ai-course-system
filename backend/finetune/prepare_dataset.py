#!/usr/bin/env python3
"""CS 学科垂类模型微调——指令数据集准备（挑战杯 XH-202620）。

从学科知识库（knowledge_data/）与评测基准（eval_baseline.json）生成
ChatML 格式指令数据集，用于 LoRA/SFT 微调：
- 知识节点讲解指令（含权威来源，训练模型养成"引用来源"习惯）
- 概念关系判断指令（对齐 education_graph 关系类型）
- 评测基准问答指令（标准答案）

纯标准库实现、确定性输出（固定随机种子），不安装任何 GPU 依赖：

    python backend/finetune/prepare_dataset.py --output-dir data
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge_data"
DEFAULT_BASELINE = Path(__file__).resolve().parent / "eval_baseline.json"
SEED = 2026
EVAL_SPLIT_RATIO = 0.1


def _chat(user: str, assistant: str) -> dict:
    return {
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


def _node_instruction(node: dict) -> str:
    source = node.get("source") or {}
    cite = "（来源：%s%s）" % (source.get("title", ""), ("，" + source["chapter"]) if source.get("chapter") else "")
    definition = node.get("definition", "")
    key_points = "\n".join("- " + kp for kp in node.get("key_points", []))
    answer = definition
    if key_points:
        answer += "\n要点：\n" + key_points
    if node.get("example"):
        answer += "\n示例：" + node["example"]
    answer += "\n" + cite
    instruction = f"请讲解计算机学科知识点「{node['name']}」：给出定义、关键要点与示例，并注明权威来源。"
    return _chat(instruction, answer)


def _relation_instruction(rel: dict, node_names: dict[str, str]) -> dict:
    frm = node_names.get(rel["from"], rel["from"])
    to = node_names.get(rel["to"], rel["to"])
    question = f"在计算机学科知识图谱中，「{frm}」与「{to}」之间是什么关系？请解释。"
    answer = f"「{frm}」与「{to}」的关系类型为 {rel['relation_type']}：{rel.get('note', '')}"
    return _chat(question, answer)


def _baseline_instruction(case: dict) -> dict:
    return _chat(
        case["question"],
        "标准答案：" + case["expected"] + "（来源：" + case["source"]["title"] + "）",
    )


def build_dataset(knowledge_dir: Path, baseline: Path) -> tuple[list[dict], list[dict]]:
    samples: list[dict] = []
    node_names: dict[str, str] = {}

    for filename in ("data_structures.json", "algorithms.json", "os.json", "net.json", "db.json", "se.json", "ml.json", "compiler.json", "arch.json"):
        path = knowledge_dir / filename
        if not path.exists():
            print(f"[warn] 跳过缺失文件: {path}", file=sys.stderr)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            if node.get("id"):
                node_names[node["id"]] = node.get("name", node["id"])
            samples.append(_node_instruction(node))

    rel_path = knowledge_dir / "relations.json"
    if rel_path.exists():
        rel_data = json.loads(rel_path.read_text(encoding="utf-8"))
        for rel in rel_data.get("relations", []):
            samples.append(_relation_instruction(rel, node_names))

    if baseline.exists():
        base_data = json.loads(baseline.read_text(encoding="utf-8"))
        for case in base_data.get("cases", []):
            samples.append(_baseline_instruction(case))

    rng = random.Random(SEED)
    rng.shuffle(samples)
    split = max(1, int(len(samples) * EVAL_SPLIT_RATIO))
    eval_samples = samples[:split]
    train_samples = samples[split:]
    return train_samples, eval_samples


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 CS 学科微调指令数据集")
    parser.add_argument("--knowledge-dir", type=Path, default=DEFAULT_KNOWLEDGE_DIR)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    train_samples, eval_samples = build_dataset(args.knowledge_dir, args.baseline)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    train_path = args.output_dir / "instruction_train.jsonl"
    eval_path = args.output_dir / "instruction_eval.jsonl"

    for path, samples in ((train_path, train_samples), (eval_path, eval_samples)):
        with path.open("w", encoding="utf-8") as fh:
            for sample in samples:
                fh.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"[OK] 训练集 {len(train_samples)} 条 → {train_path}")
    print(f"[OK] 评测集 {len(eval_samples)} 条 → {eval_path}")
    print("说明：数据集已生成；LoRA 训练需 GPU（见 README.md），不在此环境执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
