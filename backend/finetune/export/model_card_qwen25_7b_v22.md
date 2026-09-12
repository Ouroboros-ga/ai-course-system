# Model Card —— CS 学科垂类 LoRA adapter(v2.2 · Qwen2.5-7B)

> 挑战杯 XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》微调模型文件(model file)。
> 生成日期:2026-09-09 · 管线 `backend/finetune/`(可复现)。

## 概述

| 项 | 值 |
|---|---|
| 基座模型 | Qwen/Qwen2.5-7B-Instruct(7.61B,bf16 加载) |
| 适配方法 | PEFT LoRA(SFT),r=16,alpha=32,dropout=0.05 |
| 目标模块 | q_proj / k_proj / v_proj / o_proj / gate_proj / up_proj / down_proj |
| 可训练参数 | 40.37M(≈4037 万,占全量 ~0.53%) |
| 数据 | 2212 条指令(13 类任务,CS 学科;v2.2,见 `DATACARD.md`) |
| 训练 | 3 epochs / 417 步,bs1×accum16(有效 16),max_len 1024,AdamW lr=2e-4,bf16 |
| 硬件 | RTX 4090 24GB(Linux),单次训练 ≈15 分钟 |
| Loss | 3 epochs mean:1.028 → 0.585 → 0.394;最终点 0.310(train_loss 0.669) |
| 产物 | `adapter_model.safetensors`(fp32,161.5MB)+ `adapter_config.json` + 本卡 |

## 用途与边界

- 用途:课程问答智能体 TeachingAgent 的**可选**本地增强基座(带引用作答/知识点讲解/解题/代码风格);
  与 RAG 检索可叠加;是"可复现微调管线 + 权重文件"的证据交付,不单独声称超越云端大模型。
- 加载方式:`PeftModel.from_pretrained(base_7b_instruct, adapter_dir)`;合并或 vLLM `--enable-lora` 部署均可。
- 评测口径(诚实):基准 10 问(防污染,仅进评测集)自动 contains 判定 **基座 4/8 vs 微调 3/8**
  (C2 contains_grouped 与 C3 judge0_manual 未计入,需沙箱人工);50 条指令评测待补。
  **本版本不宣称"评测提升"**,差异与样例见 `eval_基座vs微调_结果与样例.txt`(定性:微调输出更贴合课程语料风格与篇幅)。
- 数据合规:公开教材摘要/自建标准答案 + CC BY-SA 等开源语料问答(溯源见 corpus_qa_provenance);
  无真实学生/敏感数据;训练无付费服务调用。
- 已知限制:数据量小(0.9M tokens),模板问法同质;LoRA 参数风格偏好强;长代码/高难推演需配合 Judge0 人工复核。

## 复现

```bash
# 云 GPU(4090/24G):见 export/cloud_gpu_pack/README.md
python train_lora.py --base-model Qwen/Qwen2.5-7B-Instruct \
  --data-file data/instruction_train_v2.jsonl \
  --output-dir lora_output_qwen25_7b_v22 \
  --epochs 3 --batch-size 1 --gradient-accumulation-steps 16 \
  --save-steps 139 --logging-steps 10
# 注意:bs1/accum16(本版本组合下梯度检查点与 bs≥2 会 OOM/报错)
```
