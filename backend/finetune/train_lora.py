#!/usr/bin/env python3
"""CS 学科垂类模型 LoRA 微调脚本（挑战杯 XH-202620）。

标准 PEFT LoRA + HF Trainer 管线，基座可选（Qwen2.5 / DeepSeek-R1-Distill /
星火开源基座等 HuggingFace 格式模型）。需要 GPU 环境与独立依赖：

    pip install -r requirements.txt        # 需用户批准后安装，不进入主依赖
    python train_lora.py \
        --base-model Qwen/Qwen2.5-7B-Instruct \
        --data-file data/instruction_train.jsonl \
        --output-dir ./lora_output

诚实边界：本仓库当前**没有**可用的 GPU 训练环境，脚本在本环境不执行
（缺依赖时以退出码 2 fail-closed）；在具备 ≥16GB 显存的机器上按上述命令
可真实完成训练并保存 LoRA adapter。数据须先用 prepare_dataset.py 生成，
其中评测基准 10 问只进 eval 集，不进训练集（防对比污染）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_TRAINER_MISSING_HINT = (
    "缺少 GPU 训练依赖（torch/transformers/peft）。"
    "请先安装 backend/finetune/requirements.txt（需用户批准），"
    "或在无 GPU 环境改用星火 MaaS 微调 / 仅 RAG 增强。"
)

# 适配 Qwen/LLaMA/Mistral 系常见线性投影层；其他基座可用 --target-modules 覆盖
DEFAULT_TARGET_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
)


def _load_dataset(path: Path) -> list[dict]:
    samples = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    if not samples:
        raise SystemExit(f"[ERROR] 数据集为空或不存在: {path}（先运行 prepare_dataset.py）")
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
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--target-modules", default=",".join(DEFAULT_TARGET_MODULES),
                        help="逗号分隔的 LoRA 目标模块名")
    parser.add_argument("--allow-cpu", action="store_true",
                        help="显式允许 CPU 训练（仅小基座可行，默认拒绝）")
    args = parser.parse_args()

    if not args.data_file.exists():
        print(f"[ERROR] 数据集不存在: {args.data_file}（先运行 prepare_dataset.py）", file=sys.stderr)
        return 1

    try:
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
    except ImportError:
        print(f"[ERROR] {_TRAINER_MISSING_HINT}", file=sys.stderr)
        return 2

    if not torch.cuda.is_available() and not args.allow_cpu:
        print("[ERROR] 未检测到 CUDA。7B 级基座的 LoRA 训练需 ≥16GB 显存；"
              "如确要在 CPU 上试跑小基座，请加 --allow-cpu。", file=sys.stderr)
        return 3

    samples = _load_dataset(args.data_file)
    print(f"[INFO] 加载数据集 {len(samples)} 条；基座 {args.base_model}")
    print(f"[INFO] LoRA 参数：r={args.lora_r} alpha={args.lora_alpha} dropout={args.lora_dropout} "
          f"epochs={args.epochs} lr={args.learning_rate}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=torch.bfloat16, trust_remote_code=True,
    ).to(device)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[m.strip() for m in args.target_modules.split(",") if m.strip()],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    tokenized = _tokenize(samples, tokenizer, args.max_length)
    collator = _collate(tokenizer)

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        logging_steps=10,
        save_strategy="epoch",
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        report_to=[],
        remove_unused_columns=False,
        seed=2026,
    )
    trainer = Trainer(model=model, args=training_args, train_dataset=tokenized, data_collator=collator)
    trainer.train()

    model.save_pretrained(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"[OK] LoRA adapter 已保存到 {args.output_dir}；评测方式见 README.md 第 4 步。")
    return 0


def _tokenize(samples: list[dict], tokenizer: Any, max_length: int) -> list[dict]:
    """ChatML 模板化；labels 只对 assistant 段计算损失（prompt 段掩为 -100）。"""
    features: list[dict] = []
    for sample in samples:
        messages = sample.get("messages") or []
        if len(messages) < 2:
            continue
        prompt_ids = tokenizer.apply_chat_template(
            messages[:-1], tokenize=True, add_generation_prompt=True,
        )
        full_ids = tokenizer.apply_chat_template(messages, tokenize=True)
        prompt_len = min(len(prompt_ids), len(full_ids))
        labels = [-100] * prompt_len + list(full_ids[prompt_len:])
        full_ids = full_ids[:max_length]
        labels = labels[:max_length]
        features.append({"input_ids": full_ids, "labels": labels})
    if not features:
        raise SystemExit("[ERROR] 无可训练样本：messages 需至少含 user/assistant 两条")
    return features


def _collate(tokenizer: Any) -> Any:
    from dataclasses import dataclass
    from typing import List

    import torch

    @dataclass
    class Collator:
        pad_token_id: int

        def __call__(self, batch: List[dict]) -> dict:
            max_len = max(len(item["input_ids"]) for item in batch)
            input_ids, labels, attention_mask = [], [], []
            for item in batch:
                ids, lab = item["input_ids"], item["labels"]
                pad = max_len - len(ids)
                input_ids.append(ids + [self.pad_token_id] * pad)
                labels.append(lab + [-100] * pad)
                attention_mask.append([1] * len(ids) + [0] * pad)
            return {
                "input_ids": torch.tensor(input_ids, dtype=torch.long),
                "labels": torch.tensor(labels, dtype=torch.long),
                "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            }

    return Collator(pad_token_id=tokenizer.pad_token_id)


if __name__ == "__main__":
    sys.exit(main())
