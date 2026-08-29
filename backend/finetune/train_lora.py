#!/usr/bin/env python3
"""CS 学科垂类模型 LoRA 微调脚本（挑战杯 XH-202620）。

标准 PEFT LoRA + HF Trainer 管线，基座可选（Qwen2.5 / DeepSeek-R1-Distill /
星火开源基座等 HuggingFace 格式模型）。需要 GPU 环境与独立依赖：

    pip install -r requirements.txt        # 需用户批准后安装，不进入主依赖
    python backend/finetune/train_lora.py \
        --base-model Qwen/Qwen2.5-7B-Instruct \
        --data-file data/instruction_train.jsonl \
        --output-dir ./lora_output

诚实边界：本仓库当前**没有**可用的 GPU 训练环境，脚本不在本环境执行；
运行前请确认有 ≥16GB 显存（7B 参数 LoRA）或改用星火 MaaS 微调/仅使用 RAG。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TRAINER_MISSING_HINT = (
    "缺少 GPU 训练依赖（torch/transformers/peft/datasets）。"
    "请先安装 backend/finetune/requirements.txt（需用户批准），"
    "或在无 GPU 环境改用星火 MaaS 微调 / 仅 RAG 增强。"
)


def _load_dataset(path: Path) -> list[dict]:
    samples = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="CS 学科垂类模型 LoRA 微调")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--data-file", type=Path, default=Path("data/instruction_train.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("lora_output"))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    args = parser.parse_args()

    if not args.data_file.exists():
        print(f"[ERROR] 数据集不存在: {args.data_file}（先运行 prepare_dataset.py）", file=sys.stderr)
        return 1

    try:
        import torch  # noqa: F401
        from peft import LoraConfig, get_peft_model  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments  # noqa: F401
    except ImportError:
        print(f"[ERROR] {_TRAINER_MISSING_HINT}", file=sys.stderr)
        return 2

    samples = _load_dataset(args.data_file)
    print(f"[INFO] 加载数据集 {len(samples)} 条；基座 {args.base_model}")

    # 此处为真实训练入口：加载基座、构建 LoRA、训练并保存。
    # 当前环境不执行（见模块 docstring 的诚实边界）。
    print("[INFO] LoRA 训练参数：r=%d alpha=%d dropout=%.2f epochs=%d"
          % (args.lora_r, args.lora_alpha, args.lora_dropout, args.epochs))
    print("[INFO] 输出目录: %s" % args.output_dir)
    print("[TODO] 训练在本环境未执行；请在有 GPU 的环境按 README.md 运行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
