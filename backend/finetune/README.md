# CS 学科垂类模型微调管线（backend/finetune/）

> 挑战杯 XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》——
> "模型微调（LoRA/SFT）"的**可复现管线交付**（2026-08-20，R2 骨架）。
>
> **诚实状态**：管线脚本与数据可运行/可复现；**当前环境无 GPU，训练未执行**。
> 如需"已微调模型"成果，请：(a) 提供 GPU 环境运行本管线，或 (b) 开通星火 MaaS
> 微调（提交 ServiceID），或 (c) 以"管线 + RAG 增强"口径申报并在方案中如实说明。

## 目录

| 文件 | 作用 | 可在本环境运行？ |
|---|---|---|
| `prepare_dataset.py` | 从知识库 + 评测基准生成 ChatML 指令集（纯标准库、确定性） | ✅ 是 |
| `eval_baseline.json` | CS 学科评测基准（6 用例，与典型问题测试案例集对齐） | ✅ 是（数据） |
| `evaluate.py` | 对 OpenAI 兼容端点批量评测并输出结果 JSON（对比基座 vs 微调后） | ✅ 是（需端点 Key，fail-closed） |
| `train_lora.py` | PEFT LoRA + HF Trainer 训练脚本 | ❌ 需 GPU + 独立依赖 |
| `requirements.txt` | GPU 训练依赖（**需用户批准后安装**） | ❌ 不装 |

## 使用流程

```bash
# 1) 生成指令数据集（本环境可跑）
python backend/finetune/prepare_dataset.py --output-dir backend/finetune/data

# 2) 评测基座模型（对比基线；需端点 Key，不写入任何文件）
python backend/finetune/evaluate.py \
  --base-url https://spark-api-open.xf-yun.com/v1 \
  --api-key $XFYUN_SPARK_API_KEY --model 4.0Ultra \
  --output backend/finetune/results_base.json

# 3) 微调（GPU 环境；先经用户批准安装 requirements.txt）
pip install -r backend/finetune/requirements.txt
python backend/finetune/train_lora.py \
  --base-model Qwen/Qwen2.5-7B-Instruct \
  --data-file backend/finetune/data/instruction_train.jsonl \
  --output-dir backend/finetune/lora_output

# 4) 评测微调后模型，与第 2 步结果对比（技术先进性证据）
python backend/finetune/evaluate.py \
  --base-url <本地 vLLM 端点> --api-key <local> --model <lora 合并模型> \
  --output backend/finetune/results_lora.json
```

## 评测规则（eval_baseline.json）

- `contains`：输出须包含全部 `markers`（自动判定）；
- `judge0_manual`：需 Judge0 沙箱执行验证（人工/服务端，不自动判定）。

## 数据来源与合规

- 指令数据由公开教材内容摘要（`knowledge_data/`）与自建标准答案构成，
  无真实学生/患者/案件等敏感数据；不涉及付费服务调用（评测调用需自有 Key，
  结果文件只记录输出与判定，不回传密钥）。
