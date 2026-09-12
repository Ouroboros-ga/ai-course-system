# 数据集清单(统合版)——XH-202620 微调训练/评测集

> 生成:2026-09-09 · 本目录统合**已精调模型实际使用**的数据;权威源文件在 `backend/finetune/data/`,派生提交物在 `backend/finetune/export/`。

## 1. 权威数据集(已用于 Qwen2.5-7B LoRA 训练)

| 文件 | 条数 | 大小 | SHA256 | 说明 |
|---|---|---|---|---|
| `sft_train_v2.2_messages.jsonl` | 2212 | 1.24 MB | `d3aa8bb48287679dadb82c10155f3fa9072cbb858a227b6f8c7c9ed3a2d2dacc` | 训练集(权威,2212 条 ChatML messages) |
| `sft_train_v2.2_alpaca.jsonl` | 2212 | 1.07 MB | `a6d139e0daadcc84bf273438704f294c6b1fb176e79f4473991785de3cdefe86` | 训练集派生(Alpaca instruction/output,2212 条) |
| `sft_eval_v2.2.jsonl` | 50 | 0.03 MB | `6c754f3b8bee6e6c1820b439cb67388d13b57a8e328747eb2694f832572f7d3d` | 评测集 50 条(含基准 10,防污染:不进训练) |
| `benchmark10_only.jsonl` | 10 | 0.00 MB | `c6f3009d0952cb5cb1768b2f508a6fe9773e8089c7df94132ab1641660420a17` | 基准 10 问独立留档(防污染审计) |

**同源核对**:`sft_train_v2.2_messages.jsonl` 与 MaaS 提交物 `backend/finetune/export/spark_train_messages.jsonl` SHA256 完全一致(同一份数据两种用途)。

## 2. 训练集画像

| 项 | 值 |
|---|---|
| 条数 | 2212 |
| 消息数 | 4728(其中多轮 101 条) |
| 内容字符总量 | 587,119 |
| 单条内容上限 | 793 字符(≤1024 token,不触发截断) |
| 语言分布 | 中文为主 1343 条,英文 869 条(语料问答随源语言) |
| 格式 | ChatML `messages`(user/assistant,支持多轮);派生 Alpaca `instruction/output` |

## 3. 任务构成(13 类,详见 `backend/finetune/data/DATACARD.md`)

| 分组 | 条数 | 内容 |
|---|---|---|
| A 人工核校任务(T1–T12) | 1113 | 知识点讲解 202 / 图谱关系 88 / 解题推演 118 / 代码三件套 30 / 多轮教学 101 / 误区澄清 18 / 带引用作答 202 / 判断题 101 / 术语对照 43 / 知识定位 101 / 出处溯源 101 / 课件问答 8 |
| B 学科语料接地问答(T13) | 1099 | 教材 OSTEP 全量 + 中英维基 CS + RFC 选样 → LLM 生成 2434 对 → 三重过滤保留 45% |

## 4. 使用与去向

| 模型/用途 | 数据集 | 备注 |
|---|---|---|
| Qwen2.5-7B-Instruct + LoRA(已交付,`model_files/`) | `sft_train_v2.2_messages.jsonl` | 3 epochs, train_loss 0.667–0.669 |
| 星火 MaaS ServiceID(待提交) | `sft_train_v2.2_messages.jsonl`(= `spark_train_messages.jsonl`) | 2212 条 ≥ 门槛 |
| Spark-X2.5-1.7B/4B LoRA(进行中,`spark_x25_pack/`) | `sft_train_v2.2_messages.jsonl` / 派生 `spark_x25_alpaca.jsonl` | LLaMA-Factory 或 PEFT 兜底 |
| 评测 | `sft_eval_v2.2.jsonl`(50)+ `benchmark10_only.jsonl`(10) | 基准 10 问只进评测 |

## 5. 合规与防污染

- 数据来源:公开教材内容摘要 / 自建标准答案 / 开源语料(CC BY-SA 等,逐条溯源见 `backend/finetune/data/corpus_qa_provenance.jsonl`);无真实学生或敏感数据。
- 防污染:评测基准 10 问仅存在于评测集,训练集不含(自动校验 0 泄漏)。
- 历史版本(`instruction_train.jsonl` 197 条 等)仅作追溯,不作为当前训练依据。

---

## 新数据集接入记录 `v3`(由 `backend/finetune/intake_dataset.py` 生成)

| 文件 | 条数 | 大小 | SHA256(前12) |
|---|---|---|---|
| `v3_train_messages.jsonl` | 3127 | 2.09 MB | `fbbdf9f6d34e` |
| `v3_train_alpaca.jsonl` | 3127 | 1.94 MB | `1867caa3d7c2` |
| `v3_eval.jsonl` | 231 | 0.15 MB | `3d6b49f0ec29` |
| `sft_train_v2.2_messages.jsonl` | 2212 | 1.24 MB | `d3aa8bb48287` |
| `sft_train_v2.2_alpaca.jsonl` | 2212 | 1.07 MB | `a6d139e0daad` |
| `sft_eval_v2.2.jsonl` | 50 | 0.03 MB | `6c754f3b8bee` |
| `benchmark10_only.jsonl` | 10 | 0.00 MB | `c6f3009d0952` |

| 画像项 | 值 |
|---|---|
| 条数 | 3127 |
| 消息数 | 6948(多轮 296) |
| 内容字符 | 731,221 |
| 单条上限 | 708 字符 |
| 中文/英文起始 | 3113 / 14 |

防污染检查:基准 10 问 **0 命中**(通过)。
