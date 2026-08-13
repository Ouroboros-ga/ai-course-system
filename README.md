# AI 互动智课系统（ai-course-system）

> **2026-08-11 数据库迁移状态**：服务器运行库已切换到独立 PostgreSQL 16。Alembic `0052`、可审计 SQLite 快照迁移工具和 `deploy/postgres/` 是当前基线；最终快照的 162 张表、89,561 行已完成摘要/外键校验。迁移会原样保留历史 `media_release_items → script_nodes` 失效引用，并要求目标侧逐关系数量与源快照一致；该一项外键在 PostgreSQL 中为 `NOT VALID`，新写入仍被校验。`0049/0050` 中遗留的小写枚举标签只用于兼容历史类型，`0051/0052` 补齐并归一化为 SQLAlchemy 实际持久化/读取的大写成员名：`evidence_render_assets.asset_type`、`source_material_versions.parse_status` 和 `source_materials.status` 不得保留小写活跃值，其他枚举仍 fail-closed。实施入口见 [deploy/postgres/README.md](deploy/postgres/README.md) 与 [SQLite 到 PostgreSQL 迁移基线](docs/phase1/2026-08-11_SQLite到PostgreSQL迁移与服务器切换.md)。
>
> 历史 `deploy/DEMO部署说明.md` 中“生产 MySQL”描述已废弃，不可作为部署依据。

> **面向高校课程的证据驱动型智能教学平台** —— 把静态课件建设为"可解析、可讲授、可互动、可追踪"的课程闭环，并承载挑战杯 XH-202620"学科垂类大模型与创新应用"的计算机学科延伸方向（助教 / 助学 / 助研）。
>
> 当前定位：**本地原型 Demo**。真实实现以代码、注册路由、数据库迁移、契约测试和浏览器手工行为为准；规划文档不能替代可运行证据。详见 [docs/DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md)。

> **2026-08-13 代码实验状态**：正式评测已收敛为持久化异步任务和 ACM/ICPC 0/1 评分；自由运行保持非计分 Beta。实验室记录只从服务端终结尝试投影，旧 `POST /lab/{lab_id}/records` 与学生成绩提交入口已下线。现行边界、灰度限制和未完成的真实环境验收见 [实验室-代码沙箱可信评测契约](docs/phase1/实验室代码沙箱可信评测契约.md)。

---

## 目录

1. [项目简介与设计目标](#1-项目简介与设计目标)
2. [核心功能特性（含实现状态）](#2-核心功能特性含实现状态)
3. [技术栈与运行环境](#3-技术栈与运行环境)
4. [目录结构概览](#4-目录结构概览)
5. [快速开始指南](#5-快速开始指南)
6. [常用开发与部署命令](#6-常用开发与部署命令)
7. [文档与规划索引](#7-文档与规划索引)

---

## 1. 项目简介与设计目标

系统将教师已有教学资料（PPT/PDF/Word/教案/题目）转化为一条可编辑、可播放、可互动、可回看学习状态的课程链路：

```text
课程资料 → 统一上传与版本化对象存储 → 解析任务 / DocumentIR / Evidence
→ 可信检索、课程图谱与教学结构 → 教师审核、编辑与发布
→ 学生学习、练习、代码实验、TeachingAgent 问答与课程媒体播放
```

**设计目标：**

- **证据驱动、内容可追溯**：讲稿、问答、诊断回链 Evidence 原文锚点，拒绝无依据断言；
- **教师审核闸门**：备课 PatchProposal、出题草稿、媒体发布均需教师确认，fail-closed；
- **数据最小化三域分离**：Agent Runtime/Audit、Conversation、学习分析三域隔离，隐私合规；
- **可降级、可回滚**：外部 LLM/TTS/OCR/Judge0/GraphRAG 全部经独立适配层或任务服务接入，缺失配置即明确降级或拒绝，不伪造成功。

**赛题延伸（挑战杯 XH-202620）**：在通用教学闭环之上，面向计算机学科扩展知识库、代码实验、算法可视化与助研（ResearchAgent）能力。其中**模型微调（LoRA/SFT）与 CS 学科知识库内容填充为规划项，尚未实现**，详见 [探索结果摘要与差距分析](../代码库探索结果摘要与差距分析.md)。

---

## 2. 核心功能特性（含实现状态）

> 状态口径：✅ 已实现（有代码/路由/测试证据） ｜ 🧪 测试或 Demo 阶段（可运行但默认关闭或需显式配置） ｜ 📋 规划中/未实现 ｜ ⚠️ 接口已定义实现待填充

### 2.1 课程建设（教师端）

| 功能 | 状态 | 说明 |
|---|---|---|
| 课程创建、资料上传（≤100MB）、课程生命周期（发布/下架/回滚） | ✅ | `document.py`、`course_build_service.py`、`course_release_service` |
| 文档解析（PPT/PDF/DOCX → Markdown → 结构化） | ✅ | Docling + LibreOffice/Poppler + PaddleOCR（本地真实链路） |
| 结构化讲稿生成（开场白/讲解/过渡语） | ✅ | Prep Agent + 有界 Map/Reduce + PatchProposal 审核闸门；单节点优化返回待审核提案，批量一键优化才直接应用，教师界面只显示节点/字段摘要 |
| PPT 页面 ↔ 知识点映射 | ✅ | `mapping.py` + LLM 语义匹配 |
| 课程知识图谱（GraphRAG，8 种教育关系） | 🧪 | Worker 已部署、LanceDB/BGE 已接通；真实课程构图因**数据外发授权未获批**默认关闭（`GRAPHRAG_ENABLED=false`） |
| 教师 8 步生产工作台、脚本快照/版本/回滚 | ✅ | shadow 前端 `/app/course/:courseId/build` |

### 2.2 媒体与数字人讲授（Stage 8）

| 功能 | 状态 | 说明 |
|---|---|---|
| 课程级批量媒体（MediaBuildBatch → MediaReleaseItem） | ✅ | 只读计划 → 教师一次确认 → 批量构建 |
| 不可变播放清单（`audio-playlist/v1`、`ppt-manifest/v1`、字幕、`avatar-cues/v1`） | ✅ | 发布快照固定 `release_id + playlist_content_hash`；PPT manifest 使用后台 `media.ppt_manifest`，复用映射页图并仅补渲染缺页 |
| PixiJS 2D 数字人（平台注册角色） | ✅ | 默认 `platform-female-instructor-v1@1.0.0`（虚构女性讲师，非真实肖像）；按音频时钟驱动 |
| 真实 TTS（豆包） | 🧪 | `MEDIA_DEMO_MODE=false` + `STAGE8_TTS_PROVIDER=doubao` 显式配置；已通过一次受控 POC（`phonemes` 为空，不承诺精确口型） |
| OSS/S3 对象存储、上传 confirm 校验 | ✅ | Local PUT / S3-OSS presigned POST 双链路 |
| 旧 `/video-gen` 数字人视频链 | 🚫 | 仅历史兼容，带弃用响应与 Sunset |

### 2.3 学生学习

| 功能 | 状态 | 说明 |
|---|---|---|
| 选课、分屏/统一学习工作台（大纲+媒体+助手+笔记） | ✅ | `/app/course/:courseId/learn`；legacy `StudentPlayer` 保留 |
| 学习事件链（`learning_events`）与进度续接 | ✅ | 事件 → 投影 → 学生状态/教师统计；失败事件浏览器待发队列 |
| 六维认知状态 + 掌握度（规则基线） | ✅ | `rule_baseline.py` 为真实实现；**BKT/DKT/IRT 仅接口定义** |
| 认知推荐 | ✅ | `cognitive_recommendation.py` + `recommendation_consumed` 事件 |
| 课程内问答（TeachingAgent 六段工作流） | ✅ | 上下文锚定 `course_id+release_id+outline_node_id`，证据引用，Conversation 域独立持久化（默认 90 天保留） |
| TeachingAgent 受控回顾与进度续接 | 🧪 | 已实现本地 P0：提问位置、冻结回顾目标和点击时返回锚点三者分离；回顾须由学习者确认，且不会写入掌握度。跨媒体项、浏览器 seek 失败和主动返回仍待非生产人工验收。 |
| 练习/测验、前置知识跳转补学 | ✅ | `question_bank.py`、`prerequisite.py` |

### 2.4 代码实验（CS 垂类）

| 功能 | 状态 | 说明 |
|---|---|---|
| 代码沙箱执行（Judge0） | 🧪 | 客户端完整（多语言/状态映射/降级），`JUDGE0_ENABLED=False` **默认禁用**（共用主机权限受限） |
| 平台实验室（Labs）、算法实验（Experiments） | ✅ | 当前仅支持代码沙箱；教师可按课程启用，关闭时师生不显示“实验任务”，未启用沙箱时执行返回 `CODING_SANDBOX_DISABLED` |
| 算法可视化（JSAV，11 种白名单算法） | ✅ | legacy `VisualizationView` + JSAVPlayer；学生可播 published 计划，教师可创建/发布计划 |
| CodingEduAgent 代码诊断 | ✅ | 三节点工作流（沙箱结果→诊断→响应） |

### 2.5 助研（ResearchAgent）与平台管理

| 功能 | 状态 | 说明 |
|---|---|---|
| ResearchAgent HarnessEngineer | ✅ | 真实条件路由 LangGraph；动态 Prompt/Tool/Context/压缩；25s 超时与并发 8 |
| 科研工作台 `/app/course/:courseId/research` | ✅ | 论文、Todo、Notepad、Memory、Scope 五个可操作视图；`course.view` 可见、执行另行授权 |
| 工作区持久化与向量记忆 | ✅ | Alembic `0053`；已验证 PostgreSQL 16.14 + pgvector 0.7.4，向前兼容 PostgreSQL 18；embedding 或 vector 查询不可用时明确降级关键词 |
| arXiv 论文元数据检索 + 来源核验 | ✅ | 真实接通（节流 3s + 24h 缓存 + PII 脱敏 + EvidenceGate） |
| 趋势分析、证据综合、学术写作、代码复现 | 🧪 | 页面按 `research_preview` 展示，未伪装完成 |
| Semantic Scholar / OpenAlex / Crossref、全文解析、GitHub 仓库复现 | 📋 | 规划中 |
| 平台管理员（用户/角色/Provider 配置/任务并发） | ✅ | `/app/admin`（shadow）、`admin_platform.py` |
| 泛雅·超星 AI 参考兼容层 | ✅ | `external_apis/fanya_chaoxing_ai/`，可整体移除 |

### 2.6 规划中（挑战杯赛题扩展，未实现）

| 功能 | 说明 |
|---|---|
| 学科垂类模型微调（LoRA/SFT） | 无训练代码；星辰 MaaS / 本地 LoRA 均为规划路线 |
| CS 学科知识库内容填充 | `knowledge_data/` 三个 JSON 为空占位 |
| 星火 X1 深度推理接入 | 仅 PPT 生成使用星火；LLM 默认豆包 |
| 代码项目交流平台（类 CSDN） | 无实现 |

---

## 3. 技术栈与运行环境

### 3.1 后端

| 项 | 版本/选型 |
|---|---|
| 语言/框架 | Python + FastAPI（≥0.135）+ Uvicorn |
| ORM/迁移 | SQLModel（≥0.0.37）+ Alembic（当前 head `0053`） |
| 智能体 | LangGraph（0.6.x）+ 自研 Port/Provider 契约 |
| 文档解析 | Docling（≥2.81）、LibreOffice、Poppler、PaddleOCR（容器） |
| 向量/图谱 | LanceDB 0.34、本地 BGE 嵌入、GraphRAG 3.1.1（独立 Worker，关闭态） |
| 代码沙箱 | Judge0（客户端就绪，默认关闭） |
| 外部服务 | 豆包 LLM（默认）、豆包 TTS（Demo/显式）、讯飞 PPT、arXiv |
| 数据库 | 当前本地 SQLite；ResearchAgent 已验证 PostgreSQL 16.14 + pgvector 0.7.4，并保持 PostgreSQL 18 前向兼容；对象存储 Local/S3/OSS 适配 |

### 3.2 前端

| 项 | 版本/选型 |
|---|---|
| 框架 | Vue 3.5 + Vite 7 + Pinia + vue-router 5 |
| 渲染 | PixiJS 8.16（Sprite2D 数字人）、Chart.js、KaTeX、marked |
| 双前端 | legacy 路由（/）+ shadow 前端（`/app/**`，`VITE_ENABLE_SHADOW_FRONTEND` 默认开） |

### 3.3 运行环境

- Node ≥ 20.19（前端）；Python 3.11+（后端，uv 管理，`uv.lock`/`pyproject.toml`）
- 生产部署：Ubuntu 22.04 + systemd（`smartcarb-backend.service`，2 workers）+ Nginx（`smartcarb-nginx.conf`）+ Docker Compose（`deploy/`）
- 服务器资源边界：7.1 GiB 内存无 swap，OCR/GraphRAG/Judge0 压测须串行

---

## 4. 目录结构概览

```text
ai-course-system/
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/endpoints/    # 63 组路由、64 个端点模块（公开 API 权威来源）
│   │   ├── platform/            # 智能体(agents)、知识库(knowledge)、证据(evidence)、
│   │   │                        # 文档智能(document_intelligence)、适配器(adapters)、mastery
│   │   ├── services/            # 66 个业务服务
│   │   ├── domain/              # learning / safety / student_memory / education_graph / knowledge_bundle
│   │   ├── models/              # 42 个 ORM 模型
│   │   └── external_apis/       # 泛雅·超星 AI 参考兼容包
│   ├── alembic/                 # 45 个迁移版本
│   └── tests/                   # 105 个测试文件（pytest）
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── router/              # legacy 路由（23 条具名）
│   │   ├── app/                 # shadow 前端（/app/** 43 条：建课/学习/研究/管理）
│   │   ├── api/                 # 40 个 API 客户端
│   │   ├── views/               # legacy 视图（播放器/可视化/检索 Demo…）
│   │   ├── features/            # 特征模块（student-learning / graph-browser / evidence-viewer…）
│   │   └── components/          # 组件（chat / visualization / graphrag / cognitive…）
│   └── package.json             # dev/build/test:unit/lint/smoke:app
├── docs/                        # 文档（DOCUMENTATION_INDEX.md 为入口）
│   ├── phase1/                  # 现行实施基线、审计与契约（37 篇）
│   ├── refactor/                # 历史重构/Shadow/迁移记录（仅追溯）
│   └── frontend-design/         # 页面设计与前端契约
├── deploy/                      # Docker Compose、Dockerfile.backend、nginx、judge0、paddleocr
├── database/                    # SQLite 生产库 + 备份
├── knowledge_data/              # CS 学科知识库（当前为空占位）
├── scripts/                     # dev-stack.sh（PaddleOCR + 后端一键启动）等
├── research/                    # 离线研究沙箱（不构成生产结论）
└── test/ tests/                 # 测试资产与基准
```

---

## 5. 快速开始指南

### 5.1 后端启动

```bash
cd backend
uv sync                 # 按 uv.lock 安装依赖（或 uv run 自动处理）
uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API 文档：http://localhost:8000/docs
- 数据库迁移（如需要）：`uv run alembic upgrade head`
- 一键开发栈（PaddleOCR 容器 + 后端）：`./scripts/dev-stack.sh`（Linux/macOS）

### 5.2 前端启动

```bash
cd frontend
npm install             # 或 pnpm install（仓库含 pnpm-lock.yaml）
npm run dev             # 默认端口 5300
```

- 访问 http://localhost:5300（终端按 `o` 打开浏览器）
- shadow 前端默认开启（`VITE_ENABLE_SHADOW_FRONTEND=true`），入口为 `/app/**`

### 5.3 环境配置

```bash
cd backend
cp .env.example .env     # 若有模板；否则按 config.py 默认值 + 生产 .env 填写
```

关键开关（缺省均为安全默认）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `doubao` | 外部 LLM；未配置 Key 时相关能力 fail-closed |
| `MEDIA_DEMO_MODE` | `true` | 媒体建设用 Fake WAV，页面显示 `fake-demo`，不调用付费 TTS |
| `STAGE8_TTS_PROVIDER` | — | 正式 TTS 需 `MEDIA_DEMO_MODE=false` + `doubao` |
| `JUDGE0_ENABLED` | `false` | Judge0 沙箱默认关闭 |
| `GRAPHRAG_ENABLED` | `false` | GraphRAG 构图默认关闭（等待数据外发授权） |
| `VITE_ENABLE_SHADOW_FRONTEND` | `true` | 前端 shadow 入口 |

### 5.4 运行测试

```bash
# 后端（pytest.ini 已配置 pythonpath=backend、testpaths=backend/tests）
cd backend
uv run pytest -q

# 前端单元测试（node --test 定向）
cd frontend
npm run test:unit

# 前端生产构建 + 应用冒烟
npm run build
npm run smoke:app
```

> 测试基线示例：媒体发布/播放定向回归 53 passed、前端学习/媒体单测 40 passed（2026-08-10 记录）。所有自动化均为 Fake/Mock/本地数据，不调用真实付费服务。

---

## 6. 常用开发与部署命令

### 6.1 常用命令速查

| 操作 | 命令 |
|---|---|
| 后端开发启动 | `cd backend && uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` |
| 后端单测 | `cd backend && uv run pytest -q` |
| 数据库迁移 | `cd backend && uv run alembic upgrade head`（PostgreSQL `0049–0052` 为前向枚举迁移；故障按备份/服务环境恢复或前向修复，勿执行 `downgrade -1`） |
| 前端开发 | `cd frontend && npm run dev` |
| 前端构建 | `cd frontend && npm run build` |
| 前端单测 | `cd frontend && npm run test:unit` |
| 前端 lint | `cd frontend && npm run lint` |
| 应用冒烟 | `cd frontend && npm run smoke:app` |
| 一键开发栈 | `./scripts/dev-stack.sh [--skip-backend|--skip-ocr]` |

### 6.2 部署（Ubuntu）

```bash
# 后端 systemd 服务（工作目录 /opt/smartcarb/backend，uvicorn 0.0.0.0:8000，2 workers）
# 前端 Nginx：SPA 回退 + /api/ 反代 127.0.0.1:8000（60m body、600s 超时）
# 完整部署说明见 deploy/DEMO部署说明.md 与 docs/phase1/2026-08-09_服务器环境一致性与外部链路审计.md
```

历史部署脚本（根目录 `deploy_*.sh`、`verify_*.sh` 等）为 2026-08 现场排障产物，仅供参考。

---

## 7. 文档与规划索引

### 7.1 现行文档（优先阅读）

| 文档 | 用途 |
|---|---|
| [docs/DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md) | 文档导航与状态（唯一入口） |
| [AGENTS.md](AGENTS.md) | 开发与安全规则（最高优先级） |
| [docs/phase1/功能现状审计表.md](docs/phase1/功能现状审计表.md) | 当前代码审计结论与已知缺口 |
| [docs/phase1/服务器环境一致性与外部链路审计.md](docs/phase1/2026-08-09_服务器环境一致性与外部链路审计.md) | 2026-08-09 Ubuntu 实际环境与外部链路基线 |
| [docs/phase1/统一课程建设与解析基线.md](docs/phase1/统一课程建设与解析基线.md) | 统一上传、解析、RAG、讲稿与 PPT 映射目标 |
| [docs/phase1/阶段8_媒体TTS数字人PPT_实施规划.md](docs/phase1/阶段8_媒体TTS数字人PPT_实施规划.md) | 媒体与数字人现行基线 |
| [docs/phase1/研究智能体整体架构与前端设计.md](docs/phase1/研究智能体整体架构与前端设计.md) | ResearchAgent 架构与上线门 |
| [docs/phase1/路由契约基线.md](docs/phase1/路由契约基线.md) | API 契约基线 |
| [docs/RUN.md](docs/RUN.md) | 最小启动说明 |
| [设计指南](design.md) | 前端视觉令牌/组件规范（改前端前必读） |

### 7.2 规划与差距分析

| 文档 | 性质 | 状态标注 |
|---|---|---|
| [代码库探索结果摘要与差距分析](../代码库探索结果摘要与差距分析.md) | 2026-08-11 探索基线 | 现行 |
| [文档更新清单](../文档更新清单.md) | 旧文档状态与更新原因 | 现行 |
| [挑战杯揭榜挂帅_文档规划方案](../挑战杯揭榜挂帅_文档规划方案.md) | 比赛文档规划（根目录） | 规划文档；§1.2 已完成清单需按代码复核 |
| [XH202620_文档规划/01_文档规划总方案.md](../XH202620_文档规划/01_文档规划总方案.md) | 写作蓝图 | 规划；"垂类模型精调"未实现 |
| [docs/产品二-CodeNexus计算机学科智能教学系统.md](docs/产品二-CodeNexus计算机学科智能教学系统.md) | 产品二规划 | 规划中（大部分未实现） |
| [docs/赛题差距分析与重构建议.md](docs/赛题差距分析与重构建议.md) | 2026-06-21 旧分析 | 已废弃/仅历史追溯 |

### 7.3 文档维护规则

- 现行文档写入 `docs/phase1/` 并在 `DOCUMENTATION_INDEX.md` 登记。
- 与开发者讨论后的方案/技术路线变化，必须同步 README、对应现行文档与索引；被替代文档标记"已废弃/仅历史追溯"。
- `docs/refactor/`、`backend/docs/`、`frontend/docs/`、根目录产品/比赛材料仅用于历史追溯，不作为实现依据。
- 禁止用规划文档、Shadow 报告或离线研究证明功能已完成；一切以注册路由、模型、迁移、测试与浏览器行为为准。

---

## 近期关键更新（时间线）

- **2026-08-12**：新课程默认开放知识图谱、证据、认知分析和安全策略配置；当前「实验平台」仅接入代码沙箱，因此 `experiment`/`coding_sandbox` 默认关闭，须由教师按课程显式启用。课程设置中的智能体策略仅保留已被教学问答运行时消费的 `enabled` 启动开关；逐工具治理继续由独立 `AgentToolPolicy` 链路负责，尚未在课程设置页提供配置入口。平台 `ADMIN` 权限在所有课程持有成员列表不可见的「课程所有者」身份（`course_role=owner`、无成员关系），facade 首页与建设列表对管理员返回全部课程（含草稿）以便修改不合规课程。
- **2026-08-11**：课程导入走受管异步路径（解析先行 → GraphRAG 草稿排队教师审核 → 授权后激活 LanceDB/BGE）；平台管理员可配置任务并发。初始备课若个别讲稿未通过证据校验或模型漏项，保留其余草稿并标记 `partial_success`，由教师在讲稿页手工补齐；未覆盖/空讲稿是不可确认绕过的发布 BLOCKER。
- **2026-08-11**：PPT manifest 改为缓存优先的后台 `media.ppt_manifest` 任务：复用映射阶段页图、仅补渲染缺页、记录安全页数进度；激活不再同步触发 LibreOffice 渲染。
- **2026-08-11**：课程建设助教自由文本改由 Prep 结构化意图路由器按完整语义选择既有五种 action，移除关键词兜底；低置信度/范围不明请求只澄清或返回 `PREP_AGENT_INTENT_UNAVAILABLE`。明确按钮 action 仍绕过分类器；一键整理结构/优化讲解在 batch API 前写入带授权标识的本地用户消息，批量原子应用与单节点待审核提案语义保持不变，无数据库迁移。
- **2026-08-10**：智能备课材料证据 Map/Reduce 调用预算 64→160，证据 ID 服务端确定性回填；平台女性讲师成为默认 2D 角色；课程 87 Demo 发布版本本地 Chrome 播放回归通过。
- **2026-08-09**：账户名称收敛为唯一 `username`；Ubuntu 部署基线（LanceDB/PaddleOCR/GraphRAG Worker/Judge0）审计完成，GraphRAG/Judge0 fail-closed。
- **2026-08-12**：ResearchAgent 的真实部署数据库兼容基线确认为 PostgreSQL 16.14 + pgvector 0.7.4；vector 类型、`<=>` 余弦运算符与 Alembic `0053` 五张工作区表均只读验收。运行时将 pgvector SQL 不可用降级为关键词检索，不修改数据库配置或服务。
- **2026-08-13**：TeachingAgent 学习调整 P0 增加 release-pinned 回顾提案与学习者确认的返回锚点；`applied` 仅表示已接受回顾，不表示浏览器跳转成功。泛雅兼容 `/progress/adjust` 不再根据外部理解等级伪造建议，只有关联同一学习者、课程、有效冻结目标及已持久化助手回答的真实回合才返回补充内容；否则明确返回 `503`。本地定向测试已通过，浏览器人工验收和部署仍待执行。
- **2026-08-11**：ResearchAgent Harness v1（真实条件 LangGraph、科研工作区、Todo/Notepad/Scope/Memory、pgvector 迁移与五视图前端）；多源检索、全文、写作与完整仓库复现仍未接通。
- **2026-08-07**：ResearchAgent P0（arXiv 检索）；Stage 8 Provider 配置基线（`MEDIA_DEMO_MODE`）；P5.1 音色/角色注册表、P5.2 OSS 隔离；统一学习数据链（`learning_events` + `/facade`）。

---

*本 README 基于 2026-08-11 代码库探索重写；所有功能状态均可回溯至代码证据，详见《代码库探索结果摘要与差距分析》。*
