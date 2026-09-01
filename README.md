# CodeNexus智码交响 —— 让课程回应学习：知识图谱驱动的可追溯智能教学系统

> **计算机学科垂类大模型与智能体应用 · 证据驱动的课程建设、互动学习与教学分析平台**
>
> **内容可审核 · 知识可追溯 · 判断有依据**
>
> 挑战杯"揭榜挂帅" XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》（发榜单位：科大讯飞）｜团队：蟹不肉｜材料硬截止 2026-09-05
>
> **2026-08-20 新赛题改造启动（挑战杯 XH-202620）**：在既有参赛基线之上，面向挑战杯"揭榜挂帅"
> XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》（发榜单位：科大讯飞，材料硬截止
> 2026-09-05）改造为**计算机学科垂类大模型与智能体应用**：基线分支 `feature/xh202620`
> （自 dev-liu @9c52bd1 切出，含 dev-main 全部最新代码）。差距分析、产品定位与改造路线图见
> [docs/phase1/2026-08-20\_XH202620差距分析与产品定位.md](docs/phase1/2026-08-20_XH202620差距分析与产品定位.md)。
> 该文档替代已废弃并删除的《docs/赛题差距分析与重构建议.md》（其"完全重构"结论被后续开发推翻；历史见 git）。

> **2026-08-31 PDF 解析布局升级（本地已验证，未提交部署）**：pdf-plumber 行级提取
> 替换为 `pdf_layout.py` 框感知布局分析（文本框 Union-Find 聚类、相对标题判定、
> 代码区聚合、公式残片吸收与符号残片过滤），解决证据候选中的语义截断与无意义
> 公式残片；真实课程 PDF 验证：u1 教材数学残片微块 157→13（-92%）、course3
> 字空格标题恢复完整；测试 256 passed。完整审计（含教师确认漏斗 1.5% 转化等
> 8 条链路问题与 P0-P3 改进提案）见
> [证据生成链路审计与改进方案](docs/phase1/2026-08-31_证据生成链路审计与改进方案.md)，
> 解析基线见 [统一课程建设与解析基线](docs/phase1/统一课程建设与解析基线.md) §4.2。

> **2026-09-01 对话式代码挑战（本地实现，未部署）**：学生学习页只呈现
> TeachingAgent；回答完成后可异步出现代码挑战卡，并在嵌入式 CodeMirror 工作区用唯一操作
> “运行并获得反馈”反复调用 Judge0。每次运行保留服务器原始记录，同一 guided session 只聚合
> 一个 episode 和每节点至多一条正式证据；单个 episode 的 1.5 权重不足以单独判定掌握。
> AI 补题需通过结构校验、参考解全测和 starter 反向校验，无逐题教师审批；课程级工具策略仍可关闭。
> 详见 [对话式代码挑战实施说明](docs/phase1/2026-09-01_对话式代码挑战实施说明.md)。

> **2026-08-13 代码作答认知更新**：CodingAgent 只可在本次提交的
> `student_id + course_id + run_id` 授权范围内短暂读取源码；EduAgent 只接收无源码的
> 结构化诊断摘要。Judge0 服务端验证的代码结果已与题库作答并列进入认知评判，权重分别
> 为 1.5 和 1.0，达到 3.0 有效权重才形成掌握度结论。边界见
> [实验室-代码沙箱可信评测契约](docs/phase1/实验室代码沙箱可信评测契约.md)。

> **2026-08-11 数据库迁移状态**：服务器运行库已切换到独立 PostgreSQL 16。Alembic `0052`、可审计 SQLite 快照迁移工具和 `deploy/postgres/` 是当前基线；最终快照的 162 张表、89,561 行已完成摘要/外键校验。迁移会原样保留历史 `media_release_items → script_nodes` 失效引用，并要求目标侧逐关系数量与源快照一致；该一项外键在 PostgreSQL 中为 `NOT VALID`，新写入仍被校验。`0049/0050` 中遗留的小写枚举标签只用于兼容历史类型，`0051/0052` 补齐并归一化为 SQLAlchemy 实际持久化/读取的大写成员名：`evidence_render_assets.asset_type`、`source_material_versions.parse_status` 和 `source_materials.status` 不得保留小写活跃值，其他枚举仍 fail-closed。实施入口见 [deploy/postgres/README.md](deploy/postgres/README.md) 与 [SQLite 到 PostgreSQL 迁移基线](docs/phase1/2026-08-11_SQLite到PostgreSQL迁移与服务器切换.md)。
>
> 历史 `deploy/DEMO部署说明.md` 中"生产 MySQL"描述已废弃，不可作为部署依据。

> **能力状态口径**：全文对外仅使用"已部署"与"规划能力"两种能力状态——"已部署"表示能力已进入远端运行环境并形成业务入口或服务调用链；"规划能力"表示尚无完整闭环，只能作为后续方向。量化效果与性能以专项实验结果为准。真实实现以代码、注册路由、数据库迁移、契约测试和浏览器手工行为为准；规划文档不能替代可运行证据。详见 [docs/DOCUMENTATION\_INDEX.md](docs/DOCUMENTATION_INDEX.md)。

> **2026-08-13 代码实验状态**：正式评测已收敛为持久化异步任务和 ACM/ICPC 0/1 评分；自由运行保持非计分 Beta。实验室记录只从服务端终结尝试投影，旧 `POST /lab/{lab_id}/records` 与学生成绩提交入口已下线。现行边界、灰度限制和未完成的真实环境验收见 [实验室-代码沙箱可信评测契约](docs/phase1/实验室代码沙箱可信评测契约.md)。

***

## 目录

1. [项目简介与设计目标](#1-项目简介与设计目标)
2. [三项核心机制](#2-三项核心机制)
3. [系统总体方案与架构](#3-系统总体方案与架构)
4. [核心功能特性（含实现状态）](#4-核心功能特性含实现状态)
5. [技术栈与运行环境](#5-技术栈与运行环境)
6. [目录结构概览](#6-目录结构概览)
7. [快速开始指南](#7-快速开始指南)
8. [常用开发与部署命令](#8-常用开发与部署命令)
9. [云端部署与验证状态](#9-云端部署与验证状态)
10. [文档与规划索引](#10-文档与规划索引)

***

## 1. 项目简介与设计目标

CodeNexus智码交响是一套智能体协作型全场景智慧教学系统，核心思想是**让课程回应学习**。系统以课程知识图谱为技术基座，把各科课件与历史文档带来源地解析，形成可信、可用、可追溯的知识结构；教师导入的课程知识库与图谱检索结合，为智能体提供精确的专业课件检索能力；教育智能体依据六维认知数据理解学生怎么学、学到什么程度、学习意愿如何，据此开展促学、导学、督学与办学，让智能体跟着学生一起进步。

系统不是外部教学平台的替代品，也不是独立运行的通用聊天机器人：它通过外部接口适配接入课程上下文，在内部完成材料解析、证据治理、课程生成、知识包构建、智能体协作、媒体发布与学习证据处理。

端到端主链围绕一门课程建立连续生命周期：

```text
材料进入与版本登记 → 文档解析与质量判定 → 证据片段与教师确认
→ 知识与课程候选生成 → 双门控审核 → 课程发布与回滚
→ 学生学习、实时问答、练习评价 → 学情反馈
```

**设计原则：**

* **以课程而非模型为系统边界**：材料、知识、检索、问答、练习、媒体与学习证据都首先归属于课程；模型供应商可替换、检索实现可演进、外部接口可变化，课程权限、版本与证据归属不因此失效；

* **以证据而非流畅度评价生成内容**：生成内容需要引用有效材料证据并经过教师审核或明确质量门，证据缺失时保留候选状态或返回失败语义；

* **以版本快照而非原地覆盖管理变化**：材料重解析、课程修改、图谱更新与索引重建均通过不可变快照、激活指针与回滚记录管理，避免历史课程与当前索引静默错位；

* **以最小权限和工具自校验约束智能体**：课程访问服务先解析调用者在当前课程中的能力，各工具执行前再次校验课程与角色，高风险动作需要教师确认，权限、治理或安全阀不可用时失败关闭；

* **以证据强度区分学习数据用途**：交互信号用于描述过程、正式评分用于支持判断、完整对话用于产品连续体验、智能体审计用于运行追踪，四类数据分别保存、授权与消费。

**三条可追溯链**：内容追溯链（材料→解析运行→DocumentIR→证据→课程发布）、知识追溯链（证据→知识节点→图谱快照→知识包→Citation→问答回答）、学习追溯链（学习事件/评分→学习证据→认知状态→推荐/分析），以课程身份与发布版本为共同连接键。

**赛题延伸（挑战杯 XH-202620）**：在通用教学闭环之上，面向计算机学科扩展知识库、代码实验、算法可视化与助研（ResearchAgent）能力。其中**模型微调（LoRA/SFT）与 CS 学科知识库内容填充为规划项，尚未实现**——该两项已列为 XH-202620 改造（基线 `feature/xh202620`）的核心补齐目标，进度与口径见 [2026-08-20 XH-202620 差距分析与产品定位](docs/phase1/2026-08-20_XH202620差距分析与产品定位.md)。

## 2. 三项核心机制

### 2.1 证据锚定与教师审核双门控的智课生成机制（第四章）

课件经原生解析与 PaddleOCR 置信度加权融合后形成稳定的 Canonical DocumentIR，证据片段与知识候选必须通过**证据门**（`evidence_refs` 可解析到当前课程有效证据）与**教师审核门**（生成结果以草稿/提案呈现，教师批准后才进入正式课程）才能发布；发布版本不可变且支持回滚。同一机制应用于 AI 出题（`QuestionGenerationDraft` → 教师批准 → `QuestionBankItem`）。

关键对象：`SourceMaterialVersion`、`DocumentParseRun`、`DocumentIRVersion`、`DocumentBlock/EvidenceSpan`、`CourseEvidenceRecord`、`PatchProposal`、`CourseRelease`。

### 2.2 知识图谱驱动的可追溯精确检索知识包（第五章）

知识图谱是检索体系的技术基座：节点是知识点，边是类型化关系（前置/从属/支撑/关联），每个节点锚定课程证据、每条关系经教师确认、图谱快照发布后不可变。图谱之上采用 BM25 稀疏检索 + 本地 BGE 语义向量 + RRF 排名融合 + GraphRAG 关系增强，检索结果再经**课程隔离、版本一致与 Citation 闭包三重约束**才允许进入正式回答：`admit(d)` 当且仅当 `d.course = c_active` 且 `d.bundle = b_active` 且存在 `Citation(d)→Evidence`。索引不可用时失败关闭，不回退到跨课程或未经审核的候选块。

关键对象：`CourseKnowledgeNode`、`GraphSnapshotRecord`、`CourseKnowledgeBundle`、`CourseKnowledgeHead/Activation`、`CourseVectorIndex`（LanceDB 三类索引）、`ActiveBundleCourseRetrievalPort`。

### 2.3 交互—测评双源证据分层驱动的学情反馈机制（第六章）

将交互信号（访问、进度、提问）与正式测评证据（服务端评分、代码实验终态）分域治理：交互信号描述过程与潜在需求、不能单独写成掌握结论；正式证据写入 `LearningEvidenceRecord` 并绑定课程发布版本。系统在课程与知识节点范围内输出六维认知状态 `s(c,k)=⟨perf, conf, confusion, depth, hint, need⟩`，每维有独立样本门槛，不达标保持 `unknown` 并写入原因码；叠加认知衰减（半衰期 14 天）、学习轨迹与图谱驱动的学习路径推荐。项目正进一步推进证据驱动的细粒度知识追踪研究（**RE-KT**），将认知机制从规则投影升级为可学习的证据驱动学生模型（研究推进中，不以研究规划代替已实现能力）。

关键对象：`LearningEvidenceRecord`、`CognitiveState`、`cognitive_decay_service`、`LearningTrajectoryRecord`、`learning_path_service`、`derive_question_inference_signals`。

## 3. 系统总体方案与架构

### 3.1 五层系统架构

| 架构层        | 承载内容                     | 核心对象                                    |
| ---------- | ------------------------ | --------------------------------------- |
| 平台接入与应用交互层 | 泛雅兼容接口、教师端与学生端页面         | Vue 3 前端、`/api/v1/compat` 适配            |
| 课程业务与发布层   | 课程草稿、材料版本、质量门、发布与回滚      | `CourseBuildDraft`、`CourseRelease`      |
| 智能体协作层     | 三类产品智能体、内部代码能力与兼容层、工具治理 | edu（含 coding）/prep/research + legacy coding runtime |
| 课程知识与证据层   | DocumentIR、证据、图谱、知识包、索引  | `GraphSnapshot`、`CourseKnowledgeBundle` |
| 基础设施与外部能力层 | LLM、OCR、数据库、对象存储、沙箱      | PostgreSQL、LanceDB、Judge0               |

### 3.2 多智能体协作

备课、教学与科研三类产品智能体状态独立，通过受控 Port 与统一治理层协作，不共享跨课程可变状态。代码教学已收敛为 TeachingAgent 的内部 `edu/coding` 能力；旧 `coding` runtime 只服务兼容 API。协作媒介不是自然语言消息，而是课程发布、知识包、提案、证据记录与受控 Port。五种统一约束：课程权限、证据、版本、工具治理、数据域。

| 智能体            | 核心职责            | 正式写入边界               |
| -------------- | --------------- | -------------------- |
| Prep Agent     | 备课提案生成（初始 + 增量） | 经教师审核后写入课程草稿         |
| TeachingAgent  | 教学问答、对话式代码挑战与受控教学动作 | 回答后非阻塞写对话域；代码运行由服务端聚合证据 |
| 代码兼容层        | 旧实验解释与分层提示 API      | 委托 TeachingAgent 内部代码能力；不再是学生产品入口 |
| ResearchAgent  | 科研检索与补充证据       | 外部结果仅补充参考，进正式课程需教师审核 |

关键机制：LangGraph 显式工作流（节点边界即权限边界，TeachingAgent 22 节点）、per-tool policy check（`_governance_check` 在每个工具节点前执行，HIGH\_RISK\_TOOLS 治理异常时 fail-closed 默认禁用）、`ScopeValidator` 强制课程/学生/成员/能力校验。

### 3.3 AI 安全围栏

安全围栏贯穿三个层面：**智能体安全围栏**（课程类型安全收敛为 professional/cybersecurity/ideological 三态、政治敏感两级审查、平台级屏蔽词配置、工具 fail-closed）、**沙箱安全围栏**（Judge0 独立实验服务器物理隔离、命令黑名单、认证边界）、**数据安全围栏**（四域分离、对象标识签名访问、Course Access v1 唯一授权入口、密钥不进前端/仓库/日志/文档）。

## 4. 核心功能特性（含实现状态）

> 状态口径：✅ 已实现（有代码/路由/测试证据） ｜ 🧪 测试或 Demo 阶段（可运行但默认关闭或需显式配置） ｜ 📋 规划中/未实现 ｜ ⚠️ 接口已定义实现待填充

### 4.1 课程建设（教师端）

| 功能                                                   | 状态 | 说明                                                                                                                       |
| ---------------------------------------------------- | -- | ------------------------------------------------------------------------------------------------------------------------ |
| 课程创建、资料上传（≤100MB）、课程生命周期（发布/下架/回滚）                   | ✅  | `document.py`、`course_build_service.py`、`course_release_service`                                                         |
| 文档解析（PPT/PDF/DOCX → Canonical DocumentIR → 内容块/证据锚点） | ✅  | 原生解析 + LibreOffice/Poppler + PaddleOCR（本地真实链路），三态质量判定 PASS/BORDERLINE/FAIL                                               |
| 证据片段与教师确认、结构化讲稿生成                                    | ✅  | EvidenceSpan 候选 → 教师确认 → `CourseEvidenceRecord`；Prep Agent + 有界 Map/Reduce + PatchProposal 审核闸门；单节点优化返回待审核提案，批量一键优化才直接应用 |
| PPT 页面 ↔ 知识点映射                                       | ✅  | `mapping.py` + LLM 语义匹配                                                                                                  |
| 课程知识图谱（GraphRAG，8 种教育关系）                             | 🧪 | Worker 已部署、LanceDB/BGE 已接通；真实课程构图因**数据外发授权未获批**默认关闭（`GRAPHRAG_ENABLED=false`）                                            |
| AI 出题双门控审核                                           | ✅  | `question_generation_drafts` → 教师批准 → `QuestionBankItem`                                                                 |
| 教师 8 步生产工作台（含独立知识治理步骤）、脚本快照/版本/回滚          | ✅  | shadow 前端 `/app/course/:courseId/build`；“知识”从建设流程跨布局进入 `/app/course/:courseId/knowledge/`，题库审核入口不再作为建设步骤 |

### 4.2 媒体与数字人讲授

| 功能                                                | 状态     | 说明                                                                                                                                 |
| ------------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| 课程级批量媒体（MediaBuildBatch → MediaReleaseItem）       | ✅      | 只读计划 → 教师一次确认 → 批量构建                                                                                                               |
| 不可变播放清单（`audio-playlist/v1`、`ppt-manifest/v1`、字幕） | ✅      | 发布快照固定 `release_id + playlist_content_hash`；PPT manifest 使用后台 `media.ppt_manifest`，复用映射页图并仅补渲染缺页                                   |
| 数字人（PixiJS 2D 角色）                                 | 🚫 已移除 | XH-202620 决策：完全移除数字人，只保留 TTS + PPT + 字幕。前端已移除 avatar 渲染/选择入口，后端移除 avatar 服务/端点/worker，媒体发布始终走兼容模式。历史不可变 release 数据与授权记录保留（DB 表未删）。 |
| 真实 TTS（豆包）                                        | 🧪     | `MEDIA_DEMO_MODE=false` + `STAGE8_TTS_PROVIDER=doubao` 显式配置；已通过一次受控 POC                                                            |
| OSS/S3 对象存储、上传 confirm 校验                         | ✅      | Local PUT / S3-OSS presigned POST 双链路                                                                                              |
| 旧 `/video-gen` 数字人视频链                             | 🚫     | 仅历史兼容，带弃用响应与 Sunset                                                                                                                |

### 4.3 学生学习

| 功能                            | 状态 | 说明                                                                                      |
| ----------------------------- | -- | --------------------------------------------------------------------------------------- |
| 选课、分屏/统一学习工作台（大纲+媒体+助手+笔记）    | ✅  | `/app/course/:courseId/learn`；legacy `StudentPlayer` 保留                                 |
| 学习事件链（`learning_events`）与进度续接 | ✅  | 事件 → 投影 → 学生状态/教师统计；失败事件浏览器待发队列                                                         |
| 六维认知状态 + 掌握度（规则基线 V1）         | ✅  | `rule_baseline.py` 为真实实现；BKT/DKT/IRT 仅接口定义，RE-KT 为研究推进项                                 |
| 认知推荐                          | ✅  | `cognitive_recommendation.py` + `recommendation_consumed` 事件                            |
| 课程内问答（TeachingAgent 受控问答）     | ✅  | 上下文锚定 `course_id+release_id+outline_node_id`，Citation 验证，Conversation 域独立持久化（默认 90 天保留） |
| TeachingAgent 受控回顾与进度续接       | 🧪 | 已实现本地 P0：提问位置、冻结回顾目标（由服务端确定性解析，不接收模型跳转位置）与点击时返回锚点三者分离；回顾须由学习者确认，且不会写入掌握度                |
| TeachingAgent 对话式代码挑战           | 🧪 | 本地端到端代码与组件级浏览器验收完成：异步准备卡、单按钮多次运行、刷新恢复、episode 低噪声证据；真实课程 + 真实 Judge0 完整冒烟与部署未执行 |
| 练习/测验、前置知识跳转补学                | ✅  | `question_bank.py`、`prerequisite.py`                                                    |

### 4.4 代码实验（CS 垂类）

| 功能                            | 状态 | 说明                                                                                      |
| ----------------------------- | -- | --------------------------------------------------------------------------------------- |
| 代码沙箱执行（Judge0，独立实验服务器）        | 🧪 | 客户端完整（多语言/状态映射/降级），`JUDGE0_ENABLED=False` **默认禁用**（共用主机权限受限）；云端 Demo 环境已接入独立 Judge0 服务器 |
| 平台实验室（Labs）、算法实验（Experiments） | ✅  | 当前仅支持代码沙箱；教师可按课程启用，关闭时师生不显示"实验任务"，未启用沙箱时执行返回 `CODING_SANDBOX_DISABLED`                  |
| 算法可视化（JSAV，11 种白名单算法）         | ✅  | legacy `VisualizationView` + JSAVPlayer；学生可播 published 计划，教师可创建/发布计划                    |
| TeachingAgent 内部代码反馈         | ✅  | `edu/coding` 只在本次 run 授权范围内短暂读取源码并返回白名单反馈；旧 CodingAgent API/runtimes 暂作兼容，不再作为学生可见入口 |

### 4.5 助研（ResearchAgent）与平台管理

| 功能                                                      | 状态 | 说明                                                                                                                   |
| ------------------------------------------------------- | -- | -------------------------------------------------------------------------------------------------------------------- |
| ResearchAgent HarnessEngineer                           | ✅  | 真实条件路由 LangGraph；动态 Prompt/Tool/Context/压缩；25s 超时与并发 8                                                               |
| 科研工作台 `/app/course/:courseId/research`                  | ✅  | 论文、Todo、Notepad、Memory、Scope 五个可操作视图；`course.view` 可见、执行另行授权                                                         |
| 学科知识库检索页 `/app/discipline-knowledge`                    | ✅  | XH-202620 CS 垂类只读检索（权威来源/图邻居/概览），R8 上线                                                                               |
| 工作区持久化与向量记忆                                             | ✅  | Alembic `0053`；已验证 PostgreSQL 16.14 + pgvector 0.7.4，向前兼容 PostgreSQL 18；embedding 或 vector 查询不可用时明确降级关键词             |
| arXiv 论文元数据检索 + 来源核验                                    | ✅  | 真实接通（节流 3s + 24h 缓存 + PII 脱敏 + EvidenceGate）                                                                         |
| 趋势分析、证据综合、学术写作、代码复现                                     | 🧪 | 学术写作（writing\_assist）与前沿趋势分析（trend\_analysis）后端已实现（测试 7+8 passed）；证据综合/代码复现仍 preview，页面按 `research_preview` 展示，未伪装完成 |
| Semantic Scholar / OpenAlex / Crossref、全文解析、GitHub 仓库复现 | 📋 | 规划中                                                                                                                  |
| 平台管理员（用户/角色/Provider 配置/任务并发）                           | ✅  | `/app/admin`（shadow）、`admin_platform.py`                                                                             |
| 泛雅·超星 AI 兼容适配层                                          | ✅  | `external_apis/fanya_chaoxing_ai/`，签名校验/字段转换/权限解析/能力降级                                                               |

### 4.6 规划中（未实现）

| 功能                 | 说明                                                                                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 学科垂类模型微调（LoRA/SFT） | 可复现管线已交付（`backend/finetune/`：数据集生成 ✅ 132+14、评测基准 10 用例 ✅、训练脚本 ✅）；**训练未执行**（无 GPU，诚实标注，需 GPU 或星火 MaaS）                                                                                                   |
| CS 学科知识库内容填充       | `knowledge_data/` 112 节点/106 关系（数据结构/算法/OS/计网/数据库/软件工程/机器学习/编译原理/计算机组成原理/离散数学/计算机图形学 11 门课）已填充并通过校验；已接线为只读检索服务 `GET /api/v1/discipline-knowledge/*`（CJK 二元组短语检索，服务 + API 测试 20 passed）；图谱/检索白名单深度接线为后续项 |
| 星火 LLM 深度接入        | 讯飞星火 LLM Provider 已接入（`LLM_PROVIDER=spark`，OpenAI 兼容接口，单测 6 passed）；真实 Key 手工验收待进行；PPT/TTS 仍走原讯飞链路                                                                                                      |
| 代码项目交流平台（类 CSDN）   | 无实现                                                                                                                                                                                                     |
| RE-KT 证据驱动学生模型     | 研究推进中（Shadow Mode 接入、细粒度 misconception 追踪、选择性诊断）                                                                                                                                                        |

***

## 5. 技术栈与运行环境

### 5.1 后端

| 项      | 版本/选型                                                                                                                    |
| ------ | ------------------------------------------------------------------------------------------------------------------------ |
| 语言/框架  | Python + FastAPI（≥0.135）+ Uvicorn                                                                                        |
| ORM/迁移 | SQLModel（≥0.0.37）+ Alembic（当前 head `0053`）                                                                               |
| 智能体    | LangGraph（0.6.x）+ 自研 Port/Provider 契约                                                                                    |
| 文档解析   | Docling（≥2.81）、LibreOffice、Poppler、PaddleOCR（容器）                                                                         |
| 向量/图谱  | LanceDB 0.34、本地 BGE 嵌入、GraphRAG 3.1.1（独立 Worker，默认关闭态）                                                                   |
| 代码沙箱   | Judge0（独立实验服务器部署，客户端默认关闭）                                                                                                |
| 外部服务   | DeepSeek LLM（`LLM_PROVIDER=deepseek`，默认，XH-202620 学科垂类基座）、讯飞星火 LLM（可选，`LLM_PROVIDER=spark`）、豆包 TTS（Demo/显式）、讯飞 PPT、arXiv |
| 数据库    | 云端 PostgreSQL 16.14 + pgvector 0.7.4（基线）；本地开发 SQLite；对象存储 Local/S3/OSS 适配                                                |

### 5.2 前端

| 项   | 版本/选型                                                                |
| --- | -------------------------------------------------------------------- |
| 框架  | Vue 3.5 + Vite 7 + Pinia + vue-router 5                              |
| 渲染  | PixiJS 8.16（Sprite2D 数字人）、Chart.js、KaTeX、marked                      |
| 双前端 | legacy 路由（/）+ shadow 前端（`/app/**`，`VITE_ENABLE_SHADOW_FRONTEND` 默认开） |

### 5.3 运行环境

* Node ≥ 20.19（前端）；Python 3.11+（后端，uv 管理，`uv.lock`/`pyproject.toml`）

* 生产部署：Ubuntu 22.04 + systemd（`smartcarb-backend.service`，2 workers）+ Nginx（`smartcarb-nginx.conf`）+ Docker Compose（`deploy/`）

* 服务器资源边界：主服务器 4 核 / 8 GB（云端 Demo），OCR/GraphRAG/Judge0 压测须串行

***

## 6. 目录结构概览

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
│   │   └── external_apis/       # 泛雅·超星 AI 兼容适配层
│   ├── alembic/                 # 45 个迁移版本
│   ├── finetune/                # XH-202620 微调管线（数据集/评测基准/训练脚本，需 GPU 执行）
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
├── competition/                 # XH-202620 参赛材料 01–07（骨架，9/5 截止）
├── deploy/                      # Docker Compose、Dockerfile.backend、nginx、judge0、paddleocr
├── database/                    # SQLite 生产库 + 备份
├── knowledge_data/              # CS 学科知识库（112 节点/106 关系，11 门课，只读检索服务 /api/v1/discipline-knowledge）
├── scripts/                     # dev-stack.sh（PaddleOCR + 后端一键启动）等
├── research/                    # 离线研究沙箱（不构成生产结论）
└── test/ tests/                 # 测试资产与基准
```

***

## 7. 快速开始指南

### 7.1 后端启动

```bash
cd backend
uv sync                 # 按 uv.lock 安装依赖（或 uv run 自动处理）
uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

* API 文档：<http://localhost:8000/docs>

* 数据库迁移（如需要）：`uv run alembic upgrade head`

* 一键开发栈（PaddleOCR 容器 + 后端）：`./scripts/dev-stack.sh`（Linux/macOS）

### 7.2 前端启动

```bash
cd frontend
npm install             # 或 pnpm install（仓库含 pnpm-lock.yaml）
npm run dev             # 默认端口 5300
```

* 访问 <http://localhost:5300（终端按> `o` 打开浏览器）

* shadow 前端默认开启（`VITE_ENABLE_SHADOW_FRONTEND=true`），入口为 `/app/**`

### 7.3 环境配置

```bash
cd backend
cp .env.example .env     # 若有模板；否则按 config.py 默认值 + 生产 .env 填写
```

关键开关（缺省均为安全默认）：

| 变量                            | 默认         | 说明                                                                   |
| ----------------------------- | ---------- | -------------------------------------------------------------------- |
| `LLM_PROVIDER`                | `deepseek` | 外部 LLM；可选 `doubao`/`qwen`/`openai`/`spark`；未配置 Key 时相关能力 fail-closed |
| `MEDIA_DEMO_MODE`             | `true`     | 媒体建设用 Fake WAV，页面显示 `fake-demo`，不调用付费 TTS                            |
| `STAGE8_TTS_PROVIDER`         | —          | 正式 TTS 需 `MEDIA_DEMO_MODE=false` + `doubao`                          |
| `JUDGE0_ENABLED`              | `false`    | Judge0 沙箱默认关闭                                                        |
| `GRAPHRAG_ENABLED`            | `false`    | GraphRAG 构图默认关闭（等待数据外发授权/消费确认）                                       |
| `MEDIA_AVATAR_ENABLED`        | `false`    | 数字人默认关闭（只保留 TTS + PPT）；开启才签发 avatar manifest/cue                     |
| `VITE_ENABLE_SHADOW_FRONTEND` | `true`     | 前端 shadow 入口                                                         |

### 7.4 运行测试

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

***

## 8. 常用开发与部署命令

### 8.1 常用命令速查

| 操作      | 命令                                                                                                               | <br />        |
| ------- | ---------------------------------------------------------------------------------------------------------------- | :------------ |
| 后端开发启动  | `cd backend && uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`                        | <br />        |
| 后端单测    | `cd backend && uv run pytest -q`                                                                                 | <br />        |
| 数据库迁移   | `cd backend && uv run alembic upgrade head`（PostgreSQL `0049–0052` 为前向枚举迁移；故障按备份/服务环境恢复或前向修复，勿执行 `downgrade -1`） | <br />        |
| 前端开发    | `cd frontend && npm run dev`                                                                                     | <br />        |
| 前端构建    | `cd frontend && npm run build`                                                                                   | <br />        |
| 前端单测    | `cd frontend && npm run test:unit`                                                                               | <br />        |
| 前端 lint | `cd frontend && npm run lint`                                                                                    | <br />        |
| 应用冒烟    | `cd frontend && npm run smoke:app`                                                                               | <br />        |
| 一键开发栈   | \`./scripts/dev-stack.sh \[--skip-backend                                                                        | --skip-ocr]\` |

### 8.2 部署（Ubuntu）

```bash
# 后端 systemd 服务（工作目录 /opt/smartcarb/backend，uvicorn 0.0.0.0:8000，2 workers）
# 前端 Nginx：SPA 回退 + /api/ 反代 127.0.0.1:8000（60m body、600s 超时）
# 完整部署说明见 deploy/DEMO部署说明.md 与 docs/phase1/2026-08-09_服务器环境一致性与外部链路审计.md
```

历史部署脚本（根目录 `deploy_*.sh`、`verify_*.sh` 等）为 2026-08 现场排障产物，仅供参考。

***

## 9. 云端部署与验证状态

系统已完成云服务器部署，作为正式展示与功能验收环境（第十一章）：主服务器运行 Nginx、FastAPI 后端、PostgreSQL 16 + pgvector、LanceDB、对象存储与 PaddleOCR 文档解析服务；独立实验服务器运行 Judge0 代码沙箱并通过内网受控访问。该环境不代表已获准处理真实生产学生数据，也不代表已达到互联网规模生产系统的全部运维要求。

### 9.1 部署拓扑

| 组件                                                | 运行状态               | 部署事实                                                         |
| ------------------------------------------------- | ------------------ | ------------------------------------------------------------ |
| Nginx                                             | systemd 服务         | 统一入口，监听 HTTP 80；提供前端静态资源并转发 API 请求                           |
| CodeNexus Backend（systemd 单元 `smartcarb-backend`） | systemd 服务         | Uvicorn 以 2 个 Worker 监听 127.0.0.1:8000；根路径 / 为应用健康检查         |
| PostgreSQL                                        | Docker 容器          | postgres:16.14 + pgvector 0.7.4，仅绑定回环地址；定时健康检查与逻辑备份          |
| PaddleOCR                                         | Docker 容器          | smartcarb/paddleocr:2.7.3-cpu，仅绑定 127.0.0.1:8090，提供独立 OCR 服务 |
| Judge0                                            | 独立实验服务器（Docker 容器） | API Server、单 Worker、PostgreSQL、Redis 四容器；Server 仅对内网后端开放认证接口 |

### 9.2 端到端验证（云端 Demo / 合成课程 / 测试账号）

以下核心场景已在云端环境中完成端到端走通验证（第十二章）：课程材料上传解析、证据审核与发布、知识包构建与激活、跨课程隔离、学生实时问答、代码沙箱运行、题目草稿审核、学习调整与续学、学情分析、泛雅兼容问答。验证结果用于证明功能链路完整可用，不代表教学效果或性能达标。

云端运行中的 OpenAPI 暴露 11 条主闭环接口：

| 路径                                                               | 用途            |
| ---------------------------------------------------------------- | ------------- |
| `POST /api/v1/teaching-agent/respond`                            | 课程内受控教学问答     |
| `POST /api/v1/teaching-agent/respond-for-learner`                | 指定学习者的受控教学响应  |
| `GET /api/v1/teaching-agent/conversations/{course_id}`           | 学习者会话恢复       |
| `GET /api/v1/teaching-agent/conversations/{course_id}/inference` | 提问结构化推断信号     |
| `GET /api/v1/player/init/{course_id}`                            | 学习播放器初始化      |
| `GET /api/v1/player/knowledge-points/{course_id}`                | 播放中的知识点读取     |
| `POST /api/v1/player/progress/save`                              | 第一方学习进度保存     |
| `GET /api/v1/player/progress/{course_id}`                        | 第一方学习进度读取     |
| `POST /api/v1/compat/qa/interact`                                | 泛雅文本问答适配      |
| `POST /api/v1/compat/progress/track`                             | 泛雅进度追踪适配      |
| `POST /api/v1/compat/progress/adjust`                            | 经验证上下文的补充讲解适配 |

`/api/v1/compat/qa/voiceToText` 在未完成真实接入前返回结构化 `503 ASR_UNAVAILABLE`，不计入可用业务接口计数；第一方语音转写链路（`/api/v1/asr/transcribe`、`/api/v1/asr/result`）已完成源码实现与课程成员授权校验。

### 9.3 能力状态口径

* **已部署**：能力已存在于当前远端 release，并具有真实页面、API、服务或任务调用链；可以描述机制和业务入口，但不能自动推导效果指标；

* **已验证**：功能链路在指定环境中完成端到端走通（云端 Demo / 合成课程 / 测试账号）；

* **已验证链路**：接口与入口已具备、主链路走通，仍需专项实验补充定量数据；

* **规划能力**：尚无完整代码实现或尚未形成闭环，只能作为后续方向。

***

## 10. 文档与规划索引

### 10.1 现行文档（优先阅读）

| 文档                                                                           | 用途                            |
| ---------------------------------------------------------------------------- | ----------------------------- |
| [docs/DOCUMENTATION\_INDEX.md](docs/DOCUMENTATION_INDEX.md)                  | 文档导航与状态（唯一入口）                 |
| [AGENTS.md](AGENTS.md)                                                       | 开发与安全规则（最高优先级）                |
| [docs/phase1/功能现状审计表.md](docs/phase1/功能现状审计表.md)                             | 当前代码审计结论与已知缺口                 |
| [docs/phase1/2026-09-01_对话式代码挑战实施说明.md](docs/phase1/2026-09-01_对话式代码挑战实施说明.md) | TeachingAgent 代码挑战、episode 证据与前端体验 |
| [docs/phase1/服务器环境一致性与外部链路审计.md](docs/phase1/2026-08-09_服务器环境一致性与外部链路审计.md)  | 2026-08-09 Ubuntu 实际环境与外部链路基线 |
| [docs/phase1/统一课程建设与解析基线.md](docs/phase1/统一课程建设与解析基线.md)                     | 统一上传、解析、RAG、讲稿与 PPT 映射目标      |
| [docs/phase1/阶段8\_媒体TTS数字人PPT\_实施规划.md](docs/phase1/阶段8_媒体TTS数字人PPT_实施规划.md) | 媒体与数字人现行基线                    |
| [docs/phase1/研究智能体整体架构与前端设计.md](docs/phase1/研究智能体整体架构与前端设计.md)               | ResearchAgent 架构与上线门          |
| [docs/phase1/路由契约基线.md](docs/phase1/路由契约基线.md)                               | API 契约基线                      |
| [docs/RUN.md](docs/RUN.md)                                                   | 最小启动说明                        |
| [设计指南](design.md)                                                            | 前端视觉令牌/组件规范（改前端前必读）           |

### 10.2 规划与差距分析

| 文档                                                                 | 性质                     | 状态标注 |
| ------------------------------------------------------------------ | ---------------------- | ---- |
| [XH-202620 差距分析与产品定位](docs/phase1/2026-08-20_XH202620差距分析与产品定位.md) | 挑战杯 XH-202620 现行定位与路线图 | 现行   |
| [典型问题测试案例集](docs/phase1/XH202620_典型问题测试案例集.md)                     | 内容质量度测试用例（10 例）        | 现行   |

> 2026-08-20 清理：删除已废弃/过时文档（产品一/产品二规划、创新点建议、平台亮点、文档状态审查清单、
> 旧赛题差距分析等 10 篇，见 git 历史）；此前删除的根目录文档（代码库探索结果摘要与差距分析、
> 文档更新清单、挑战杯文档规划方案、XH202620\_文档规划）不再有引用。

### 10.3 文档维护规则

* 现行文档写入 `docs/phase1/` 并在 `DOCUMENTATION_INDEX.md` 登记。

* 与开发者讨论后的方案/技术路线变化，必须同步 README、对应现行文档与索引；被替代文档标记"已废弃/仅历史追溯"。

* `docs/refactor/`、`backend/docs/`、`frontend/docs/`、根目录产品/比赛材料仅用于历史追溯，不作为实现依据。

* 禁止用规划文档、Shadow 报告或离线研究证明功能已完成；一切以注册路由、模型、迁移、测试与浏览器行为为准。

***

## 近期关键更新（时间线）

* **2026-08-31**：项目更名 **CodeNexus智码交响**（原 SmartCarb），A12 赛题（服务外包·超星）定位完全废弃，统一按挑战杯 XH-202620 计算机学科垂类大模型方向定位；原 A12 参赛技术文档与 T2606981 项目方案 PDF 从仓库移除（历史见 git）。

* **2026-08-20**：README 更新：项目定位统一为"让课程回应学习：知识图谱驱动的可追溯智能教学系统"，新增三项核心机制、五层架构、多智能体协作、AI 安全围栏、云端部署与验证状态章节。

* **2026-08-12**：新课程默认开放知识图谱、证据、认知分析和安全策略配置；当前「实验平台」仅接入代码沙箱，因此 `experiment`/`coding_sandbox` 默认关闭，须由教师按课程显式启用。课程设置中的智能体策略仅保留已被教学问答运行时消费的 `enabled` 启动开关；逐工具治理继续由独立 `AgentToolPolicy` 链路负责，尚未在课程设置页提供配置入口。平台 `ADMIN` 权限在所有课程持有成员列表不可见的「课程所有者」身份（`course_role=owner`、无成员关系），facade 首页与建设列表对管理员返回全部课程（含草稿）以便修改不合规课程。

* **2026-08-11**：课程导入走受管异步路径（解析先行 → GraphRAG 草稿排队教师审核 → 授权后激活 LanceDB/BGE）；平台管理员可配置任务并发。初始备课若个别讲稿未通过证据校验或模型漏项，保留其余草稿并标记 `partial_success`，由教师在讲稿页手工补齐；未覆盖/空讲稿是不可确认绕过的发布 BLOCKER。

* **2026-08-11**：PPT manifest 改为缓存优先的后台 `media.ppt_manifest` 任务：复用映射阶段页图、仅补渲染缺页、记录安全页数进度；激活不再同步触发 LibreOffice 渲染。

* **2026-08-11**：课程建设助教自由文本改由 Prep 结构化意图路由器按完整语义选择既有五种 action，移除关键词兜底；低置信度/范围不明请求只澄清或返回 `PREP_AGENT_INTENT_UNAVAILABLE`。明确按钮 action 仍绕过分类器；一键整理结构/优化讲解在 batch API 前写入带授权标识的本地用户消息，批量原子应用与单节点待审核提案语义保持不变，无数据库迁移。

* **2026-08-10**：智能备课材料证据 Map/Reduce 调用预算 64→160，证据 ID 服务端确定性回填；平台女性讲师成为默认 2D 角色；课程 87 Demo 发布版本本地 Chrome 播放回归通过。

* **2026-08-09**：账户名称收敛为唯一 `username`；Ubuntu 部署基线（LanceDB/PaddleOCR/GraphRAG Worker/Judge0）审计完成，GraphRAG/Judge0 fail-closed。

* **2026-08-12**：ResearchAgent 的真实部署数据库兼容基线确认为 PostgreSQL 16.14 + pgvector 0.7.4；vector 类型、`<=>` 余弦运算符与 Alembic `0053` 五张工作区表均只读验收。运行时将 pgvector SQL 不可用降级为关键词检索，不修改数据库配置或服务。

* **2026-08-13**：TeachingAgent 学习调整 P0 增加 release-pinned 回顾提案与学习者确认的返回锚点；`applied` 仅表示已接受回顾，不表示浏览器跳转成功。泛雅兼容 `/progress/adjust` 不再根据外部理解等级伪造建议，只有关联同一学习者、课程、有效冻结目标及已持久化助手回答的真实回合才返回补充内容；否则明确返回 `503`。本地定向测试已通过，浏览器人工验收和部署仍待执行。

* **2026-08-11**：ResearchAgent Harness v1（真实条件 LangGraph、科研工作区、Todo/Notepad/Scope/Memory、pgvector 迁移与五视图前端）；多源检索、全文、写作与完整仓库复现仍未接通。

* **2026-08-07**：ResearchAgent P0（arXiv 检索）；Stage 8 Provider 配置基线（`MEDIA_DEMO_MODE`）；P5.1 音色/角色注册表、P5.2 OSS 隔离；统一学习数据链（`learning_events` + `/facade`）。

***

*本 README 的所有功能状态均可回溯至代码证据。*
