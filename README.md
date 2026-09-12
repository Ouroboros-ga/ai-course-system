# CodeNexus 智码交响

> **面向计算机学科的垂类大模型与可执行智能体平台**
> 让知识有出处，让代码跑得通，让学习有回响
> 挑战杯"揭榜挂帅" XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》（发榜单位：科大讯飞）
> 对外叙事口径（定位、创新点、可讲/不可讲边界）以 [作品定位与叙事口径](docs/phase1/2026-09-09_CodeNexus_作品定位与叙事口径.md) 为准

---

## 项目简介

CodeNexus 智码交响的定位是**面向计算机学科的垂类大模型与可执行智能体平台**——一句话概括：**让知识有出处，让代码跑得通，让学习有回响**。

它不是"功能很多的 AI 教学平台"，而是四层学科能力栈的协同：**L1 学科模型层**（可插拔基座：现行 DeepSeek `deepseek-chat`，讯飞星火 Provider 已就绪 + CS LoRA/SFT 微调管线）负责术语理解、算法解释与专业教学表达；**L2 权威知识层**（CS 学科语料混合 RAG + 课程知识图谱）负责事实出处与教学结构；**L3 可执行工具层**（Judge0 沙箱、实验沙箱、多格式文档解析）负责真正跑起来；**L4 教育智能层**（TeachingAgent / Nexus / 学习证据）负责教学问答、代码实践、科研实验与认知状态。三者职责严格分离：**模型能力 ≠ 知识库 ≠ 验证工具**——LoRA 解决推理与表达的学科适配，RAG 解决事实的外部约束，代码工具解决答案是否真的可运行。

沿用并保留的课程侧哲学仍是**让课程回应学习**：各科课件与历史文档经来源可追踪的解析形成可信、可用、可追溯的知识结构，教育智能体依据六维认知数据理解学情，据此促学、导学、督学与办学。

系统不是外部教学平台的替代品，也不是通用聊天机器人：它通过外部接口适配接入课程上下文，在内部完成材料解析、证据治理、课程生成、知识包构建、智能体协作、媒体发布与学习证据处理。

端到端主链围绕一门课程建立连续生命周期：

```text
材料进入与版本登记 → 文档解析与质量判定 → 证据片段与教师确认
→ 知识与课程候选生成 → 双门控审核 → 课程发布与回滚
→ 学生学习、实时问答、练习评价 → 学情反馈
```

**设计原则**

- **以课程而非模型为系统边界**：材料、知识、检索、问答、练习、媒体与学习证据都首先归属于课程；模型供应商可替换、检索实现可演进、外部接口可变化，课程权限、版本与证据归属不因此失效。
- **以证据而非流畅度评价生成内容**：生成内容须引用有效材料证据并通过教师审核或明确质量门，证据缺失时保留候选状态或返回失败语义。
- **以版本快照而非原地覆盖管理变化**：材料重解析、课程修改、图谱更新与索引重建均通过不可变快照、激活指针与回滚记录管理。
- **以最小权限和工具自校验约束智能体**：课程访问服务先解析调用者在当前课程中的能力，各工具执行前再次校验课程与角色，高风险动作需教师确认，权限、治理或安全阀不可用时失败关闭。
- **以证据强度区分学习数据用途**：交互信号用于描述过程、正式评分用于支持判断、完整对话用于产品连续体验、智能体审计用于运行追踪，四类数据分别保存、授权与消费。

**三条可追溯链**：内容追溯链（材料→解析运行→DocumentIR→证据→课程发布）、知识追溯链（证据→知识节点→图谱快照→知识包→Citation→问答回答）、学习追溯链（学习事件/评分→学习证据→认知状态→推荐/分析），以课程身份与发布版本为共同连接键。

---

## 三项核心机制

### 证据锚定与教师审核双门控的智课生成

课件经原生解析与 PaddleOCR 融合后形成稳定的 Canonical DocumentIR，证据片段与知识候选必须通过**证据门**（`evidence_refs` 可解析到当前课程有效证据）与**教师审核门**（生成结果以草稿/提案呈现，教师批准后才进入正式课程）才能发布；发布版本不可变且支持回滚。同一机制应用于 AI 出题（生成草案 → 教师批准 → 题库入库）。

关键对象：`SourceMaterialVersion`、`DocumentParseRun`、`DocumentIRVersion`、`DocumentBlock/EvidenceSpan`、`CourseEvidenceRecord`、`PatchProposal`、`CourseRelease`。

### 双层知识体系下的可追溯检索

知识层拆成**两层、各管一件事**：**学科语料库管"知道什么"**（教材与权威资料的原文事实，走原文切块 + 本地 embedding + FTS/BM25 与向量混合检索，结果带 `reference_id` 与出处），**课程知识图谱管"怎么学"**（知识点、前置/从属/支撑/关联关系、学习路径与课程结构）。图谱侧节点锚定课程证据、关系经教师确认、快照发布后不可变；检索侧采用 BM25 稀疏检索 + 本地 BGE 语义向量 + RRF 排名融合，检索结果再经**课程隔离、版本一致与 Citation 闭包三重约束**才允许进入正式回答。索引不可用时失败关闭，不回退到跨课程或未经审核的候选块。

关键对象：`DisciplineCorpusChunk`（学科语料）、`CourseKnowledgeNode`、`GraphSnapshotRecord`、`CourseKnowledgeBundle`、`CourseKnowledgeHead/Activation`、`ActiveBundleCourseRetrievalPort`。向量库基线为 PostgreSQL + pgvector（LanceDB 为历史实现，见 [功能现状审计表](docs/phase1/功能现状审计表.md)）。

### 交互—测评双源证据分层驱动的学情反馈

将交互信号（访问、进度、提问）与正式测评证据（服务端评分、代码实验终态）分域治理：交互信号描述过程与潜在需求、不能单独写成掌握结论；正式证据写入 `LearningEvidenceRecord` 并绑定课程发布版本。系统在课程与知识节点范围内输出六维认知状态 `s(c,k)=⟨perf, conf, confusion, depth, hint, need⟩`，每维有独立样本门槛，不达标保持 `unknown` 并写入原因码；叠加认知衰减、学习轨迹与图谱驱动的学习路径推荐。

关键对象：`LearningEvidenceRecord`、`CognitiveState`、`cognitive_decay_service`、`LearningTrajectoryRecord`、`learning_path_service`、`derive_question_inference_signals`。

---

## 系统总体方案与架构

### 分层架构

| 架构层 | 承载内容 | 核心对象 |
| --- | --- | --- |
| 平台接入与应用交互层 | 泛雅兼容接口、教师端与学生端页面 | Vue 3 前端、`/api/v1/compat` 适配 |
| 课程业务与发布层 | 课程草稿、材料版本、质量门、发布与回滚 | `CourseBuildDraft`、`CourseRelease` |
| 智能体协作层 | 产品智能体、内部代码能力与兼容层、工具治理 | `edu/`、`prep/`、`research/` + legacy `coding/` |
| 课程知识与证据层 | DocumentIR、证据、图谱、知识包、索引 | `GraphSnapshot`、`CourseKnowledgeBundle` |
| 基础设施与外部能力层 | LLM（含星火垂类 Provider）、OCR、数据库、对象存储、沙箱 | PostgreSQL + pgvector、Judge0 |

### 多智能体协作

备课、教学与科研智能体状态独立，通过受控 Port 与统一治理层协作，不共享跨课程可变状态。协作媒介不是自然语言消息，而是课程发布、知识包、提案、证据记录与受控 Port。五种统一约束：课程权限、证据、版本、工具治理、数据域。

| 智能体 | 核心职责 | 正式写入边界 |
| --- | --- | --- |
| Prep Agent | 备课提案生成（初始 + 增量） | 经教师审核后写入课程草稿 |
| TeachingAgent | 教学问答、对话式代码挑战与受控教学动作 | 回答后非阻塞写对话域；代码运行由服务端聚合证据 |
| ResearchAgent | 科研检索与补充证据 | 外部结果仅补充参考，进正式课程需教师审核 |

关键机制：LangGraph 显式工作流（节点边界即权限边界，TeachingAgent 25 节点）、per-tool policy check（治理异常时 fail-closed 默认禁用）、ScopeValidator 强制课程/学生/成员/能力校验。

### AI 安全围栏

安全围栏贯穿三个层面：**智能体安全围栏**（课程类型安全收敛、政治敏感两级审查、平台级屏蔽词配置、工具 fail-closed）、**沙箱安全围栏**（Judge0 独立实验服务器物理隔离、命令黑名单、认证边界）、**数据安全围栏**（四域分离、对象标识签名访问、Course Access v1 唯一授权入口、密钥不进前端/仓库/日志/文档）。

---

## 核心能力矩阵

> 状态口径：✅ 已部署（进入远端运行环境并形成业务入口或服务调用链）｜🧪 已实现或 Demo 可运行（可运行但默认关闭或需显式配置）｜📋 规划中/未实现

### 课程建设（教师端）

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 课程创建、资料上传、课程生命周期（发布/下架/回滚） | ✅ | `document.py`、`course_build_service.py`、`course_release_service` |
| 文档解析（PPT/PDF/DOCX → Canonical DocumentIR → 内容块/证据锚点） | ✅ | 原生解析 + LibreOffice/Poppler + PaddleOCR；三态质量判定 |
| 证据片段与教师确认、结构化讲稿生成 | ✅ | EvidenceSpan 候选 → 教师确认；Prep Agent + PatchProposal 审核闸门 |
| PPT 页面 ↔ 知识点映射 | ✅ | `mapping.py` + LLM 语义匹配 |
| 课程知识图谱（8 种教育关系） | 🧪 | Worker 已部署、BGE 已接通；真实课程构图默认关闭（`GRAPHRAG_ENABLED=false`）；**管"怎么学"，事实检索另走学科语料 RAG** |
| AI 出题双门控审核 | ✅ | 生成草案 → 教师批准 → 题库入库 |
| 教师生产工作台、脚本快照/版本/回滚 | ✅ | `/app/course/:courseId/build` |

### 媒体与讲授

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 课程级批量媒体（MediaBuildBatch → MediaReleaseItem） | ✅ | 只读计划 → 教师一次确认 → 批量构建 |
| 不可变播放清单（`audio-playlist/v1`、`ppt-manifest/v1`） | ✅ | 发布快照固定 `release_id + playlist_content_hash` |
| 数字人（PixiJS 2D 角色） | 🚫 已移除 | XH-202620 决策：仅保留 TTS + PPT + 字幕 |
| 真实 TTS（豆包） | 🧪 | `MEDIA_DEMO_MODE=false` + `STAGE8_TTS_PROVIDER=doubao` 显式配置 |
| OSS/S3 对象存储、上传 confirm 校验 | ✅ | Local PUT / S3-OSS presigned POST 双链路 |

### 学生学习

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 选课、分屏/统一学习工作台 | ✅ | `/app/course/:courseId/learn` |
| 学习事件链与进度续接 | ✅ | 事件 → 投影 → 学生状态/教师统计 |
| 六维认知状态 + 掌握度（规则基线 V1） | ✅ | `rule_baseline.py` 为真实实现；BKT/DKT/IRT 仅接口定义 |
| 认知推荐 | ✅ | `cognitive_recommendation.py` |
| 课程内问答（TeachingAgent 受控问答） | ✅ | 上下文锚定课程+发布版本+节点，Citation 验证，Conversation 域独立持久化 |
| TeachingAgent 对话式代码挑战 | 🧪 | 本地端到端验收完成；真实课程 + 真实 Judge0 冒烟未部署 |
| 练习/测验、前置知识跳转补学 | ✅ | `question_bank.py`、`prerequisite.py` |

### 代码实验（CS 垂类）

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 代码沙箱执行（Judge0，独立实验服务器） | 🧪 | 客户端完整；`JUDGE0_ENABLED=False` 默认关闭；云端 Demo 已接入独立 Judge0 |
| 平台实验室、算法实验 | ✅ | 教师可按课程启用；未启用沙箱时返回 `CODING_SANDBOX_DISABLED` |
| 算法可视化（JSAV，11 种白名单算法） | ✅ | 学生可播 published 计划，教师可创建/发布 |
| TeachingAgent 内部代码反馈 | ✅ | `edu/coding` 只在本次 run 授权范围内短暂读取源码并返回白名单反馈 |

### 助研（ResearchAgent）与平台管理

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| ResearchAgent HarnessEngineer | ✅ | 真实条件路由 LangGraph；动态 Prompt/Tool/Context/压缩 |
| 学科知识库检索页 `/app/discipline-knowledge` | ✅ | CS 垂类只读检索（权威来源/图邻居/概览） |
| 工作区持久化与向量记忆 | ✅ | PostgreSQL 16 + pgvector；embedding 不可用时降级关键词 |
| arXiv 论文元数据检索 + 来源核验 | ✅ | 节流 + 缓存 + PII 脱敏 + EvidenceGate |
| 趋势分析、证据综合、学术写作、代码复现 | 🧪 | 学术写作与趋势分析已实现；证据综合/代码复现仍 preview |
| Nexus 受控实验（F1–F5：目标判定/持久恢复/操作中断/自动准备/冻结配方） | ✅ | 线上验证；真构建器 daemon 待部署，自主路径干净 B 重放缺线上实证 |
| Nexus 正式文档（F6：同一冻结快照 Word/LaTeX/Markdown） | ✅ | 线上验证；PDF 待 TeX 工具链（fail-closed 如实失败） |
| Nexus 持续研究（F7：任务/预算/证据/受限 researcher） | ✅ | 线上验证；Ask 综述＋Word 组合流已用主对话 Key 闭环 |
| Nexus 受控对照（F8：共同条件＋冻结配方＋描述性并列） | 🧪 | 对照 API＋对话工具＋客户端已上线；工作台展示未做 |
| 实验工作台配方身份（F9） | 🧪 | 前端已就绪；待后端合并透传修复上线（审计已知缺口） |
| 平台管理员（用户/角色/Provider 配置/任务并发） | ✅ | `/app/admin`（shadow） |
| 泛雅·超星 AI 兼容适配层 | ✅ | 签名校验/字段转换/权限解析/能力降级 |

### 规划中（未实现）

| 功能 | 说明 |
| --- | --- |
| 学科垂类模型微调（LoRA/SFT） | 可复现管线已交付（数据集/评测基准/训练脚本）；**训练未执行**（无 GPU，诚实标注） |
| CS 学科知识库内容填充 | `knowledge_data/` 已填充并接入只读检索；图谱/检索白名单深度接线为后续项 |
| 星火 LLM 深度接入 | Provider 已接入；真实 Key 手工验收待进行 |
| RE-KT 证据驱动学生模型 | 研究推进中 |

---

## 技术栈与运行环境

### 后端

| 项 | 版本/选型 |
| --- | --- |
| 语言/框架 | Python + FastAPI + Uvicorn |
| ORM/迁移 | SQLModel + Alembic |
| 智能体 | LangGraph + 自研 Port/Provider 契约 |
| 文档解析 | Docling、LibreOffice、Poppler、PaddleOCR（容器） |
| 向量/检索 | PostgreSQL + pgvector、本地 BGE 嵌入、FTS/BM25 混合检索；课程图谱 Worker（默认关闭态） |
| 代码沙箱 | Judge0（独立实验服务器，客户端默认关闭） |
| 外部服务 | DeepSeek LLM（默认基座）、讯飞星火（可选）、豆包 TTS、讯飞 PPT、arXiv |
| 数据库 | 云端 PostgreSQL 16 + pgvector（基线）；本地开发 SQLite |

### 前端

| 项 | 版本/选型 |
| --- | --- |
| 框架 | Vue 3.5 + Vite + Pinia + vue-router |
| 渲染 | PixiJS、Chart.js、KaTeX、marked |
| 双前端 | legacy 路由（`/`）+ shadow 前端（`/app/**`，`VITE_ENABLE_SHADOW_FRONTEND` 默认开） |

### 运行环境

- Node ≥ 20.19（前端）；Python 3.11+（后端，uv 管理）
- 生产部署：Ubuntu 22.04 + systemd + Nginx + Docker Compose（`deploy/`）
- 服务器资源边界：主服务器 4 核 / 8 GB（云端 Demo），OCR/GraphRAG/Judge0 压测须串行

---

## 目录结构概览

```text
ai-course-system/
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/endpoints/    # 公开路由（权威来源）
│   │   ├── platform/            # 智能体(agents)、知识库(knowledge)、证据(evidence)、检索(retrieval)
│   │   ├── services/            # 业务服务
│   │   ├── domain/              # 领域逻辑
│   │   ├── models/              # ORM 模型
│   │   └── external_apis/       # 泛雅·超星 AI 兼容适配层
│   ├── alembic/                 # 数据库迁移（75 版）
│   ├── finetune/                # XH-202620 微调管线
│   └── tests/                   # 测试套件（235 个测试文件）
├── nexus/                       # Nexus Runtime（独立 Python 项目，课程外全局入口）
├── frontend/                    # Vue 3 前端（183 个 .vue 组件）
├── docs/                        # 文档（DOCUMENTATION_INDEX.md 为入口）
│   ├── phase1/                  # 现行实施基线、审计与契约
│   ├── refactor/                # 历史重构记录（仅追溯）
│   └── frontend-design/         # 页面设计与前端契约
├── competition/                 # XH-202620 参赛材料 01–07
├── deploy/                      # Docker Compose、systemd、nginx、judge0、paddleocr
├── knowledge_data/              # CS 学科知识库（112 节点/106 关系，11 门课）
├── scripts/                     # 运维/演示脚本
└── database/                    # 本地 SQLite 开发库
```

---

## 快速开始

### 后端启动

```bash
cd backend
uv sync
uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API 文档：<http://localhost:8000/docs>
- 数据库迁移：`uv run alembic upgrade head`

### 前端启动

```bash
cd frontend
npm install
npm run dev   # 默认端口 5300
```

- 访问 <http://localhost:5300>，shadow 前端入口为 `/app/**`

### 环境配置

```bash
cd backend
cp .env.example .env   # 按 config.py 默认值 + 生产 .env 填写
```

关键开关（缺省均为安全默认）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `deepseek` | 外部 LLM；可选 `doubao`/`qwen`/`openai`/`spark`；未配置 Key 时相关能力 fail-closed |
| `MEDIA_DEMO_MODE` | `true` | 媒体建设用 Fake WAV，不调用付费 TTS |
| `JUDGE0_ENABLED` | `false` | Judge0 沙箱默认关闭 |
| `GRAPHRAG_ENABLED` | `false` | GraphRAG 构图默认关闭 |
| `VITE_ENABLE_SHADOW_FRONTEND` | `true` | 前端 shadow 入口 |

### 运行测试

```bash
# 后端
cd backend && uv run pytest -q
# 前端
cd frontend && npm run test:unit && npm run build && npm run smoke:app
```

---

## 云端部署与验证状态

系统已完成云服务器部署，作为正式展示与功能验收环境。该环境不代表已获准处理真实生产学生数据，也不代表已达到互联网规模生产系统的全部运维要求。

### 部署拓扑

| 组件 | 运行状态 | 部署事实 |
| --- | --- | --- |
| Nginx | systemd 服务 | 统一入口；提供前端静态资源并转发 API 请求 |
| CodeNexus Backend | systemd 服务 | Uvicorn 监听 127.0.0.1:8000 |
| PostgreSQL | Docker 容器 | postgres:16.14 + pgvector 0.7.4，仅绑定回环地址 |
| PaddleOCR | Docker 容器 | 独立 OCR 服务，仅绑定 127.0.0.1:8090 |
| Judge0 | 独立实验服务器（Docker 容器） | API Server、Worker、PostgreSQL、Redis；仅对内网后端开放 |

### 端到端验证

以下核心场景已在云端环境完成端到端走通验证：课程材料上传解析、证据审核与发布、知识包构建与激活、跨课程隔离、学生实时问答、代码沙箱运行、题目草稿审核、学习调整与续学、学情分析、泛雅兼容问答。验证结果用于证明功能链路完整可用，不代表教学效果或性能达标。

公网入口：`https://zsitai.xyz`（SSH 管理地址 `103.36.223.177`）。旧地址 `http://47.99.97.154/` 已随原服务器退租失效。

---

## 文档与规划索引

**正式项目文档**

- [docs/DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md)：文档导航与状态（唯一入口）
- [AGENTS.md](AGENTS.md)：开发与安全规则（最高优先级）
- [competition/05-作品代码/技术报告.md](competition/05-作品代码/技术报告.md)：参赛技术报告（按赛题组织）
- [design.md](design.md)：前端视觉令牌/组件规范（改前端前必读）
- [docs/RUN.md](docs/RUN.md)：最小启动说明

**现行实施文档**

| 文档 | 用途 |
| --- | --- |
| [docs/phase1/功能现状审计表.md](docs/phase1/功能现状审计表.md) | 当前代码审计结论与已知缺口 |
| [docs/phase1/2026-08-20_XH202620差距分析与产品定位.md](docs/phase1/2026-08-20_XH202620差距分析与产品定位.md) | 挑战杯现行定位与路线图 |
| [docs/phase1/统一课程建设与解析基线.md](docs/phase1/统一课程建设与解析基线.md) | 统一上传、解析、RAG、讲稿与 PPT 映射目标 |
| [docs/phase1/路由契约基线.md](docs/phase1/路由契约基线.md) | API 契约基线 |
| [docs/phase1/实验室代码沙箱可信评测契约.md](docs/phase1/实验室代码沙箱可信评测契约.md) | 代码实验与可信记录边界 |

**开发中 / 规划能力**（不构成已实现依据，详见对应 `docs/phase1/` 文档）

- CodeNexus 转型与 Nexus AI 全局入口（建设中）：[CodeNexus_转型设计与实施方案_v1.3](docs/phase1/CodeNexus_转型设计与实施方案_v1.3.md)、[CodeNexus_P2开发计划](docs/phase1/CodeNexus_P2开发计划.md)
- CS 语料向量化与 RAG 上线（NEXT）：[2026-09-08_CS语料向量化与RAG上线实施计划](docs/phase1/2026-09-08_CS语料向量化与RAG上线实施计划.md)
- Nexus 自主实验与持续研究任务书：[Nexus_自主实验V1_执行任务书](docs/phase1/Nexus_自主实验V1_执行任务书.md)、[Nexus_持续研究V1_开源集成与开发任务书](docs/phase1/Nexus_持续研究V1_开源集成与开发任务书.md)
- Nexus 功能补齐（2026-09-09，NEXT）：[原设计功能补齐与开源集成实施计划](docs/phase1/2026-09-09_Nexus功能补齐与开源集成实施计划.md)。基础主干已接通，但持续恢复、操作级中断、自动准备、冻结复现、正式多格式输出及完整研究仍需补齐；采用成熟开源核心与薄适配，不以旧局部交付替代完整产品要求。

---

## 参赛信息

- **赛题**：挑战杯"揭榜挂帅"擂台赛 XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》（发榜单位：科大讯飞股份有限公司）
- **作品形态**：计算机学科垂类大模型（基座 + 学科知识库 + 领域微调管线）与助教 / 助学 / 助研智能体应用集
- **平台代号**：CodeNexus（智码交响）
- **项目基线**：`dev-liu`（`feature/xh202620` 已于 2026-09-03 合并回主线）
- 参赛材料见 `competition/`（01–07），打包前运行 `python competition/preflight.py`

---

*本 README 的功能状态均可回溯至代码证据。*
