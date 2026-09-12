# CS 学科垂类模型微调管线（backend/finetune/）

> 挑战杯 XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》——
> "模型微调（LoRA/SFT）"的**可复现管线交付**（2026-08-20，R2 骨架；R14 完成真训练实现；
> 2026-09-10 数据集 v2 丰富化 + 默认基座切星火 X2.5-4B）。
>
> **诚实状态(2026-09-11 合并更新)**:数据准备与评测可在本环境复现;真实训练已在云 GPU 完成——
> **Qwen2.5-7B-Instruct LoRA 3 epochs**(2026-09-09,云 GPU RTX 4090,train_loss 0.667–0.669,
> 交付/评测记录见 `export/微调交付_模型与对照表.md` 与
> `docs/phase1/2026-09-09_XH202620微调交付记录.md`)与
> **星火 X2.5-4B LoRA**(数据 v3 3127 训练 / 231 评测,曲线与评测见
> `export/spark4b_loss_curve.csv`、`export/eval_spark_x25_4b.txt`、
> `export/model_card_spark_x25_4b.md`)。
> 本机 8GB(WDDM)仅适合冒烟/3B 调试(3B ~2s/样本),4B/7B 全量请用云 GPU;无 GPU 环境下
> `train_lora.py` 保持 fail-closed(缺依赖退出码 2,不假装训练成功)。
> 评测口径如实(基准 10 问基座 4/8 vs 微调 3/8,不宣称提升)。

## 目录

| 文件 | 作用 | 可在本环境运行？ |
|---|---|---|
| `prepare_dataset.py` | 从知识库 + 评测基准生成 ChatML 指令集 v2（纯标准库、确定性、自动发现知识库节点文件） | ✅ 是 |
| `eval_baseline.json` | CS 学科评测基准（10 用例，与典型问题测试案例集对齐） | ✅ 是（数据） |
| `evaluate.py` | 对 OpenAI 兼容端点批量评测并输出结果 JSON（对比基座 vs 微调后） | ✅ 是（需端点 Key，fail-closed） |
| `train_lora.py` | PEFT LoRA + HF Trainer 完整训练脚本（默认星火 X2.5-4B，多轮掩蔽、梯度检查点、4090/5090 预设） | ❌ 需 GPU + 独立依赖 |
| `requirements.txt` | GPU 训练依赖（**需用户批准后安装**，含 transformers>=4.57.1 与可选 bitsandbytes） | ❌ 不装 |

## 默认基座：星火 X2.5-4B

- HF：`XHToken/Spark-X2.5-4B`（Apache-2.0，可商用），4.11B dense，36 层，
  混合注意力（3×sliding window 512 + 1×full），GQA（16Q/4KV），原生 1M 上下文；
  BF16 权重约 8GB。SFT 截断 2048 足够，不开 1M。
- 架构定制：`Spark2_5ForCausalLM` 要求 `transformers>=4.57.1` + `trust_remote_code=True`
  （脚本已内置）；注意力把 QKV 融合成单个 `q_k_v_proj`，另有门控 `g_proj`——
  **没有 `q_proj/k_proj/v_proj/o_proj`，用错名字 LoRA 会零匹配**。
  `--target-modules auto`（默认）会按 `model_type` 自动选择：
  - spark 系：`q_k_v_proj,g_proj,out_proj,gate_proj,up_proj,down_proj`
  - 其他（Qwen/LLaMA/Mistral）：`q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`
- Qwen2.5-7B 等旧基座仍可用 `--base-model` + 自动回退覆盖。

## 云端单卡配置（4090 24GB / 5090 32GB）

| 预设 | batch | 累积 | 有效 batch | 截断 | LoRA | lr | 显存要点 |
|---|---|---|---|---|---|---|---|
| `--gpu-profile 4090` | 2 | 8 | 16 | 2048 | r16/α32 | 2e-4 | BF16 约 8GB 权重 + 激活，梯度检查点默认开，24GB 稳过 |
| `--gpu-profile 5090` | 4 | 4 | 16 | 2048 | r32/α64 | 1e-4 | 32GB 可用更大 rank，cosine + 3% warmup |

- 显式参数优先于预设；`--use-4bit` 走 QLoRA NF4 降级（需 bitsandbytes，4090/5090 跑 BF16 可不装）。
- HF 下载：`huggingface-cli download XHToken/Spark-X2.5-4B`，国内机 `export HF_ENDPOINT=https://hf-mirror.com`。
- 单卡 LoRA 无需 DeepSpeed；3 epoch 在 2000+ 条数据上约数十分钟到 2 小时（看卡与长度）。

## 数据集（v3，2026-09-10）

> **当前权威训练/评测数据为 v3 —— 3127 训练 + 231 评测**
> （`data/v3_train_messages.jsonl` / `data/v3_train_alpaca.jsonl` +
> `export/spark_x25_cloudrun/data/instruction_eval.jsonl`；清单见
> `backend/finetune/export/比赛提交包/dataset/DATASET_MANIFEST.md`）。
> 下方 v2.2 / v2 / R14 数字为历史口径，仅作追溯。

- **v2.2（历史）指令集 2212 训练 + 50 评测**：`data/instruction_train_v2.jsonl` /
  `instruction_eval_v2.jsonl`，生成器 `prepare_dataset_v2.py`，见 `data/DATACARD.md`。
- **v2（历史）指令集 3127 训练 + 231 评测**：自有 v2 生成 2222 条（112 节点 ×16 + 106 关系 ×4
  + 36 安全，去重 40 后 1991 训练 + 231 评测）+ 外部 `instruction_train_v2.jsonl`
  课程相关子集 1136 条（修复 5 处坏样本、去重 167 后并入）。**训练集远超 2000 条，
  满足讯飞专业精调的数据量建议**。
- 类型分布（自有部分）：`node_explain/explain 112`、`definition 112`、`keypoints 112`、
  `example 112`、`paraphrase 448`（4 问法/节点）、`compare 112`、`clarify 112`、
  `kp_qa 224`、`multiturn 224`（两轮）、`teach 112`、`quiz 112`、
  `rel_forward/reverse/judge_true/judge_false` 各 106、`safety 36`
  （24 超纲拒答 + 12 防编造）；外部并入：课程讲解/关系/代码/学习路径类约 1100 条
  + 别名/辨析/多轮追问等。
- 外部集过滤政策（`C:\Users\LIU\AppData\Local\Temp\opencode\merge_v2.py` 可复现）：
  剔除英文 trivia（581）、"According to the fragment" 类（199，无原文、与拒答训练冲突）、
  RFC 编号 trivia（71+10）、非课程轶事（48，如 Shazam/中本聪/游戏史）共约 900 条；
  修复「?」占位符 4 处（线程/TCP/IP 协议栈/机器学习基本概念/图论基础，答案注记反查
  relations.json）、补全截断问句 1 处；评测基准 10 问零泄漏（合并前后均校验）。
- v1 短板补齐：单模板→4 复述 + 定义/要点/示例三切面；关系单句→4 视角（含干扰项辨析）；
  新增同课程对比、易混澄清、两轮追问、讲法指导、出题、安全守界。
- **R14（历史）指令集 197 训练 + 31 评测**（知识库 112 节点 + 106 关系 + 基准 10 问 = 228 条，
  90% / 10% 划分后评测集并入基准 10 问）。
- **防污染设计**：评测基准 10 问**只进 eval 集不进训练集**——`evaluate.py` 用这
  10 问对比"基座 vs 微调后"，若标准答案进训练集，微调收益就是记忆而非泛化，
  对比证据失真（已验证训练集零泄漏）。
- 节点文件**自动发现**（`knowledge_data/*.json` 排除 `relations.json`，只收含 `nodes` 的文件）：
  知识库后续扩充新课程时无需改本脚本，重跑即可同步。

## 使用流程

```bash
# 1) 生成指令数据集（v2.2 生成器，本环境可跑，seed 固定可复现）
python backend/finetune/prepare_dataset_v2.py --output-dir backend/finetune/data

# 2) 评测基座模型（对比基线；需端点 Key，不写入任何文件）
python backend/finetune/evaluate.py \
  --base-url https://spark-api-open.xf-yun.com/v1 \
  --api-key $XFYUN_SPARK_API_KEY --model 4.0Ultra \
  --output backend/finetune/results_base.json

# 3) 微调（云端单卡；先经用户批准安装 requirements.txt）
#    默认基座 XHToken/Spark-X2.5-4B；一键包见 export/cloud_gpu_pack/ 与 export/spark_x25_cloudrun/
pip install -r backend/finetune/requirements.txt
huggingface-cli download XHToken/Spark-X2.5-4B  # 国内机先 export HF_ENDPOINT=https://hf-mirror.com
# 4090 24GB：
python backend/finetune/train_lora.py --gpu-profile 4090 \
  --data-file backend/finetune/data/v3_train_messages.jsonl \
  --eval-file backend/finetune/export/spark_x25_cloudrun/data/instruction_eval.jsonl \
  --output-dir backend/finetune/lora_output
# 5090 32GB：把 --gpu-profile 换成 5090 即可；显存不足时加 --use-4bit
# 旧 Qwen2.5-7B 口径：加 --base-model Qwen/Qwen2.5-7B-Instruct --data-file backend/finetune/data/instruction_train_v2.jsonl

# 4) 评测微调后模型，与第 2 步结果对比（技术先进性证据）
python backend/finetune/evaluate.py \
  --base-url <本地 vLLM 端点> --api-key <local> --model <lora 合并模型> \
  --output backend/finetune/results_lora.json
```

## 评测规则（eval_baseline.json）

- `contains`：输出须包含全部 `markers`（自动判定）；
- `judge0_manual`：需 Judge0 沙箱执行验证（人工/服务端，不自动判定）。

## 比赛提交物转化（模型文件 / ServiceID）

运行 `python backend/finetune/export_platform_payload.py` 一键导出 `export/`：

| 文件 | 格式 | 用途 |
|---|---|---|
| `spark_train_messages.jsonl` | messages 对话 | 星火 MaaS 训练集（197 条 ≥ lite 门槛 100） |
| `spark_train_alpaca.jsonl` | instruction/output | 多平台通用（Alpaca 兼容） |
| `spark_inference_input_target.jsonl` | input/target | 星火推理/评测集（31 条，10-200 达标，单条 ≤4000 字符） |
| `benchmark_only_input_target.jsonl` | input/target | 仅基准 10 问（防污染审计：证明不进训练集） |
| `manifest.json` | — | sha256 / 条数 / 约束校验 / 两路径操作步骤 |

**路径 B：星火 MaaS → ServiceID（推荐主路径，贴合发榜单位生态）**

1. 训练.xfyun.cn 创建数据集，上传 `spark_train_messages.jsonl`；
2. 选基座（spark lite / 开源 Qwen2.5），提交微调（约 10 分钟-数小时，平台有 Loss 曲线）；
3. 训练成功 →「发布为服务」绑定讯飞应用 → **得到 ServiceID**（OpenAI 兼容）→ 填材料 05；
4. `evaluate.py --model <ServiceID>` 跑基座 vs 微调对比。

注意：MaaS 托管不提供权重下载，"模型文件"由路径 A 补齐。

**路径 A：云 GPU → 模型文件（租 4090 约 1-2 元/小时）**

1. 一键包已就绪：`export/cloud_gpu_pack/`（含 `train_lora.py` + v2.2 数据 + 操作手册
   `export/cloud_gpu_pack/README.md`，SHA256 见包内 `SHA256SUMS.txt`）；
2. 产物 `adapter_model.safetensors + adapter_config.json` 即**可提交的模型文件**（几十 MB，
   附基座声明与 model card；不必提交 15GB 合并全量模型）；
3. 可选：上传 ModelScope 建仓得模型仓 ID，或 vLLM `--enable-lora` 部署为 OpenAI 端点（等效 ServiceID）。

**实测提示（2026-09-09，本机 RTX 5070 Laptop 8GB/WDDM）**：本地小 batch 训练吞吐仅 ~60–80 tok/s，
3B 3 epochs 实测需 6–9h 且逐步降频；**建议直接用路径 A 云 GPU 或路径 B MaaS**，本地仅作冒烟/调试。

**建议组合**：B 出 ServiceID + A 出 adapter 文件，同一份数据、同一个 `evaluate.py` 评测，
两条证据互相印证。

## 数据来源与合规

- 指令数据由公开教材内容摘要（`knowledge_data/`）与自建标准答案构成，
  无真实学生/患者/案件等敏感数据；不涉及付费服务调用（评测调用需自有 Key，
  结果文件只记录输出与判定，不回传密钥）。
