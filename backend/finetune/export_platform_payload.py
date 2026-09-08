#!/usr/bin/env python3
"""比赛提交物转化：把 finetune 指令集转为"模型文件/ServiceID"两条交付路径所需格式。

挑战杯 XH-202620 要求提交 模型文件 或 模型 ServiceID。本脚本从
data/instruction_{train,eval}.jsonl 与 eval_baseline.json 一次性导出：

  export/spark_train_messages.jsonl      讯飞星辰 MaaS 对话微调训练集（messages 格式）
  export/spark_train_alpaca.jsonl        Alpaca(instruction/output) 格式（多平台通用）
  export/spark_inference_input_target.jsonl  星火推理集/评测集格式 {"input","target"}
  export/benchmark_only_input_target.jsonl   仅基准 10 问（单独可辨识，防污染审计用）
  export/manifest.json                   sha256 / 条数 / 约束校验结果

纯标准库、确定性输出。用法：
    python backend/finetune/export_platform_payload.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUT = BASE / "export"

TRAIN_LIMIT_NOTE = "spark lite 训练集>=100 条；spark pro>=1500 条"
INFERENCE_LIMIT = 4000  # 星火推理集单条 input+target 字符上限


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _to_alpaca(row: dict) -> dict:
    m = row["messages"]
    return {"instruction": m[0]["content"], "output": m[1]["content"]}


def _to_input_target(row: dict) -> dict:
    m = row["messages"]
    return {"input": m[0]["content"], "target": m[1]["content"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(name: str, rows: list[dict], *, min_n: int, max_n: int, length_check: bool) -> list[str]:
    issues = []
    if not (min_n <= len(rows) <= max_n):
        issues.append(f"{name}: 条数 {len(rows)} 超出 [{min_n}, {max_n}]")
    if length_check:
        for i, r in enumerate(rows):
            total = len(r.get("input", "")) + len(r.get("target", ""))
            if total > INFERENCE_LIMIT:
                issues.append(f"{name} 第{i + 1}条 input+target={total} 字符，超 {INFERENCE_LIMIT}")
    return issues


def main() -> int:
    OUT.mkdir(exist_ok=True)
    train = _load_jsonl(DATA / "instruction_train.jsonl")
    ev = _load_jsonl(DATA / "instruction_eval.jsonl")
    baseline = json.loads((BASE / "eval_baseline.json").read_text(encoding="utf-8"))["cases"]

    files: dict[str, list[str]] = {}

    # 1) 训练集两种格式
    train_messages = OUT / "spark_train_messages.jsonl"
    train_messages.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in train) + "\n", encoding="utf-8")
    train_alpaca = OUT / "spark_train_alpaca.jsonl"
    train_alpaca.write_text(
        "\n".join(json.dumps(_to_alpaca(r), ensure_ascii=False) for r in train) + "\n", encoding="utf-8")

    # 2) 评测/推理集（input+target）：eval 31 条 + 基准 10 问合并去重
    inf_rows = [_to_input_target(r) for r in ev]
    seen = {r["input"] for r in inf_rows}
    bench_rows = []
    for c in baseline:
        if c["question"] not in seen:
            inf_rows.append({"input": c["question"], "target": c["expected"]})
        bench_rows.append({"id": c["id"], "input": c["question"], "target": c["expected"]})

    inference = OUT / "spark_inference_input_target.jsonl"
    inference.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in inf_rows) + "\n", encoding="utf-8")
    benchmark = OUT / "benchmark_only_input_target.jsonl"
    benchmark.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in bench_rows) + "\n", encoding="utf-8")

    # 3) 校验 + manifest
    issues = []
    issues += _validate("spark_train_messages", train, min_n=100, max_n=100000, length_check=False)
    issues += _validate("spark_train_alpaca", train, min_n=100, max_n=100000, length_check=False)
    issues += _validate("spark_inference", inf_rows, min_n=10, max_n=200, length_check=True)

    manifest = {
        "schema_version": "xh202620-finetune-export/1.0",
        "source": {
            "train": "backend/finetune/data/instruction_train.jsonl (197 条)",
            "eval": "backend/finetune/data/instruction_eval.jsonl (31 条)",
            "baseline": "backend/finetune/eval_baseline.json (10 问，防污染：不进训练集)",
        },
        "files": {
            p.name: {"rows": n, "sha256": _sha256(p)}
            for p, n in [
                (train_messages, len(train)),
                (train_alpaca, len(train)),
                (inference, len(inf_rows)),
                (benchmark, len(bench_rows)),
            ]
        },
        "constraints": {
            "train_min_note": TRAIN_LIMIT_NOTE,
            "inference_char_limit": INFERENCE_LIMIT,
            "inference_range": "10-200 条",
        },
        "usage": {
            "service_id_path": [
                "1. 讯飞星辰 MaaS(training.xfyun.cn) 创建数据集，上传 spark_train_messages.jsonl",
                "2. 选择基座模型（spark lite 或开源 Qwen2.5），提交微调任务（约 10 分钟-数小时）",
                "3. 训练成功后『发布为服务』并绑定讯飞应用 → 得到 ServiceID（OpenAI 兼容）",
                "4. evaluate.py --base-url https://spark-api-open.xf-yun.com/v1 --model <ServiceID> 跑对比评测",
            ],
            "model_file_path": [
                "1. 云 GPU（如 AutoDL 4090/24G）上传 train_lora.py + data/instruction_train.jsonl",
                "2. 训练产出 lora_output/adapter_model.safetensors + adapter_config.json（即『模型文件』，几十 MB）",
                "3. 交付：adapter 文件 + 基座声明(Qwen2.5-7B-Instruct) + model card；可选上传 ModelScope 得模型仓 ID",
            ],
        },
        "issues": issues or "全部约束校验通过",
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] 训练集(messages) {len(train)} 条 -> {train_messages.name}")
    print(f"[OK] 训练集(alpaca)  {len(train)} 条 -> {train_alpaca.name}")
    print(f"[OK] 推理/评测集     {len(inf_rows)} 条 -> {inference.name}（含基准 {len(bench_rows)} 问）")
    for msg in issues:
        print(f"[WARN] {msg}")
    if not issues:
        print("[OK] 约束校验全部通过（训练>=100 条；评测 10-200 条；单条<=4000 字符）")
    print(f"[OK] manifest -> {OUT / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
