# Model Card —— Spark-X2.5-4B 学科垂类 LoRA(数据 v3)

> 挑战杯 XH-202620 · 生成日期 2026-09-10 · 管线 `backend/finetune/`(dev-liu 数据集 v3 与训练脚本)。
> 本次交付:**基座换成发榜单位科大讯飞的星火 X2.5-4B**,同一套 CS 学科指令集 LoRA SFT。

## 概述

| 项 | 值 |
|---|---|
| 基座 | `XHToken/Spark-X2.5-4B`(**Apache-2.0**,4.11B dense,36 层,混合注意力 3×SWA(512)+1×full,原生 1M 上下文,GQA 16Q/4KV,BF16 ≈8.2GB) |
| 适配方法 | PEFT LoRA(SFT),r=16 / alpha=32 / dropout=0.05 |
| LoRA 目标层 | `q_k_v_proj, g_proj, out_proj, gate_proj, up_proj, down_proj`(星火融合 QKV,**无** q/k/v/o_proj) |
| 可训练参数 | **32,449,536 / 4,144,528,896(0.78%)** |
| 数据 | v3:**3127 训练 / 231 评测**(ChatML,多轮掩蔽;来源 commit `d1c2be0`,评测基准 10 问零泄漏) |
| 训练 | 4090 24GB;bs2 × accum8(有效 16),cutoff 2048,lr 2e-4 cosine + 3% warmup,bf16,梯度检查点,seed 2026;**3 epochs = 588 步,26.0 分钟** |
| 训练损失 | train_loss **0.2032**;末步 loss 0.0014;训练中 eval_loss:epoch1 0.1053 / epoch2 **0.0987** / epoch3 0.1068(第 2 轮最优,第 3 轮轻微回升) |
| 产物 | `adapter_model.safetensors`(129.9MB,432 张量)+ adapter_config + tokenizer/chat_template |

## 用途与边界

- 用途:CS 学科 TeachingAgent 的**本地轻量基座**(4B 级、可单卡部署、原生 1M 上下文);与检索增强叠加;
  作为"可复现微调管线 + 权重文件"的证据交付,并体现**发榜单位模型生态**。
- 加载:`AutoModelForCausalLM.from_pretrained("XHToken/Spark-X2.5-4B", trust_remote_code=True)` +
  `PeftModel.from_pretrained(base, "adapter_spark_x25_4b")`;需 **transformers==4.57.6 系**(4.57.1+;5.16/5.17 实测不兼容)。
- 评测(诚实口径,全部真实执行):
  - **同分布 231 条 e_token 级对照:基座 eval_loss 2.39647(ppl 10.98)→ 微调 0.05497(ppl 1.057)**,拟合显著改善;但该集与训练集同源同风格,反映**领域拟合**而非开放域泛化。
  - **基准 10 问(防污染)自动 contains 8 题:基座 4/8 vs 微调 4/8**(C6 基座过/微调未过,C9 相反)——**不宣称提升**。
  - 逐条判定与 6 组样例:见 `evidence/spark_x25_4b_评测与曲线.md` 与 `evidence/eval_spark_x25_4b.txt`。
- 数据合规:公开教材摘要 + 自建标准答案 + 开源语料(逐条溯源见 provenance);无真实学生/敏感数据;基座 Apache-2.0 可商用。
- 已知限制:训练 loss 末段极低(0.0014)提示对小数据集拟合强;3 轮时 eval_loss 回升,必要时改用第 2 轮 checkpoint(checkpoint-392)。

## 复现

```bash
pip install -r backend/finetune/requirements.txt   # transformers>=4.57.1(torch>=2.3)
# 数据(dev-liu v3):3127 训练 / 231 评测
python backend/finetune/train_lora.py --gpu-profile 4090 \
  --data-file backend/finetune/data/instruction_train.jsonl \
  --eval-file backend/finetune/data/instruction_eval.jsonl \
  --output-dir backend/finetune/lora_output_spark_x25_4b
```
