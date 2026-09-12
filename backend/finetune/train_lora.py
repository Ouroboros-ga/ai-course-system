#!/usr/bin/env python3
"""CS 学科垂类模型 LoRA 微调脚本（挑战杯 XH-202620）。

默认基座：星火 X2.5-4B（`XHToken/Spark-X2.5-4B`，Apache-2.0，4.11B dense，
混合注意力 3×sliding + 1×full，原生 1M 上下文，BF16 约 8GB）。
SFT 只用 2048/4096 截断即可，不需要开 1M。

云端单卡示例（AutoDL / 恒源云租 4090 24GB 或 5090 32GB，先经用户批准安装依赖）：

    pip install -r backend/finetune/requirements.txt   # transformers>=4.57.1（Spark2_5 架构必需）
    huggingface-cli download XHToken/Spark-X2.5-4B    # 或 export HF_ENDPOINT=https://hf-mirror.com
    python backend/finetune/train_lora.py --gpu-profile 4090
    python backend/finetune/train_lora.py --gpu-profile 5090

Qwen 等旧基座仍可用 --base-model 覆盖，--target-modules auto 会按架构自动选择；
显存不足时加 --use-4bit 走 QLoRA（需 bitsandbytes）。

诚实边界：本仓库当前**没有**可用的 GPU 训练环境，脚本在本环境不执行
（缺依赖时以退出码 2 fail-closed）；在云端单卡上按上述命令可真实完成训练
并保存 LoRA adapter。数据须先用 prepare_dataset.py v2 生成（2000+ 训练条目），
其中评测基准问答只进 eval 集，不进训练集（防对比污染）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_TRAINER_MISSING_HINT = (
    "缺少 GPU 训练依赖（torch/transformers/peft）。"
    "请先安装 backend/finetune/requirements.txt（需用户批准，"
    "星火 X2.5 架构要求 transformers>=4.57.1），"
    "或在无 GPU 环境改用星火 MaaS 微调 / 仅 RAG 增强。"
)

DEFAULT_BASE_MODEL = "XHToken/Spark-X2.5-4B"

# 星火 X2.5 注意力把 QKV 融合成一个 q_k_v_proj（见 modeling_spark.py），
# 另有 headwise 门控 g_proj；没有 q_proj/k_proj/v_proj/o_proj。
# 用错名字会导致 LoRA 零匹配（可训练参数≈0），故单独列出。
SPARK_TARGET_MODULES = (
    "q_k_v_proj", "g_proj", "out_proj", "gate_proj", "up_proj", "down_proj",
)

# Qwen2.5 / LLaMA / Mistral 系常见线性投影层（旧基座回退）
QWEN_TARGET_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
)

# 云端单卡预设（单卡 LoRA，无需 DeepSpeed；有效 batch = batch × accum）
GPU_PROFILES = {
    # 4090 24GB：BF16 全量加载约 8GB 权重 + 激活；开梯度检查点稳过
    "4090": dict(batch_size=2, gradient_accumulation_steps=8,
                 max_length=2048, lora_r=16, lora_alpha=32, learning_rate=2e-4),
    # 5090 32GB：可上 r32 + 更大 batch；有效 batch 保持 16 对齐 4090
    "5090": dict(batch_size=4, gradient_accumulation_steps=4,
                 max_length=2048, lora_r=32, lora_alpha=64, learning_rate=1e-4),
}


def _resolve_target_modules(base_model: str, requested: str) -> list[str]:
    """--target-modules auto 时按架构选择；显式传值则直接使用。"""
    if requested != "auto":
        return [m.strip() for m in requested.split(",") if m.strip()]
    try:
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(base_model, trust_remote_code=True)
        model_type = getattr(cfg, "model_type", "") or ""
        if "spark" in model_type:
            return list(SPARK_TARGET_MODULES)
    except Exception:
        pass  # 取不到配置时按名字启发式回退
    if "spark" in base_model.lower() or "x2.5" in base_model.lower():
        return list(SPARK_TARGET_MODULES)
    return list(QWEN_TARGET_MODULES)


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
    parser = argparse.ArgumentParser(description="CS 学科垂类模型 LoRA 微调（默认星火 X2.5-4B）")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL,
                        help="HF 模型 id 或本地路径，默认 XHToken/Spark-X2.5-4B")
    parser.add_argument("--data-file", type=Path, default=Path("data/instruction_train.jsonl"))
    parser.add_argument("--eval-file", type=Path, default=None,
                        help="可选：instruction_eval.jsonl，用于训练中按 eval 做早停/对照")
    parser.add_argument("--output-dir", type=Path, default=Path("lora_output"))
    parser.add_argument("--gpu-profile", choices=["4090", "5090", "none"], default="4090",
                        help="云端单卡预设；none=全部用显式参数")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lora-r", type=int, default=None)
    parser.add_argument("--lora-alpha", type=int, default=None)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    # 以下参数默认 None：由 --gpu-profile 预设解析，显式传值优先（见下方合并逻辑）
    parser.add_argument("--learning-rate", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=None)
    parser.add_argument("--max-length", type=int, default=None)
    parser.add_argument("--target-modules", default="auto",
                        help="'auto'=按架构自动选择；或逗号分隔显式指定")
    parser.add_argument("--use-4bit", action="store_true",
                        help="QLoRA：4bit NF4 加载基座（显存不足时的降级方案，需 bitsandbytes）")
    parser.add_argument("--no-gradient-checkpointing", action="store_true",
                        help="关闭梯度检查点（默认开启，省显存）")
    parser.add_argument("--resume-from-checkpoint", type=str, default=None,
                        help="从 output-dir 下某 checkpoint-* 目录续训（断点续跑）")
    parser.add_argument("--save-steps", type=int, default=0,
                        help=">0 时按步保存 checkpoint(0 = 仅在每个 epoch 末保存)")
    parser.add_argument("--logging-steps", type=int, default=10,
                        help="每隔多少优化步打印一次 loss")
    parser.add_argument("--allow-cpu", action="store_true",
                        help="显式允许 CPU 训练（仅小基座可行，默认拒绝）")
    args = parser.parse_args()

    # 预设与显式参数合并：显式传值优先
    profile = GPU_PROFILES.get(args.gpu_profile, {}) if args.gpu_profile != "none" else {}
    lora_r = args.lora_r if args.lora_r is not None else profile.get("lora_r", 16)
    lora_alpha = args.lora_alpha if args.lora_alpha is not None else profile.get("lora_alpha", 32)
    learning_rate = args.learning_rate if args.learning_rate is not None else profile.get("learning_rate", 2e-4)
    batch_size = args.batch_size if args.batch_size is not None else profile.get("batch_size", 2)
    grad_accum = (args.gradient_accumulation_steps if args.gradient_accumulation_steps is not None
                  else profile.get("gradient_accumulation_steps", 8))
    max_length = args.max_length if args.max_length is not None else profile.get("max_length", 2048)
    target_modules = _resolve_target_modules(args.base_model, args.target_modules)

    if not args.data_file.exists():
        print(f"[ERROR] 数据集不存在: {args.data_file}（先运行 prepare_dataset.py）", file=sys.stderr)
        return 1

    try:
        import torch
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            Trainer,
            TrainingArguments,
        )
    except ImportError:
        print(f"[ERROR] {_TRAINER_MISSING_HINT}", file=sys.stderr)
        return 2

    if not torch.cuda.is_available() and not args.allow_cpu:
        print("[ERROR] 未检测到 CUDA。4B 基座的 LoRA 训练需云端单卡（4090 24GB / 5090 32GB）；"
              "如确要在 CPU 上试跑小基座，请加 --allow-cpu。", file=sys.stderr)
        return 3

    samples = _load_dataset(args.data_file)
    print(f"[INFO] 加载数据集 {len(samples)} 条；基座 {args.base_model}")
    print(f"[INFO] 预设 {args.gpu_profile}：batch={batch_size} accum={grad_accum} "
          f"有效batch={batch_size * grad_accum} max_len={max_length}")
    print(f"[INFO] LoRA r={lora_r} alpha={lora_alpha} dropout={args.lora_dropout} "
          f"epochs={args.epochs} lr={learning_rate} 4bit={args.use_4bit}")
    print(f"[INFO] target_modules={target_modules}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if args.use_4bit:
        if device == "cpu":
            print("[ERROR] --use-4bit 需要 CUDA（bitsandbytes 不支持 CPU 训练）。", file=sys.stderr)
            return 3
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.base_model, quantization_config=bnb_config,
            trust_remote_code=True,
        )
        model = prepare_model_for_kbit_training(model)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.base_model, torch_dtype=torch.bfloat16, trust_remote_code=True,
        ).to(device)

    if not args.no_gradient_checkpointing and device != "cpu":
        model.gradient_checkpointing_enable()
        model.config.use_cache = False
        print("[INFO] 梯度检查点已开启")

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    tokenized = _tokenize(samples, tokenizer, max_length)
    collator = _collate(tokenizer)

    eval_dataset = None
    if args.eval_file is not None and args.eval_file.exists():
        eval_samples = _load_dataset(args.eval_file)
        eval_dataset = _tokenize(eval_samples, tokenizer, max_length)
        print(f"[INFO] 评测集 {len(eval_dataset)} 条（训练中对照，不回流训练）")

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=args.logging_steps,
        save_strategy="steps" if args.save_steps > 0 else "epoch",
        save_steps=args.save_steps if args.save_steps > 0 else None,
        eval_strategy="epoch" if eval_dataset is not None else "no",
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        gradient_checkpointing=not args.no_gradient_checkpointing and device != "cpu",
        optim="adamw_torch",
        report_to=[],
        remove_unused_columns=False,
        seed=2026,
    )
    trainer = Trainer(model=model, args=training_args, train_dataset=tokenized,
                      eval_dataset=eval_dataset, data_collator=collator)
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)

    model.save_pretrained(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"[OK] LoRA adapter 已保存到 {args.output_dir}；评测方式见 README.md 第 4 步。")
    return 0


def _tokenize(samples: list[dict], tokenizer: Any, max_length: int) -> list[dict]:
    """多轮 SFT 掩蔽：对每条 assistant 回复计算 loss，user 段与 pad 掩为 -100。

    用 apply_chat_template 逐前缀求增量实现，与各基座的 chat_template 解耦
    （Qwen ChatML / Spark thinking 模板均可）。
    """
    features: list[dict] = []
    for sample in samples:
        messages = sample.get("messages") or []
        if len(messages) < 2:
            continue
        full_ids = tokenizer.apply_chat_template(messages, tokenize=True)
        labels: list[int] = [-100] * len(full_ids)
        # 对每条 assistant 消息：prefix=此前全部消息，增量部分即本轮回复
        for i, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                continue
            prefix_ids = tokenizer.apply_chat_template(
                messages[:i], tokenize=True, add_generation_prompt=True,
            )
            with_reply = tokenizer.apply_chat_template(messages[:i + 1], tokenize=True)
            start = min(len(prefix_ids), len(with_reply))
            start = min(start, len(full_ids))
            end = min(len(with_reply), len(full_ids))
            for j in range(start, end):
                labels[j] = full_ids[j]
        full_ids = full_ids[:max_length]
        labels = labels[:max_length]
        if not any(lab != -100 for lab in labels):
            continue
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
