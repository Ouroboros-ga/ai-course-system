# CodeNexus《04—作品方案》PPT 脚本 · 技术细化与数据校核版

# 0. CS LoRA 微调交付实测（2026-09-09 交付包）

> **证据来源**：`finetune_提交包/`（提交清单 / 交付对照表 A–G / model card / loss CSV）。本机复核：loss CSV **418 行 = 1 表头 + 417 点**，与声明一致。

## A. 训练：真实执行，双轨交付

| 项 | 实测值 |
|---|---|
| **基座** | **`Qwen/Qwen2.5-7B-Instruct`**（7.61B，bf16） |
| 方法 | PEFT LoRA（SFT / ChatML / prompt 段 loss 掩蔽），**r=16 / alpha=32 / dropout=0.05** |
| 目标模块 | 7 类：`q/k/v/o/gate/up/down_proj` |
| 可训练参数 | **40.37M**（≈4037 万，占全量 **0.53%**） |
| 数据 | **2212 条**（13 类学科任务）；评测 50 条防污染 |
| 硬件 | 云 GPU **RTX 4090 24GB** |
| 轮次 / 步数 | 3 epochs / **417 优化步** |
| 优化 | AdamW lr=2e-4；bs=1 × accum 16（有效 16）；max_len 1024；bf16；**seed 2026** |
| **时长** | **≈15 分钟**（909s / 914s） |
| **Loss** | **train_loss 0.6675**（复跑 0.6690，两次一致）；epoch mean **1.028 → 0.585 → 0.394**；末点 **0.3102** |
| 产物 | `adapter_model.safetensors`（fp32，**161.5MB**，392 张量）；交付 zip 11 文件 **146.4MB** |

**双轨结构**（决定 PPT 怎么写"星火"）：

```text
轨 A · 开源权重轨：Qwen2.5-7B + LoRA r16 → adapter 权重（已完成，可下载可复现）
轨 B · 讯飞生态轨：2212 条学科指令 → 星火 MaaS 微调 → ServiceID（数据已备齐，待提交）
```

**星火 MaaS 侧现状**：`spark_train_messages.jsonl` **2212 条**，超 spark pro 门槛（1500 条）与 lite 门槛（100 条）；推理集 50 条（限制 10–200 ✅，单条 ≤4000 字符 ✅）；防污染基准 10 条独立文件；自检 `"全部约束校验通过"`；**ServiceID 待提交回填**（MaaS 不提供权重下载，权重由轨 A 补齐）。

## B. 评测：诚实且不理想 —— 最高表述红线

| 用例 | 判定 | 基座 | 微调 |
|---|---|---|---|
| C1/C4/C5/C6/C7/C8/C9/C10（8 题） | `contains` | **4/8** | **3/8** |
| C2 / C3 | `contains_grouped` / `judge0_manual` | 未计 | 未计 |
| 50 条指令评测集 | 全量 | 待测 | 待测 |

条件：同一 10 问、相同解码设置（`do_sample=False, max_new 384`）、云端 4090 实测。

🚨 **绝对不得写"微调提升了效果"**。严格 markers 口径下微调**未提升**（4/8 → 3/8，C4 由 True 变 False）。交付包 README 与交付记录均明确写"**不得宣称评测提升**"。

**允许的三种说法**（交付包给定口径）：

> ① **LoRA 训练收敛**（train_loss 0.67，417 步，两次独立运行一致）；
> ② **可复现**（云 GPU 15 分钟 / seed 2026 / 脚本与数据随包）；
> ③ **输出更贴合课程语料风格**（结构化要点 + 教材出处、篇幅收敛）——**定性观察，非通过率证据**。

## C. "星火 8B CS-LoRA"三要素逐个对齐

| 脚本写法 | 实况 | 结论 |
|---|---|---|
| 星火 | 微调基座是 **Qwen2.5-7B**；星火是 **MaaS 提交渠道**（ServiceID 待提交） | ⚠️ 不能写"星火基座"；**可写"星火 MaaS 微调"** |
| 8B | 实际 **7B** | ⚠️ 数字需改 |
| CS-LoRA | **真实**（r16 / 2212 条 / 417 步收敛） | ✅ 可写，且**现在有完整证据** |

**建议表述（二选一）**：

> **方案 1（推荐，双轨完整）**：*CS 学科 LoRA 微调双轨交付 —— 模型权重轨：Qwen2.5-7B + LoRA r16（已完成，2212 条学科指令，417 步收敛至 train_loss 0.67，160MB adapter 可下载复现）；讯飞生态轨：2212 条学科指令提交星火 MaaS（超 spark pro 1500 条门槛），ServiceID 待回填。*

> **方案 2（突出讯飞生态，赛题友好）**：*面向讯飞星火生态的 CS 学科微调 —— 星火 MaaS 侧 2212 条学科指令已备齐并校验通过；开源侧同步交付 Qwen2.5-7B LoRA adapter 作为可下载权重，双轨互补。*

两个方案都比"星火 8B CS-LoRA"**更实、更扣题**：赛题要"深度结合讯飞星火"，"数据已提交 MaaS + ServiceID"是**可核验的动作**，比一个型号名更有说服力。

## D. 顺带发现的两处仓库不一致（建议一并修）

1. **`README.md` 仍写"训练未执行（无 GPU，诚实标注）"** —— 与 9/9 已交付 adapter 冲突。提交前必须同步，否则五方对账时"代码 ↔ PPT"对不上。
2. **`backend/finetune/export/` 在仓库中不存在** —— 交付包（对照表 / model card / loss CSV / SHA256）只在本地 Downloads，**未归档入库**。材料 05 要求"可复现入口"，建议归档证据文件（adapter zip 146MB 可放 ModelScope 不入库）。

---

# 1. 全局技术数据总表（各页复用，一次给全）

> 这一节是"数据字典"。P4/P5/P6/P13/P14 要画图时，数字全部从这张表取，不要临场另编。

## 1.1 模型与基座层

| 指标 | 实测值 | 出处 |
|---|---|---|
| 默认推理基座 | `deepseek-chat`（OpenAI 兼容端点 `https://api.deepseek.com/v1`） | `backend/app/core/config.py:59`；`backend/finetune/results_deepseek.json` |
| 可插拔 provider | **5 个**：`doubao` / `qwen` / `openai` / `spark` / `deepseek`；未知值回落 `DoubaoClient` | `backend/app/common/llm_client.py:617-634` |
| 讯飞星火 Provider | 已实现（`SparkClient`），单测 6 项通过；**默认型号 `4.0Ultra`**；云端是否启用星火以 `.env` 实配为准 | `llm_client.py:332/346`、`config.py:66-74`、`bootstrap.py:96` |
| 📌 型号名"星火 8B" | 实况：微调基座是 **Qwen2.5-7B**；星火是 **MaaS 渠道**（ServiceID 待提交）。见 §0 C | 交付包 `model_card` |
| 📌 Model Router | 保留命名；**图注须挂实现落点**（provider 选择 + 工具策略门 + 检索门面） | `llm_client.py:617-634` |
| **CS LoRA 微调（已交付）** | **训练已完成**：Qwen2.5-7B-Instruct 基座 / r16 / 2212 条 / 3 epochs·417 步 / RTX 4090 **≈15 分钟** / **train_loss 0.6675**（复跑 0.6690 一致） | `finetune_提交包/`；§0 |
| 可训练参数 | **40.37M**（≈4037 万，占全量 **0.53%**） | `model_card` |
| 微调数据 | 训练 **2212 条**（13 类任务）/ 评测 **50 条**（防污染，基准 10 问不进训练） | 对照表 D |
| 微调评测（诚实口径） | 基准 10 问 **基座 4/8 vs 微调 3/8** —— **不得宣称提升** | 对照表 E |
| 星火 MaaS | 数据 **2212 条**已备齐（超 spark pro 1500 条门槛），**ServiceID 待提交** | `maas/manifest.json` |

**口径定稿（2026-09-10 更新版）**：

> **CS 学科 LoRA 微调双轨交付** —— ① **模型权重轨**：Qwen2.5-7B-Instruct + LoRA r16，2212 条学科指令、417 步收敛至 train_loss 0.67，adapter（161.5MB）可下载可复现；② **讯飞生态轨**：2212 条学科指令提交星火 MaaS（超 spark pro 门槛），ServiceID 待回填。
>
> **效果口径只写三项**：训练收敛、可复现、输出更贴合课程语料风格（定性观察）——**不得写"评测提升"**。
>
> 运行基座另计：现行推理默认 **DeepSeek `deepseek-chat`**（10 用例 9 项自动通过）；星火 Provider 已实现（`SparkClient`，型号字段默认 `4.0Ultra`）。

## 1.2 知识层（双层知识体系）

**A. 精编学科知识库**（`knowledge_data/*.json`，实测）

| 指标 | 实测值 |
|---|---|
| 概念节点 | **112** 个 |
| 关系边 | **106** 条 |
| 文件数 / 课程数 | 11 个 JSON / **10 门课** |
| 课程分布 | 数据结构与算法 24、离散数学 12、数据库系统 10、计算机操作系统 10、机器学习 10、计算机图形学 10、计算机组成原理 9、编译原理 9、计算机网络 9、软件工程 9 |
| 节点 schema | `id / name / node_type / definition / key_points[] / example / source{title,authors,chapter} / aliases[]` |
| 关系 schema | `{from, to, relation_type, note}`，例：`{"from":"ds-001","to":"ds-005","relation_type":"uses"}` |

> 节点结构样例（`algorithms.json` 首节点）：`algo-001 时间复杂度分析 / node_type=method / source=《算法导论（原书第3版）》第 3 章`。

**B. 原始 CS 语料库**（`knowledge_data/corpus/manifest.json`，实测）

| 来源 | 文档数 | 字符数 | 备注 |
|---|---:|---:|---|
| 英文维基 CS 子集 | 117,779 | 675,286,023 | CC BY-SA 4.0 |
| arXiv CS 论文全文 | 33,990 | 2,067,849,683 | CC 授权子集（Common Pile） |
| 中文维基 CS 子集 | 22,770 | 38,129,018 | CC BY-SA 4.0 |
| RFC 全集 | 9,824 | 537,380,084 | IETF 自由分发 |
| 开放教材（OSTEP/SICP） | 72 | 3,066,821 | 作者自由授权版本 |
| **合计** | **184,435** | **3,321,711,629** | **3,501,624,282 bytes ≈ 3.50 GB** |

**C. 混合检索参数**（`knowledge_data/corpus/rag/config.json`，2026-09-09 冻结）

| 参数 | 值 |
|---|---|
| Embedding 模型 | `BAAI/bge-small-zh-v1.5`（本地预置，`revision=local-bge-small-zh-v1.5-20260809`） |
| 向量维度 | **512** |
| 池化 / 归一 | CLS pooling + L2 归一化；查询前缀"为这个句子生成表示以用于检索相关文章：" |
| 最大长度 | 512 tokens |
| 切块 | 目标正文 320 tokens / 相邻重叠 32 / 标题 ≤64；保留段落与代码块边界，超长显式拆分、禁止静默截断 |
| 词法召回 | `lexical_k = 30` |
| 向量召回 | `vector_k = 30` |
| 融合 | **RRF（k=60）** |
| 返回 | `top_k = 6` |
| 上下文预算 | `3000 tokens` |
| 服务 | 仅 loopback `127.0.0.1:8310`，不对公网暴露 |

**⚠️ 状态校正（这一条最容易翻车）**：

| 层 | 真实状态 | 允许说法 |
|---|---|---|
| 精编概念层（112/106） | 【实测】已入库、已接只读检索页 | 可直接说数字 |
| 语料 RAG（184,435 篇） | 【已实现·默认关】CR0–CR6 代码与工具全落地，**部署与全量向量化未执行**；本地无语料文件时盘点如实报 `file_unavailable` | "混合检索链路已实现并冻结参数，全量索引待部署窗口"；**不得写"全量权威语料已接入"** |
| 历史向量 | 前序服务器 COUNT **130,351** 条，仅覆盖部分来源（zhwiki/ostep/sicp），非全量中英向量 | 若要引用，注明"部分来源" |
| 课程知识图谱 | `GRAPHRAG_ENABLED = False`（默认关）；NodeType 17 值、RelationType 15 值 | "课程结构层已实现，真实课程构图按需开启" |

## 1.3 执行层

| 指标 | 实测值 | 出处 |
|---|---|---|
| Judge0 开关 | `JUDGE0_ENABLED = False`（默认关）；云端 Demo 已接独立 Judge0 | `config.py:496` |
| Judge0 状态枚举 | **10 个**：`in_queue / processing / accepted / wrong_answer / time_limit_exceeded / memory_limit_exceeded / runtime_error / compilation_error / internal_error / sandbox_unavailable` | `sandbox_client.py:39-50` |
| Judge0 返回字段 | `status / stdout / stderr / compile_output / time / memory / exit_code / message / token` | `sandbox_client.py:82-93` |
| Judge0 资源默认 | CPU 时限 **5s** / 内存 **128,000 KB** / wall 时限 **10s** / 进程上限 **30** / 文件上限 **1024 KB** / 队列超时 **30s** | `config.py:502-508` |
| Repro Worker 限额 | 总时限 **900s** / 单步 **300s**（部署脚本收紧为 720）/ 磁盘 **2048 MB** / 并发 **1** / 最多 **10 步** / 超时按进程组 `SIGKILL` | `deploy/repro-worker/worker.py:69-76` |
| Repro Runtime | `swe-rex==1.4.0`（MIT）Docker 后端薄 HTTP 封装；只绑 `127.0.0.1:8401`；**T1-b 验证中** | `deploy/repro-runtime/pyproject.toml`、`swerex_adapter.py` |
| 复现预设 | **仅 1 个**：nanoGPT（MIT / `github.com/karpathy/nanoGPT` / 期望 `val_loss = 1.88 ± 0.06`） | `nexus/src/nexus/tools/reproduction.py:22-64` |
| 复现实测 | nanoGPT 端到端通过，作业 `b3002f061502` **5/5 步 succeeded**，实测 `val_loss = 1.8857`（落在期望区间） | `docs/phase1/验收记录/服务器迁移_2026-09-04.md` §6 |
| 实验 stage | **6 段**：`preparing → building → running → metric → verifying → completed` | `worker.py:266` |
| stage 状态 | `started / done / skipped / pending / failed / not_applicable` | `worker.py:525-646` |
| ⚠️ verifying 段 | 恒为 `not_applicable`（无干净环境 B） | 工作记忆 §6 |
| Nexus SSE 事件 | **6 类**：`token / plan / tool_call / tool_result / error / done` | `nexus/src/nexus/main.py:341-681` |
| Nexus 工具面 | **30 个** `@tool`（`NEXUS_TOOLS`），分 7 族：artifact / attachments / course_retrieval / paper_search / paper_research / reproduction / compare / web_search / experiment_intake / research_loop | `nexus/src/nexus/tools/__init__.py:34-71` |
| 智能体文件权限 | `FilesystemMiddleware(tools=["read_file"])` —— 只读单文件，无写、无列目录、无执行 | `nexus/src/nexus/agent.py:393` |
| Middleware | `FilesystemMiddleware` + `SummarizationMiddleware`（显式 token 阈值 50000 / 保留 20 条）+ `TodoListMiddleware` | `agent.py:393-400` |
| 运行→对话回传 | run 列表 `GET /api/v1/nexus/runs`、详情 `/runs/{id}`、取消 `/runs/{id}/cancel-grant`、`live_log_tail` 字段透传 | `nexus_proxy.py:1729/1770/1820/797` |

## 1.4 教学与认知层

| 指标 | 实测值 | 出处 |
|---|---|---|
| TeachingAgent 工作流 | **25 个 LangGraph 节点**（`validate_request → safety_check → … → validate_response → propose_learning_adjustment → record_learning_event`） | `backend/app/platform/agents/edu/workflow.py:1820-1845` |
| 六维认知向量 | `observed_performance_score / evidence_confidence / confusion_risk / inquiry_depth / hint_dependency / explanation_need` | `backend/app/models/cognitive_state_model.py:35-42` |
| 认知状态值 | `unknown / low / medium / high`；证据不足时字段 `None`、`mastery_level` 默认 `unknown` | `:45-50`、`:77` |
| 学习证据类型 | **12 类**：`node_completion / course_completion / quiz_accuracy / quiz_pattern / coding_execution / engagement / questioning / prereq_gap / prereq_recovery / correction / mastery / recommendation` | `backend/app/domain/learning/evidence.py:22-63` |
| 证据写入路径 | 只接受**服务端评分**（`record_scored_evidence`）与 **Judge0 终态聚合**（`coding_episode_finalize_service`）；学生自报分数一律拒绝 | 技术报告 §2.3 |
| 六维公式 | `perf = Σ(score×weight)/Σweight`（窗口 5、有效权重门槛 3.0、代码证据 1.5 > 测验 1.0）；`conf = w/(w+3)`；`confusion = 0.7×错误率+0.3×重复因子`；`need = 0.5×confusion+0.3×(1−perf)+0.2×hint` | 技术报告 §2.3 |
| 掌握分层 | ≥0.8 `advanced` / ≥0.6 `proficient` / ≥0.4 `developing` / 其余 `beginner` | 同上 |
| 六维实现状态 | `rule_baseline` V1 为真实实现；**BKT/DKT/IRT 仅接口定义** | README 能力矩阵 |
| 抗刷分 | 一个 guided session 的多次运行聚合为**一个 evidence episode**（`passed = any(ACCEPTED)`） | 技术报告 §2.3 |
| 双源证据分层 | 交互信号（`LearningEvent`）描述过程；正式评分写 `LearningEvidenceRecord`；二者分域 | README 三项核心机制 |
| 对话最小化投影 | 分析侧只消费 `derive_question_inference_signals`（回看 14 天 / 薄弱阈值 0.4 / trace 上限 5），**不读对话原文** | 技术报告 §2.4 |
| 权限枚举 | **7 项**：`platform.admin / platform.course.create / platform.course.audit / platform.user.manage / platform.safety.manage / platform.capability.manage / platform.nexus.use` | `backend/app/models/access_control_model.py:38-46` |
| 授权决策链 | 课程权限 =（角色基线 ∪ 课程级授权 ∪ 平台级指派）− 拒绝项；入口 `resolve_course_access()` | `course_access_service.py:243` |
| TeachingAgent 返回字段 | `citations`（课程证据闭包）+ `discipline_references`（学科参考，含 `reference_id/release_id/source_kind/authority_label/is_supplementary`）+ `discipline_release_id` + `used_discipline_reference_ids` | `endpoints/teaching_agent.py:562-613` |

## 1.5 工程规模

| 指标 | 实测值 |
|---|---:|
| 后端路由文件 | 67（`include_router` 64 处，前缀统一 `/api/v1/*`） |
| ORM 模型文件 | 48 |
| Alembic 迁移 | 75 |
| 前端页面 `.vue` | 81 |
| 前端组件 `.vue` | 19 |
| 前端 API client `.js` | 49 |
| Nexus 前端能力项 | 7（`course_materials / cs_knowledge / web_search / arxiv_papers / nexuslab_repro / file_upload / paper_evidence`），**当前全部 `ready`** |
| 前端架构 | 双前端：legacy（`/`）+ shadow（`/app/**`，`VITE_ENABLE_SHADOW_FRONTEND` 默认开） |
| 部署 | `https://zsitai.xyz`（HTTPS / Nginx）；主服务器 **4 核 / 8 GB** |

## 1.6 验证与评测基线

| 项 | 结果 | 出处 |
|---|---|---|
| 后端全量回归 | **2749 passed / 6 failed / 22 skipped**（2026-08-20 基线；6 failed 均为可选环境依赖缺失，对应能力默认关闭） | 技术报告 §4.1 |
| 前端契约测试 | **106 用例**（`node --test`） | `frontend/src/api/__tests__/apiContracts.test.cjs` 实测 |
| 典型问题评测（运行基座） | **10 用例，9 项自动全通过**（覆盖助学/助教/助研，七类 CS 知识） | `results_deepseek.json` |
| **LoRA 微调评测（独立口径）** | 基准 10 问 **基座 4/8 vs 微调 3/8** —— **不宣称提升**；C2/C3 未计，50 条待测 | `finetune_提交包/evidence/` |
| **LoRA 训练复现性** | **两次独立运行 train_loss 0.6675 / 0.6690 一致**；417 步；seed 2026 | 对照表 B |
| 语料 RAG 测试 | discipline **176/176**、agents+nexus_internal **261**、Nexus **244**、前端 **97/98**（唯一失败为既有 CourseLayout 旧断言） | 实施计划 §9 |
| Nexus 真实链路冒烟 | DeepSeek 端到端 **6/6 通过**（含 SearXNG 检索、nanoGPT 复现规划、复现执行 fail-closed、会话续聊） | `docs/phase1/验收记录/S1_Nexus真实链路_2026-09-03.md` |
| ⚠️ 规模化用户数据 | **50 人以上尚未采集** | 技术报告 §6 |

---

# 2. 逐页技术细化（P1–P16）

> 每页统一五段：**① 技术主张**（这页要立什么）· **② 关键实现逻辑**（机制 + 代码锚点）· **③ 架构要点**（图上画什么、怎么标）· **④ 可用数据指标**（可直接上图的数字）· **⑤ 口径校核**（脚本原文 → 实况 → 建议）。

---

## P1 封面

**① 技术主张**：定位句 = *面向计算机学科的垂类大模型与可执行智能体平台*。三个动词对应三层真实能力。

**② 关键实现逻辑**：
- "懂学科" → 精编知识库 112 节点锚定权威教材章节（`source.chapter` 字段是真实存在的，可点开）；
- "能执行" → Judge0 十态沙箱 + Repro Worker 受限执行；
- "可核查" → Citation 闭包（`citation_key = SHA-256(artifact_id|block_id|char_start|char_end)[:12]`）。

**③ 架构要点**：背景用代码 / 知识网络 / 执行节点三类元素——这三类恰好对应 L1/L2/L3。**不放产品截图**（脚本原要求，保留）。

**④ 可用数据指标**：建议底部一行极简数据带 —— `184,435 篇 CS 语料 · 112 精编概念 · 106 关系 · 25 节点教学工作流 · 30 个智能体工具 · CS LoRA 微调 2212 条（train_loss 0.67）`。

**⑤ 口径校核**：
- ⚠️ 副标题"专业知识有依据 · 学习结果可验证 · 科研任务能执行"与口径文档白话副标（"让知识有出处，让代码跑得通，让学习有回响"）**不一致**。二者择一，**建议统一为口径文档版本**（该句已落地 README / design.md / 首页 hero）。
- ⚠️ 页码总数写 16 页，但 `competition/04-作品方案/PPT内容稿.md` 现有版本是 10 页。**提交前需声明以哪版为准**，避免五方对账时页数对不上。

---

## P2 痛点：为什么通用 AI 还不够

**① 技术主张**：计算机学科天然可执行 → 因此有资格要求"可验证"，这是本作品全部技术决策的起点。

**② 关键实现逻辑**（每一条痛点都对应一个真实机制，讲解时可直接举例）：
- 痛点 01 长尾/版本敏感 → 语料层含 **RFC 全集 9,824 篇**、arXiv CS **33,990 篇**，按 `source_kind` 区分 `textbook/wiki/rfc/arxiv` 并保留原始许可；
- 痛点 02"说得对≠跑得对" → 现成反例可用评测集 **C3**：一段 C 反转字符串函数有**三处**缺陷（循环边界应为 `n/2`、`s[n-i]` 越界应为 `s[n-1-i]`、未处理空串），静态阅读极易漏判，Judge0 实跑 `reverse("hello")` 输出非 `olleh` 才暴露；
- 痛点 03 止步于解释 → 证据链 `LearningEvidenceRecord` **12 类**，其中 `coding_execution` 只接受服务端终态；
- 痛点 04 只给建议 → Nexus 三问分离（能不能跑 / 该不该跑 / 跑没跑成）。

**③ 架构要点**：四痛点 + 对应机制的双列对照，右侧可挂 C3 代码片段。

**④ 可用数据指标**：C3 三处缺陷、Judge0 10 态、preset 1 个（说明"能跑"的范围是真实的、有限的）。

**⑤ 口径校核**：无风险。建议在痛点 04 补一句"当前受控预设 1 个（nanoGPT）" —— **主动交代边界比被追问更有利**。

---

## P3 产品定位：一核两翼

**① 技术主张**：不是三卡片平级，而是"一个底座 → 两个应用"。

**② 关键实现逻辑**（底座五件套的真实落点）：

| 脚本提法 | 真实对应 | 状态 |
|---|---|---|
| 星火 8B CS-LoRA | **CS LoRA 已完成**（Qwen2.5-7B 基座 / r16 / 2212 条 / 417 步 / train_loss 0.67 / 15 分钟）＋ **星火 MaaS 数据已备齐**（2212 条，ServiceID 待提交） | 【已交付】 |
| CS Corpus | `knowledge_data/corpus/` 184,435 篇 | 【已实现·默认关】 |
| Course Knowledge | `CourseKnowledgeNode` / `GraphSnapshotRecord` / `CourseKnowledgeBundle` | 【已实现·默认关】 |
| Professional Tools | Judge0（10 态）+ Repro Worker（900s/1C/2G）+ SWE-ReX 1.4.0 | 【已实现·默认关】 |
| Agent Runtime | `edu/workflow.py` 25 节点 LangGraph / Nexus 独立 Runtime 30 工具 | 【实测·本地】 |

**③ 架构要点**：底座画成"核心"，Teaching 与 Research 各一条箭头延伸；**底座内部五件套必须带来源标签**（星火 / CodeNexus / 开源 / 第三方），呼应 P13 的色码。

**④ 可用数据指标**：五件套各自的量化（184,435 / 112–106 / 25 节点 / 30 工具 / 5 provider）。

**⑤ 口径校核**：
- 📌 **"星火 8B CS-LoRA" 保留叙事**（云端已上线）。**但事实已查明**：LoRA 训练**真实完成**，基座是 **Qwen2.5-7B**（不是星火、不是 8B）——详见 §0。建议落笔为 **"CS 学科 LoRA 微调（Qwen2.5-7B / r16 / 2212 条 / train_loss 0.67）+ 星火 MaaS 数据已备齐（2212 条 / ServiceID 待回填）"**，双轨并写：既有已交付权重，又回应讯飞生态要求。
- ✅ 左翼"运行验证""学习路径"：`learning_path_service` 判弱条件是真实实现的（表现 <0.5 且样本 ≥3 且衰减后置信度 ≥0.6），可以放心讲。
- ✅ 右翼"循环研究""报告产出"：写"受控执行型智能体"，**不写"全自动科研"**。

---

## P4 总体技术架构

**① 技术主张**：五层拆解 + 明确的**技术来源边界**。

**② 关键实现逻辑**（五层的真实模块映射）：

| 层 | 真实承载 |
|---|---|
| L1 用户与应用层 | Vue 3 前端 `/app/**`（81 页面 / 双前端）；TeachingAgent 入口 `/app/course/:id/learn`；Nexus 入口 `/app/nexus`；学科检索 `/app/discipline-knowledge` |
| L2 Agent Orchestration | `edu/workflow.py` **25 节点**（多轮上下文 / 安全校验 / 意图识别 / 证据检索 / 教学动作决策 / 引用校验 / 学习事件）；Nexus `create_deep_agent` + TodoListMiddleware + SummarizationMiddleware |
| L3 能力路由层 | **Model Router**（保留自研命名）= ① provider 选择（`LLMClient._create_client()`，5 个 provider）+ ② 工具级 policy check（`tool_governance.py`）+ ③ 检索门面（`search_corpus_unified`） |
| L4 学科能力层 | 模型：**CS LoRA 微调适配（Qwen2.5-7B，权重已交付）**；知识：112 精编节点 + 184,435 篇语料 + RRF 混合检索 + Citation；工具：Judge0 / Repro Worker / 文档解析（Docling + LibreOffice/Poppler + PaddleOCR） |
| L5 工程基础设施 | FastAPI + SQLModel/Alembic（48 模型 / 75 迁移）+ PostgreSQL 16 + pgvector + Docker + Vue 3.5/Vite |

**③ 架构要点（色码与标签的实体清单，按实况重列）**：
- **讯飞蓝 [XF Spark]**：**星火 MaaS 微调通道**（2212 条学科指令已备齐、约束校验通过，ServiceID 待回填）。画在 L4 模型层的"讯飞生态"子块；
- **深灰 [CodeNexus]**：TeachingAgent(25 节点) / Nexus Runtime / Retrieval Service / Model Router / Learning Evidence（12 类）/ Course Knowledge（112/106）/ Agent Runtime / 混合检索（RRF k=60）；
- **橙色 [3rd Party]**：Judge0；
- **补充一类 [Open Source]**：SWE-ReX 1.4.0 / Deep Agents / LangGraph / Docling / PaddleOCR / pgvector / SearXNG。

**④ 可用数据指标**：`25 节点 / 5 provider / 30 工具 / 10 态沙箱 / 75 迁移 / 112+106 / 184,435`。

**⑤ 口径校核**：
- 📌 **"Model Router" 保留命名**。图注必须给出实现落点：把名字与**provider 选择**（`LLMClient._create_client`）**+ 工具策略门**（`tool_governance`）**+ 检索门面**（`search_corpus_unified`）三个真实模块绑死，"路由代码在哪"就不再是漏洞。
- 📌 **"Spark 8B CS-LoRA" 保留叙事，但数字要改**：LoRA 基座是 **Qwen2.5-7B**（不是 8B），且训练**已完成**（§0）。建议写"Qwen2.5-7B LoRA 微调（已交付权重）+ 星火 MaaS 数据已备（2212 条）"。
- ✅ 第五层建议补"双前端（legacy + shadow）"，`/app/**` 是 shadow 前端。
- ✅ "Hybrid RAG" 保留，建议补参数（RRF k=60 / 词法 30 / 向量 30 / top6 / 3000 tokens）——**有具体参数的技术名词才可信**。

---

## P5 四大创新总览

**① 技术主张**：四个创新 = 四组**职责分离**的机制，不是四个技术名词。

**② 关键实现逻辑**（与脚本 §附录 A 的标准说明一一对应，并挂可查锚点）：

| 创新 | 机制核心 | 代码锚点 |
|---|---|---|
| 01 模型—知识—工具协同 | 三者职责分离、互相制衡 | `LLMClient` / `discipline_corpus.py` / `sandbox_client.py` |
| 02 双层知识体系可追溯生成 | 学科语料给事实，课程图谱给结构 | `discipline_corpus.py::search_corpus` / `CourseKnowledgeBundle` |
| 03 "回答→执行→证据→反馈"闭环 | 真实执行结果进入正式证据 | `edu/workflow.py` 25 节点 + `coding_episode_finalize_service` |
| 04 受控执行型智能体 | 白名单 + 审批票据 + 数值判定 + 受限 Worker | `nexus/tools/reproduction.py` + `deploy/repro-worker/worker.py` |

**③ 架构要点**：中心"CodeNexus Intelligence Core"分两栏——**CS 学科 LoRA 微调模型**（专业增强，权重已交付，标 `[Qwen + CodeNexus]`；星火 MaaS 通道标 `[XF Spark]`）与 **高能力通用模型**（复杂推理与规划）；三个外部能力域（A 双层知识 / B 可验证教学流 / C 云端科研实验）。

**④ 可用数据指标**：创新 03 可挂"12 类证据 / 25 节点 / Judge0 10 态"；创新 04 可挂"1 preset / 900s / 1C / 2G / 并发 1 / 10 步"。

**⑤ 口径校核**：
- 📌 **"垂类模型是学科核心"这句现在有实证撑腰**：LoRA 训练真实完成（417 步收敛至 train_loss 0.67、两次独立运行一致、adapter 161.5MB 可下载）。建议写法：**"CS 学科 LoRA 微调：Qwen2.5-7B 基座 + r16 适配，2212 条学科指令，417 步收敛；星火 MaaS 侧 2212 条数据已备齐"**。
- ⚠️ 但**效果口径只能写三项**（收敛 / 可复现 / 风格贴合），**不得写"评测提升"**——实测基座 4/8 vs 微调 3/8（§0 B）。
- ✅ 创新 03 的措辞"计算机学科独占，其他学科复制不了"成立且是好句，保留。

---

## P6 创新二：双层知识体系

**① 技术主张**：学科知识回答"是什么"，课程知识决定"怎么学"。**两层各管一件事，不冲突。**

**② 关键实现逻辑**：
- 左侧（学科层）：原文切块（320/32）→ 本地 embedding（bge-small-zh-v1.5，512 维）→ FTS/BM25 + 向量双路各 30 条 → RRF(k=60) 融合 → top 6 → 3000 tokens 预算；结果带 `reference_id`（形如 `{release_id}:{chunk_id}`）、`source_kind`、`authority_label`、`is_supplementary=true`；
- 右侧（课程层）：`CourseKnowledgeNode`（NodeType 17 值）→ `GraphSnapshotRecord`（发布时前一活跃快照转 `SUPERSEDED`）→ `CourseKnowledgeBundle`；
- 中间链路：`Retrieval → Citation → Answer`，Citation 是**闭包校验**（答案中每个 `evidence_id` 必须属于本次检索结果集），不是格式检查。

**③ 架构要点**：左右两栏 + 中间链路；**必须画出"两层不混"**：学科层进的是"补充参考"，课程层进的是"正式引用"（`citations` vs `discipline_references` 是两个独立返回字段，这是硬边界）。

**④ 可用数据指标**：左：184,435 篇 / 512 维 / RRF k=60 / top6 / 3000 tokens；右：112 节点 / 106 关系 / 10 门课 / NodeType 17 / RelationType 15。

**⑤ 口径校核**：
- ⚠️ 脚本写"BM25 / FTS / Vector Retrieval / Hybrid RAG"——**OK，但不要写 GraphRAG**。口径文档明令：`GraphRAG 检索` → 改为 `FTS/BM25 + 本地向量 + pgvector 混合检索`。
- ⚠️ 左侧来源写"教材、专业资料"应精确化为"五类：教材 / 中英维基 / RFC / arXiv"，**因为 `source_kind` 是真实字段且决定 `authority_label`**（"未知来源不全称教材"是实现事实）。
- ⚠️ 不得写"全量语料已接入检索"（见 §1.2 状态校正）。

---

## P7 创新三：智慧教学闭环

**① 技术主张**：AI 不在回答处结束；执行结果成为下一轮教学的依据。

**② 关键实现逻辑**（七步 → 真实机制）：

| 脚本步骤 | 真实实现 |
|---|---|
| 1 产生疑问 | `/respond` 或 `/respond-for-learner` 入口 |
| 2 回答讲解 | 25 节点工作流：`safety_check → detect_intent → resolve_concept → retrieve_evidence → retrieve_discipline_knowledge → generate_response` |
| 3 执行代码 | `decide_teaching_action` → 代码挑战提案（`coding-challenges/offers/{id}`）→ 学生接受后 `start` |
| 4 真实验证 | `POST coding-challenges/sessions/{id}/runs` → Judge0（10 态：accepted / wrong_answer / time_limit_exceeded / memory_limit_exceeded / compilation_error / runtime_error …） |
| 5 反馈讲解 | `load_coding_diagnosis` 节点读回执行终态 → 白名单反馈（不泄露完整参考实现） |
| 6 Learning Evidence | `close_session` → **一个 session 聚合为一条 episode 证据**（`passed = any(ACCEPTED)`）→ 写 `coding_execution` |
| 7 下一轮学习 | `propose_learning_adjustment` + `record_learning_event` → 六维认知 → 路径推荐（判弱条件：perf<0.5 且样本≥3 且衰减后 conf≥0.6） |

**③ 架构要点**：七步纵向流程 + 右侧标注"哪一步产生正式证据"（第 6 步是唯一入口）。

**④ 可用数据指标**：25 节点 / 12 类证据 / 10 态 / 六维（含 6 个维度英文名）/ `conf = w/(w+3)`。

**⑤ 口径校核**：
- ⚠️ **状态必须写"本地端到端已验收"**，不能写"已上线"。`README` 明载：真实课程 + 真实 Judge0 冒烟**未部署**。
- ✅ "抗刷分"是本页最有说服力的细节（一次 session 多次提交只算一条证据），**强烈建议加一行**——它能证明"学习证据"不是营销词。
- ⚠️ 六维展示时**必须标注"规则基线 V1，BKT/DKT 为研究项"**，否则被问"用的什么模型"会失分。

---

## P8 创新四：Nexus 科研智能体

**① 技术主张**：从"研究建议"到"云端实验执行"——**但严格限定在受控范围内**。

**② 关键实现逻辑**（脚本七步 → 真实机制；注意**真实的 stage 只有 6 段**）：

| 脚本 Research Loop | 真实 stage / 机制 |
|---|---|
| 1 Research | `search_arxiv_papers`（arXiv API，3s 限速 + 1 天缓存）+ `web_search`（SearXNG 主通道 → DuckDuckGo 降级）+ `search_cs_knowledge` |
| 2 Plan | `TodoListMiddleware` 的 `write_todos` → 投影为 `plan` SSE 事件 + `GET /api/v1/nexus/plan/{session_id}` 只读恢复 |
| 3 Environment | stage `preparing` → `building`（`environment_builder.py` / SWE-ReX `PUT /sandboxes/{run_id}`） |
| 4 Experiment | stage `running` → `metric` |
| 5 Reflection | 失败分析：Worker 日志尾部 + `add_reproduction_note` |
| 6 Iterate | `run_reproduction` 重新提交（**参数在 run 之间改，从不在 run 中途改**） |
| 7 Report | stage `completed` → `write_research_report`（服务端按登记渲染引用写 Markdown Artifact） |
| （脚本无） | stage `verifying` —— **恒为 `not_applicable`** |

**③ 架构要点**：Research Loop 画成环；受控执行画成**四边界**而非三要点：

```text
能力边界  preset 白名单（当前 1 个：nanoGPT，MIT，val_loss 1.88±0.06）
授权边界  审批票据（consume_approval 原子核销，不可重放）
判定边界  数值阈值（val_loss ∈ [1.82, 1.94]）——结论是数字，不经 LLM
执行边界  独立容器 + 独立网络 repro_net；900s / 1C / 2G / 并发 1 / 10 步 / SIGKILL
```

**④ 可用数据指标**：30 工具 / 6 段 stage / 6 类 SSE 事件 / 900s / 2048MB / 实测 `val_loss=1.8857`。

**⑤ 口径校核**：
- ⚠️ **脚本写 7 段，真实 stage 是 6 段**。建议：**保留"七步研究循环"作为叙事**（这是合理的抽象），但在截图/日志页明确标出真实 stage 名（preparing/building/running/metric/verifying/completed），二者不要混。**图上出现日志就必须用真实 stage 名**。
- ⚠️ **"任务可恢复"是真实能力**（`NEXUS_POSTGRES_DSN` 配置后切 PostgresSaver，独立 schema `nexus_checkpoints`，重启可续；未配置时内存续聊），可以讲，但要注明"持久化需配置 DSN"。
- ⚠️ **严禁写"全自动科研"**。用"受控执行型智能体"。
- ⚠️ 脚本"受控执行只保留三点"建议扩为四点（上表），三点的版本漏掉了最有说服力的**数值判定**——那一条恰恰是"复现结论不经 LLM 之口"的证据。

---

## P9 Hero Case：Dijkstra 纵向深度

**① 技术主张**：一条教学链路如何纵向穿过 Think → Act → Observe → Think → Teach。

**② 关键实现逻辑**：
- Think：`resolve_concept` 定位"最短路/贪心正确性" → `retrieve_evidence`（课程证据）+ `retrieve_discipline_knowledge`（学科参考，会带回"贪心选择性""最优子结构"类节点）；
- Act：生成负权最小反例 → 代码挑战 run → Judge0 执行 → 返回错误路径（如 `A→B→C` 负环导致已定终点被后续松弛）；
- Observe：Citation 展示（`reference_id` 可点回原文）+ Code Workspace 执行结果 + 反馈；
- Teach：`load_coding_diagnosis` → episode 证据 → `propose_learning_adjustment` → 指向 Bellman-Ford / SPFA。

**③ 架构要点**：强制三泳道（Think / Act / Observe）+ 折线路径。**这一页的关键是"折线要跨泳道"**——跨泳道次数越多，越能体现闭环。

**④ 可用数据指标**：本次链路可点出的真实对象 —— 学科参考 `reference_id`、课程引用 `evidence_id`、Judge0 `status/time/memory`、证据类型 `coding_execution`。

**⑤ 口径校核**：
- ✅ **脚本已有的"注意"非常重要，务必保留**：问句必须写 **"为什么 Dijkstra 遇到负权边可能失效？"**，不写"不能处理负权边"。
- ⚠️ 但需注意：**口径文档 §9 案例一用的正是"为什么 Dijkstra 不能处理负权边？"**——两处不一致。**建议以脚本（更严谨）为准，并回头同步口径文档**，否则五方对账时会被指出自相矛盾。
- ⚠️ 演示前需确认该反例在 Demo 环境真的跑过（Judge0 云端通道 / 本地沙箱），否则改为已实测的案例。

---

## P10 Nexus 科研实验短视频

**① 技术主张**：用真实运行证明 Nexus 进入环境执行，而不是只输出建议。

**② 关键实现逻辑**（视频时间轴 → 真实日志/字段）：
- 0–5s：`POST /api/v1/nexus/chat/stream`；
- 5–10s：SSE `plan` 事件（来自 `write_todos` 真实 state 投影）；
- 10–18s：stage `preparing` / `building` 的真实日志；
- 18–28s：stage `running` 的 `stdout` 增量（`live_log_tail` 2000 字符环形缓冲）+ `metric`；
- 28–36s：stage `failed` → 修正 → 重跑（**必须真实发生**）；
- 36–45s：`completed` → Experiment Summary / Metrics / Files / Markdown Report（`write_research_report`）。

**③ 架构要点**：脚本里的示意日志建议替换为**真实日志格式**：

```text
[preparing] started
[building ] done
[running   ] started
[metric    ] pending
[verifying ] not_applicable      ← 如实展示，不要画成绿色完成
[completed ] done
```

**④ 可用数据指标**：可直接放实测数字 —— 作业 `b3002f061502`，**5/5 步 succeeded**，`val_loss = 1.8857`（期望 1.88 ± 0.06）。**这是全片最有价值的一个数字**，因为它可复现、可核对。

**⑤ 口径校核**：
- ⚠️ **"失败→重试"必须真实发生才可剪**。README 记载 Repro Worker 已部署、nanoGPT 端到端通过，但**"失败后自动修正环境并重试"的完整闭环未见实测记录**。若视频无真实失败素材，**改为展示"取消/超时如实保留终态"**（`cancel` 幂等、超时 SIGKILL 是真实实现）。
- ⚠️ **不要用"Resolving dependencies / Creating isolated environment"这类英文示意日志**，除非截图来自真实终端。**虚构日志是附录 E 明令禁止项。**
- ⚠️ 若视频里出现 verifying 段，**必须显示"不适用"**。

---

## P11 三类任务，三条可核查证据链

**① 技术主张**：不要求 AI 永远正确，而要求关键结论能被核查。

**② 关键实现逻辑 + 可用字段（照真实字段列表写，不臆造）**：

**案例一 KNOW｜版本敏感专业知识**

| 项 | 真实内容 |
|---|---|
| 可检索来源 | RFC（9,824 篇）/ 中英维基 CS / arXiv CS / OSTEP·SICP ＋ **云端演示前导入的 PyTorch 文档** |
| 输出字段 | `reference_id` / `chunk_id` / `doc_id` / `section_path` / `source_kind` / `source_url` / `license` / `authority_label` / `matched_by`（`fts`/`vector`）/ `is_supplementary` |
| 核验 | `GET /api/v1/discipline-knowledge/chunks/{chunk_id}?release_id=...` 回读原文；`source_url` 为空时不渲染链接；撤回来源返回 **410** |

**案例二 RUN｜中等难度算法挑战**

| 项 | 真实内容 |
|---|---|
| 执行 | Judge0 独立沙箱 |
| 字段 | `status`（10 态枚举）/ `stdout` / `stderr` / `compile_output` / `time` / `memory` / `exit_code` |
| 资源 | CPU 5s / 内存 128,000 KB / wall 10s / 进程 30 / 文件 1024 KB |

> 脚本要求"Runtime / Memory 只有真实链路确实返回并展示时才放"—— **实测结论：`time` 与 `memory` 是 `SandboxResult` 的真实字段，可以放**。注意字段名是 `time`（不是 `runtime`）。

**案例三 RESEARCH｜小型科研对比实验**

| 项 | 真实内容 |
|---|---|
| 可用预设 | nanoGPT（已实测 `val_loss 1.8857`）；排序算法对比实验需**云端补 preset 条目**（纯 CPU 任务，可行性高） |
| 证据 | stage 轨迹（6 段）/ `metrics` / artifact 元数据 / Markdown Report |
| 判定 | 数值阈值判定，非 LLM 判定 |

**③ 架构要点**：三列并排，**底部三行收口**：`KNOW → Citation` / `RUN → Execution Result` / `RESEARCH → Experiment Artifact`。

**④ 可用数据指标**：见上表；另可挂"10 态 / 9 字段 / 6 段 stage / 410 撤回语义"。

**⑤ 口径校核**：
- 📌 **案例一（`torch.compile`）家良决定保留，云端导入资料即可支撑**。
  **落地动作（两步，缺一不可）**：
  ① 把 PyTorch 官方文档或对应版本说明导入语料 —— `python backend/scripts/import_discipline_corpus.py --source-set cs-public --source-root <dir>`；
  ② **必须重建索引** —— `manage_corpus_index.py build --from-build <id> → validate → activate`。
  > ⚠️ 只导入不重建，检索命中的仍是旧 release，截图会露馅。演示前用一次真实查询确认 `reference_id` 指向新导入文档。
- ✅ 案例二不得写 LeetCode 品牌（脚本已注意，保留）。
- 📌 **案例三（排序算法 / Ridge 对比）家良决定保留，云端会准备**。需分清两件事：
  - "导入资料"解决的是**知识侧**（Citation）；案例三属**执行侧**，它需要的是 **preset 条目**（`REPRO_PRESETS`），不是文档。
  - **落地动作**：在 `nexus/src/nexus/tools/reproduction.py` 的 `REPRO_PRESETS` 增加一项（repo/命令/steps/期望指标区间），并在云端 Worker 真跑一次留下 run 记录。
  - 好消息：排序算法耗时对比是**纯 CPU 任务**，无 GPU 依赖，加 preset 成本低、可行性高。
  > ⚠️ **有 run 记录才叫"可复现"**。只有资料没有 run，这页的证据链是断的——评审问一句"跑过吗"就答不上来。

---

## P12 真实 UI + 真实使用反馈

**① 技术主张**：证明系统已进入真实教学场景。

**② 关键实现逻辑（三张截图的真实落点）**：

| 截图 | 真实路径 | 红框标注 |
|---|---|---|
| Screenshot 1 | `/app/course/:courseId/learn` 助教气泡 | `citations`（课程证据闭包）+ `discipline_references`（学科参考，带 `authority_label` + `reference_id` 可点开原文） |
| Screenshot 2 | 代码挑战 run 结果 | Judge0 `status` + `stdout` + `time`/`memory` |
| Screenshot 3 | `/app/nexus` 实验工作台 | `plan`（Todo 投影）+ Console（`live_log_tail`）+ 6 段 stage 时间线 |

**③ 架构要点**：左 70–75% 三图，右 25–30% 反馈卡。脱敏要求（姓名/QQ/微信/头像/学号/手机号）**照脚本执行**。

**④ 可用数据指标**：本页人数取**云端真实统计值**（见校核）。

**⑤ 口径校核**：
- 📌 **"50+ Students" 家良决定保留**（云端已真实上线）。**这一项与其他三项性质不同：它不是技术表述问题，是数据真实性问题**，且"导入资料"解决不了。附录 F 要求"所有用户身份与反馈真实可核验"。**需闭合两件事**：
  - ① **真实人数** —— 写实际数；写"50+"须实际 ≥50（后台统计或班级名单可查）；
  - ② **可核验载体** —— 班级群讨论、课程名单或后台使用留痕（脱敏后可用）。
  > 只要有真实数字，这页是全 PPT 最有说服力的一页——**它是唯一能证明"真的有人在用"的页面**，比任何架构图都硬。若暂时给不出，最小改动是把 "50+ Students" 换成实际人数，版式不用动。
- ✅ 优先级 A（教授 / 副教授 / 课程负责人 / ACM 教练）**身份必须真实可核验**；脚本已注明。
- ⚠️ 不得把指导教师评价包装成独立用户认可（附录 F）。

---

## P13 工程技术方案

**① 技术主张**：从垂类模型到执行环境的工程化落地 + 明确的来源边界。

**② 关键实现逻辑（五个技术域的真实清单）**：

| 域 | 真实内容 | 来源标签 |
|---|---|---|
| **Model** | **CS LoRA 微调**（Qwen2.5-7B 基座，r16，2212 条，417 步收敛至 loss 0.67，adapter 已交付）＋ **星火 MaaS 通道**（2212 条数据已备，ServiceID 待回填）＋ **Model Router**（provider 选择：doubao/qwen/openai/spark/deepseek） | `[Qwen]` + `[XF Spark]` + `[CodeNexus]` |
| **Agent** | TeachingAgent（25 节点 LangGraph / 自研 Port-Provider 契约）；Nexus（30 工具 + Deep Agents + TodoListMiddleware + SummarizationMiddleware，独立 venv） | `[CodeNexus]` + `[Open Source]` |
| **Knowledge** | 精编 112/106；语料 184,435 篇；混合检索 RRF k=60；PostgreSQL 16 + pgvector；Citation 闭包 | `[CodeNexus]` + `[Open Source]` |
| **Execution** | Judge0（10 态 / 5s / 128MB / 独立沙箱）；Repro Worker（900s / 1C / 2G / 并发 1 / 10 步）；**SWE-ReX 1.4.0**（MIT，Docker 后端，T1-b 验证中） | `[3rd Party]` + `[Open Source]` + `[CodeNexus Integration]` |
| **Platform** | FastAPI（67 路由 / 48 模型 / 75 迁移）；PostgreSQL 16 + pgvector；Vue 3.5 + Vite（双前端，81 页面） | `[CodeNexus]` + `[Open Source]` |

**③ 架构要点（编号表必须修订）**：

| 编号 | 脚本写 | 建议改为 |
|---|---|---|
| M1 | Model Router | ✅ **保留名称**；图注挂实现（provider 选择 + 工具策略门 + 检索门面） |
| K1 | Retrieval / Citation | ✅ 保留（真实：RRF 混合检索 + Citation 闭包） |
| A1 | Tool Gateway | **A1 工具策略门**（`tool_governance.py`，分级失败语义：高风险 fail-closed） |
| E1 | Judge0 | ✅ 保留 |
| E2 | Nexus Sandbox | **E2 实验沙箱**（Repro Worker + Repro Runtime / SWE-ReX Docker 后端） |
| D1 | Data Layer | ✅ 保留（四域分离 + 最小化投影） |

**④ 可用数据指标**：见上表；工程规模数字（67/48/75/81/49/106）全部可直接上屏。

**⑤ 口径校核**：
- ✅ **"SWE-ReX"是真实的**（`swe-rex==1.4.0`，MIT，`deploy/repro-runtime/`），**不要因为"看起来像新词"而删掉**——它恰恰证明"独立执行环境"不是口号。建议补一行"容器不挂 docker.sock、不读宿主业务卷、只绑 127.0.0.1"。
- 📌 **"Model Router" 保留**（同 P4）；图注挂实现落点即可。
- ✅ "LangGraph / Deep Agents" 标签应为 `[Open Source]`；"TeachingAgent / Nexus AI" 为 `[CodeNexus]`。脚本已区分，正确。
- ⚠️ 无 HNSW：当前索引方案声明为 `exact-member-filtered`，**未建 HNSW**（无 PG 环境验证）。若图里画"ANN 索引/HNSW"，需改为"成员过滤精确排序"。

---

## P14 安全控制与执行证据

**① 技术主张**：Risk → Control → Evidence。**每一条风险必须能找到实际控制层，且能看到证据。**

**② 关键实现逻辑（六条证据链的真实机制映射）**：

| # | Risk | Control（真实机制 + 锚点） | Evidence（可展示的真实产物） |
|---|---|---|---|
| 1 | 危险命令 `rm -rf /` | E1 Judge0 独立沙箱（物理隔离 + 命令黑名单）/ E2 执行容器不挂 docker.sock、不读宿主卷 | Judge0 状态 `internal_error` / `runtime_error`；容器隔离核验脚本 `deploy/repro-runtime/scripts/verify_host.sh` |
| 2 | 无限循环 `while(true){}` | CPU Time Limit **5s** + wall 10s（Judge0）；Repro 侧单步 300s / 总 900s，超时按进程组 `SIGKILL` | `status = time_limit_exceeded`；Repro 日志 `TIMEOUT after 300s (SIGKILL)` |
| 3 | 超量内存 | Judge0 `memory_limit = 128,000 KB`；Worker `--memory 2g` + 磁盘配额 2048MB | `status = memory_limit_exceeded` |
| 4 | 高风险 Tool Calling | A1 工具策略门：per-tool policy check + **分级失败语义**（高风险 `web_research` / `trigger_experiment` / `change_topic` 治理异常时 **fail-closed**；低风险 fail-open）；审批票据 `consume_approval` 原子核销 | 审批 UI、`agent_tool_invocations` 审计摘要（截断 2000 字符 / payload ≤64KB） |
| 5 | AI 内容透明 | K1 Citation 闭包（引用必须是本次检索结果子集）+ `is_supplementary=true` + `authority_label` | 真实 UI 截图：可点开的 `reference_id`、来源标签 |
| 6 | 敏感数据 | D1 四域分离（交互 / 评分 / 对话 / 审计）+ 对话最小化投影（分析侧只拿结构化信号，不读原文）+ Course Access v1 唯一授权入口 | 投影字段结构（提问计数 / 平均深度 / 薄弱推断 / trace 引用，**不含原文**） |

**③ 架构要点**：工程取证 / 线索关联图（脚本要求），**禁止大盾牌与口号矩阵**。

**④ 可用数据指标**：`5s CPU / 128MB / 10s wall / 30 进程 / 1024KB 文件 / 900s 总 / 300s 单步 / 2GB 磁盘 / 并发 1 / 10 步`。

**⑤ 口径校核（本页禁区最多）**：
- ✅ 脚本的"禁止写未经验证的安全术语"必须严格执行。**实测结论**：`Seccomp Profile` / `network syscall blocked` / `egress deny` / `kernel capability drop` **在仓库中均无对应配置证据**，一律不写。
- ⚠️ 脚本把 "CPU / Memory quota" 也列入禁止词，但**实测这两项是真实存在的**：Judge0 `JUDGE0_DEFAULT_CPU_TIME_LIMIT=5` / `JUDGE0_DEFAULT_MEMORY_LIMIT=128000`，Worker `--cpus 1.0 --memory 2g`。**建议解禁这两项**，改为可写（附配置出处）——这是白捡的加分项。
- ⚠️ **"通过"用词要精确**：**"工具治理 fail-closed"** 只在**治理查询异常时**触发，不是所有工具都 fail-closed。写"高风险工具治理异常时失败关闭"。
- ⚠️ 断网/出站白名单：Repro Worker **有** `refresh-iptables.sh` 出站白名单（仅 GitHub / PyPI(tuna) / pytorch 轮子源），这是**真实的**，可写；但要说清"仅限 Repro Worker 容器，非全局网络隔离"。
- ✅ 推荐安全证据测试 6 项（无限循环 / 超量内存 / 非法路径 / 高风险命令 / 网络访问 / 高风险 Tool Call）**提交前逐项真跑并截图**——脚本已列，落实即可。

---

## P15 商业化：学科智能能力包

**① 技术主张**：可复制的不是 UI，而是"学科能力四件套"。

**② 关键实现逻辑（对应口径文档 §10 的定稿）**：

```text
一个"学科能力包" = LoRA Adapter + 学科语料索引 + 工具链与策略 + Agent Workflow & 课程图谱规范
```

替换四件套即可换学科：**`LoRA Adapter + Corpus + Tool Policy + Workflow Template`**。

**③ 架构要点**：`CS → AI → SE → DS` 复制路径；客户形态五类（高校学院 / 单课 / 教学平台 / 科研团队 / 教育平台厂商）。

**④ 可用数据指标**：四件套的可复制性论据 —— 语料构建脚本（`knowledge_data/corpus/` 含 8 个抓取/提取脚本）、知识库校验脚本（`validate.py`）、预设机制（`REPRO_PRESETS` 数据驱动）、能力开关（`feature_flags` 7 项 + `TEACHING_AGENT_MODE`）。**"数据驱动的可替换"比"我们以后也能做"有说服力得多。**

**⑤ 口径校核**：
- ⚠️ 脚本用"Computer Science Intelligence Pack / Domain Model / Domain Corpus"是英文包装，**与口径文档的中文四件套不完全对齐**。建议中英分开用：对外标题用英文，落到机制时**用口径文档的四件套**，避免两套说法。
- ⚠️ 赛题看的是"高校/学科规模化复制"，**不要出现学生会员、C 端订阅类表述**。

---

## P16 迭代计划 + 团队 + Ending

**① 技术主张**：从 CodeNexus 1.0 到学科智能基础设施。

**② 关键实现逻辑（下一阶段的真实缺口，按优先级写）**：

| 方向 | 真实待办（来自审计） |
|---|---|
| 模型能力 | ① **星火 MaaS 提交**（数据集 2212 条已备，待 ServiceID 回填）② **LoRA 效果提升**（扩同源数据 / 调 epoch / 叠加 RAG 再评 —— 当前基准口径未提升）③ provider 选择升级为任务级分流 |
| 知识能力 | ① 语料 RAG 部署 + 小批→全量向量化 ② PG 上的 HNSW/查询计划验证 ③ 片段上下文与引用增强（Nexus `/cs-knowledge` 当前只查精编节点） |
| Agent 能力 | ① Nexus `mode`/`context.course_id` 两层静默丢弃（P0，课程资料注入未通）② 全量日志回看 / 指标时序 / 结构化 config（GAP-1/3/4）③ 长任务恢复 |
| 可复制能力 | 四件套参数化 → AI / SE / DS |

**③ 架构要点**：左侧迭代四条，右侧团队分工（技术 / 产品 / 算法 / 设计），Ending 大字。

**④ 可用数据指标**：把"待办"写成**可验收的**指标（如"语料检索热查询 p95 ≤ 3s（不含生成）"——这是实施计划里的真实验收门）。

**⑤ 口径校核**：
- ⚠️ **团队信息全部待填**（成员/职责/指导教师在仓库中无数据）。**不要用占位文本提交**。
- ✅ Ending 句"让 AI 不止回答计算机科学，而是真正参与学习、验证与研究"与口径文档一致，保留。
- ⚠️ 迭代表**不要出现完成时态的未完成项**（附录 H 第 6 条）。

---

# 3. 口径校正汇总表

> **表前说明**：标记 📌 的项已保留原表述并给出配套落地动作；其余项仍建议按"建议表述"列修改。

| # | 位置 | 脚本原文 | 实况 / 决策 | 建议表述或动作 | 依据 |
|---|---|---|---|---|---|
| 1 | P1/P3/P4/P5/P13/P16 | 星火 8B CS-LoRA | 📌 **保留叙事**。⚠️ **事实已查明**：LoRA 训练**已完成**，基座是 **Qwen2.5-7B**（非星火 / 非 8B）；星火是 MaaS 通道 | **"CS LoRA 微调（Qwen2.5-7B / r16 / 2212 条 / loss 0.67，已交付）+ 星火 MaaS 数据已备（2212 条）"** | 交付包；§0 |
| 2 | P4/P13 | Model Router | 📌 **保留**（自研命名） | 保留名称，**图注挂实现落点**（provider 选择 + 工具策略门 + 检索门面） | `llm_client.py:617-634`；§0 |
| 3 | P6/P13 | Hybrid RAG / 泛称 | 真实为 FTS/BM25 + 本地向量 + RRF(k=60) | 补参数：**词法 30 / 向量 30 / RRF k=60 / top6 / 3000 tokens / 512 维** | `rag/config.json` |
| 4 | P6/P13 | GraphRAG | 默认关闭 | **FTS/BM25 + 本地向量 + pgvector 混合检索** | `config.py:176`；口径文档 §11 |
| 5 | P6 | 全量权威语料 | 代码就绪，**部署与全量向量化未执行** | **"混合检索链路已实现并冻结参数，全量索引待部署"** | 实施计划 §9 |
| 6 | P7 | TeachingAgent 已上线 | 本地端到端验收完成，真实课程+Judge0 冒烟未部署 | **"本地端到端已验收"** | README 能力矩阵 |
| 7 | P8/P10 | Research Loop 7 段 | 真实 stage **6 段**；verifying 恒 not_applicable | 叙事可留 7 步，**日志必须用真实 stage 名** | `worker.py:266` |
| 8 | P8 | 受控执行 3 点 | 实为 4 边界（含**数值阈值判定**） | 补第 4 条：**判定边界 = 数值阈值，不经 LLM** | 技术报告 §2.7 |
| 9 | P9 | （口径文档）Dijkstra"不能处理" | 脚本已改"可能失效" | **以脚本为准，回头同步口径文档 §9** | 本版 §P9 |
| 10 | P10 | 英文示意日志 | 仓库无此日志 | **仅用真实终端输出**；虚构日志属禁令 | 附录 E |
| 11 | P11 | `torch.compile` 案例 | 📌 **保留**，云端导入 PyTorch 文档支撑 | 导入后**必须重建索引**（build → validate → activate），否则命中旧 release | `manage_corpus_index.py` |
| 12 | P11 | Runtime 字段 | 真实字段名是 `time` | **写 `time` / `memory`**（均为真实字段） | `sandbox_client.py:82-93` |
| 13 | P11 | 排序算法 / Ridge 对比实验 | 📌 **保留**，云端补 preset | 需在 `REPRO_PRESETS` 加条目并**真跑一次留 run 记录**（纯 CPU，可行） | `reproduction.py:22-64` |
| 14 | P12 | **50+ Students** | 📌 **保留**（云端已上线）。⚠️ 属**数据真实性**项，"导入资料"不解决 | 写**实际人数**（≥50 才写 "50+"）+ 准备可核验载体 | 附录 F |
| 15 | P13 | HNSW / ANN 索引 | 未建 HNSW，方案为成员过滤精确排序 | 写 **"成员过滤后精确排序"** | 实施计划 §6 CR3 |
| 16 | P14 | 禁写 CPU/Memory quota | **两者真实存在** | **解禁**，附 `config.py:502-508` 出处 | 本版 §P14 |
| 17 | P14 | "网络隔离" | 仅 Repro Worker 有出站白名单 | 限定为 **"Repro Worker 出站白名单（iptables）"** | `refresh-iptables.sh` |
| 18 | P16 | 团队信息 | 仓库无数据 | **必须要求真实填写** | — |

---

# 4. 提交前五方对账清单（把附录 F 变成可勾选项）

对账对象：`PPT 口径 ↔ GitHub 代码 ↔ 线上 Demo ↔ 03-Demo 视频 ↔ 05-作品代码`

## 4.1 模型
- [ ] LoRA 口径统一为 **"Qwen2.5-7B + LoRA r16 / 2212 条 / 417 步收敛至 train_loss 0.67（已交付）"**
- [ ] 星火相关表述限定为 **"星火 MaaS 通道 / 数据已备齐 2212 条 / ServiceID 待回填"**，不写"星火基座"、不写"8B"
- [ ] **全片未出现"微调提升了效果"**（实测 4/8 → 3/8 为下降）
- [ ] "Model Router" 每次出现处**图注已挂实现落点**（provider 选择 + 工具策略门 + 检索门面）
- [ ] 评测数字写为"10 用例中 9 项自动评测通过（9/9 auto），1 项待沙箱补验"（不是笼统的"9/9"）
- [ ] `README.md` 的"训练未执行"已同步修正（仓库 ↔ PPT 一致）

## 4.2 知识
- [ ] 112 节点 / 106 关系 / 10 门课 与 `knowledge_data/` 实测一致
- [ ] 184,435 篇 / 3.32B 字符 / 3.50 GB 与 `corpus/manifest.json` 一致
- [ ] 混合检索参数（512 维 / RRF k=60 / top6 / 3000 tokens）与 `rag/config.json` 一致
- [ ] 未出现 GraphRAG / LanceDB 作为现行路线
- [ ] 未声称"全量语料已接入全部入口"
- [ ] P11 案例一的 PyTorch 文档**已导入并重建索引**（只导入不重建会命中旧 release）

## 4.3 教学
- [ ] TeachingAgent 节点数写 **25**（不是 22）
- [ ] TeachingAgent 状态写"本地端到端已验收"（不是"已上线"）
- [ ] Judge0 字段名与枚举与 `sandbox_client.py` 一致（10 态 / `time` / `memory`）
- [ ] 六维标注"规则基线 V1，BKT/DKT 为研究项"
- [ ] 证据类型 12 类与 `evidence.py` 一致

## 4.4 科研
- [ ] Research Loop 叙事与真实 6 段 stage 不混淆
- [ ] verifying 段显示"不适用"
- [ ] 出现 preset 时只写已核验仓库（nanoGPT；排序算法 preset 若补入，已真跑通）
- [ ] P11 案例三**有真实 run 记录**（只有资料不算"可复现"）
- [ ] 视频中的失败/重试若无法复现，已改为"取消/超时如实保留终态"
- [ ] 未出现"全自动科研"

## 4.5 安全
- [ ] 所有安全机制均可在代码/配置中找到出处
- [ ] 未出现 Seccomp / egress deny / capability drop
- [ ] 网络相关表述限定为"Repro Worker 出站白名单"
- [ ] 所有日志来自真实系统，无手工构造
- [ ] AI 标识与 Citation 在真实 UI 中可见

## 4.6 用户反馈
- [ ] 人数为**云端真实统计值**（写 "50+" 须已确认 ≥50）
- [ ] 反馈载体（班级群 / 课程名单 / 后台使用统计）**可出示**
- [ ] 所有身份真实可核验
- [ ] 班级截图完成脱敏（姓名/账号/头像/学号/手机号）
- [ ] 指导教师评价未包装成独立用户认可

---

# 5. 一句话使用建议

技术细化不是把 PPT 变长，而是**让每个技术名词都能被追问三分钟**。本版所有数字都能在仓库里找到出处。

**技术表述类与数据真实类要分开对待**：云端已上线、资料可导入这个前提，对**技术表述类**（型号、命名、案例）成立 —— 导入资料 + 重建索引 / 补 preset 就能补齐证据；但对**数据真实类**（P12 人数）不成立，它只能靠真实统计闭合。**这一项请优先落实。**

**提交前把第 3 节的 18 条逐条过一遍，比再润色一遍文案有价值得多。**

**关于 LoRA（§0）—— 本版最大的一次事实修正**：训练不仅做了，而且证据链完整（loss CSV 417 点、两次独立运行一致、adapter SHA256、评测如实）。**但正因为证据完整，口径反而必须更严**：能写"收敛 / 可复现 / 风格贴合"，**不能写"效果提升"**。评审看到 loss 曲线与两次一致，会认为你严谨；看到"提升"而实测是 4/8→3/8，会认为你不可信。**有证据的人，最有资格说边界。**

---

*证据基线：2026-09-10 于 `dev-liu` 工作区实测；行号漂移时以类名/函数名检索为准。*
