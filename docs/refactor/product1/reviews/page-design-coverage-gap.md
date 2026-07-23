# page-design 设计稿 × 现有系统：功能覆盖度与接口依赖缺口分析

> **对象**：前端设计稿 `page-design(1).md`（v0.4，29 章）× 现有系统（稳定版 V1 + 影子版 V2-shadow + 实验版 canary/demo）
> **代码库**：`E:/smartcarb/ai-course-system`
> **分析时间**：2026-07-23
> **核实方式**：逐文件读 `main.py` 路由注册、`router/index.js`、`featureFlags.js`、契约 `registry.md`、各端点 handler 与响应模型；不臆断。
> **前置审计**：`research-report-frontend-verification.md`、`knowledge-graph-rag-implementation-audit.md`、`graph-browser-implementation.md` 三份均聚焦图谱/RAG，**未覆盖全局路由覆盖度**——本报告补此空白。
> **后续更新**：见 §7（c25172e0 R2 sidecar 真实化 + 主链接入）。

---

## 0. TL;DR（最关键的三条结论）

1. **路由层级整体不对齐（最大缺口）**：page-design 定义的是全新 `/app` 信息架构（`/app`、`/app/courses/*`、`/app/lab/*`、`/app/resources/*`、`app/tasks/*`、`/app/course/:courseId/{overview,learn,build,knowledge,experiments,members,settings}`）。**现有前端 router 实际仍是 M7 基线的扁平结构**（`/teacher/*`、`/student/*`、`/player/*`、`/admin`、`/evidence-viewer`、`/graph-browser`）。page-design 的 L1/L2/课程内二级页面在前端**几乎都不存在对应路由**——这不是字段缺口，是信息架构层面的代差。

2. **5 个后端"端点文件"是未挂载的孤儿**：`codebench.py`、`cognitive.py`、`graphrag.py`、`visualization.py`、`agents.py` 头部都写着"XXX 接口端点"，但 `main.py` 从未 `include_router` 它们，`router.py` 仅是空注释。意味着 page-design 的**代码实验台、认知判断、GraphRAG、可视化、智能体**五大域在运行系统中**不暴露任何 HTTP 端点**。前端恰好也有对应的孤儿视图（`CodeBenchView.vue`/`CognitiveDashboardView.vue`/`VisualizationView.vue` 存在但无路由）——前后端对称的"原型阶段产物，均未接线"。

3. **影子/实验版接口已对齐但全是"空壳数据"**：`evidence-v2`/`document-v2`/`canary-v2`/`retrieval-demo` 端点、前端 `evidence.js`/`graph-browser`/`retrieval-demo` 客户端、7 面影子旗 + 依赖级联降级——**接口契约与调用链已对齐**（冻结 `internal-evidence-api/1.0` 等 14 契约），但 V2 影子用 fake/offline provider（仅 safety 用真 evaluator），evidence-v2 在 G4 默认返回**空列表/abstain**，canary 的 `model_quality` 恒为 `NOT_EVALUATED`，G5B 真模型 canary **阻塞**。即"管线通了，水没接"。

---

## 1. 功能映射表

状态口径：✅ 已支持（端点真实可用）/ ⚠️ 部分支持（有端点但不完整或孤儿未挂载）/ ❌ 无接口

### 1.1 平台一级空间 L1（page-design §2.1、§7、§8）

| page-design 页面 | 推荐路由 | 前端路由 | 后端接口 | 状态 |
|---|---|---|---|---|
| 公开产品展示首页 | `/` | `/` -> `Home.vue` | 无后端依赖（静态叙事） | ✅ |
| 登录后工作首页 | `/app` | **无 `/app`**（最接近的是 `/student`->`StudentDashboard`、`/teacher/history`） | `GET /api/v1/document/my-courses`、`/courses`（document.py:771/680） | ⚠️ 首页存在但路由名不对、内容未按"继续进行/需要处理/系统回应/最近内容"四区组织 |
| 我的课程 | `/app/courses` | **无** | `GET /document/courses`、`/my-courses`、`document_course.py /courses` | ⚠️ 后端有课程列表，但无"我学习的/我建设的/课程大厅"三分区聚合接口 |
| 实验室 | `/app/lab` | **无**（`CodeBenchView.vue` 存在但无路由） | `codebench.py` **未挂载** | ❌ |
| 资源库 | `/app/resources` | **无**（`Edulib.vue` 是教材库，非资源库） | `asset.py`（F1 素材）部分覆盖 | ⚠️ 素材管理有，文件/文件夹/回收站/课程引用无 |
| 任务中心 | `/app/tasks` | **无** | 无独立 task router；仅 `video_generation /task/{id}`、`ppt /task/{sid}` | ❌ 无统一任务中心 |
| 平台管理 | `/app/admin` | `/admin` -> `AdminPanel.vue`（admin-only） | `user.py /list`、`/role`、`/stats`；`platform.py` 泛雅同步 | ⚠️ 用户管理有，平台级治理弱 |

### 1.2 课程内部二级页面（page-design §10、§11–§18）

| page-design 页面 | 推荐路由 | 前端路由 | 后端接口 | 状态 |
|---|---|---|---|---|
| 课程概览（学生/教师） | `/app/course/:id/overview` | `/student/course/:id`、`/teacher/course/:id`（Dashboard 而非概览） | `GET /document/course/{id}`、`/stats`、`/students` | ⚠️ 数据有，但非"概览页"结构 |
| 课程学习（Adaptive Canvas） | `/app/course/:id/learn` | `/player/course/:id` -> `StudentPlayer`（flag 开则 `StudentLearningWorkspace`） | `GET /player/init/{id}`、`/knowledge-points/{id}`、`POST /progress/save`、`/prerequisite/jump` 等 | ⚠️ 核心 LEARN+UNDERSTAND 有；PRACTICE/VISUALIZE/NOTE/VERIFY 缺 |
| 教师建设 | `/app/course/:id/build` | `/teacher/course/:id/production`、`/mapping`（flag-gated） | `document.py`（资料/结构/讲稿/映射/媒体/发布全链）、`mapping.py`、`ppt`、`video-gen`、`document_tts` | ✅ 建设链路最完整（见 1.4） |
| 课程知识空间 | `/app/course/:id/knowledge` | `/graph-browser/:id`（admin-only，flag-gated）；`Knowledge.vue` 无路由 | `knowledge.py`（知识点/关系）、`mapping.py`；`graphrag.py` **未挂载** | ⚠️ 知识点 CRUD 有，图谱浏览器仅 admin 影子，候选审核/版本记录无 |
| 实验任务 | `/app/course/:id/experiments` | **无** | `codebench.py` **未挂载** | ❌ |
| 成员 | `/app/course/:id/members` | **无** | `document.py /enroll`、`/unenroll`、`/students` | ⚠️ 直接选课+学生列表有；加入申请/分组/泛雅成员同步无 |
| 设置 | `/app/course/:id/settings` | **无** | `document.py /course/{id}/save`（基础信息）、`platform.py`（集成）；安全/沙箱设置无 | ⚠️ 基础信息+发布有，安全合规/沙箱/智能体配置无 |

### 1.3 课程学习页状态机（page-design §12.3，最核心链路）

| 学习状态 | 触发 | 前端 | 后端接口 | 状态 |
|---|---|---|---|---|
| LEARN 正常讲解 | 默认 | `StudentPlayer`/`StudentLearningWorkspace` | `GET /player/init/{id}` | ✅ |
| UNDERSTAND 提问 | 点"提问" | `chat.js askQuestion` | `POST /chat/ask`（返回 answer+ragSources+understanding） | ✅ |
| PRACTICE 试一试 | 点"试一试" | 无 | `codebench.py` **未挂载** | ❌ |
| VISUALIZE 看可视化 | 点"看可视化" | `VisualizationView.vue` 无路由 | `visualization.py` **未挂载**；仅 `progress.py /visualization/{id}` | ❌ |
| NOTE 做笔记 | 点"做笔记" | 无 | 无笔记接口 | ❌ |
| CITATION 原文引用 | 点"原文引用" | `evidence-viewer`（admin-only，flag-off） | `evidence_v2.py`（默认 503，开则空列表） | ⚠️ 契约通，数据空 |
| VERIFY 验证完成 | 完成条件满足 | 无 | 无 | ❌ |
| 学习分支返回 | 进入分支 | `prerequisite.js` | `POST /prerequisite/jump`、`/return`、`GET /jump-stack` | ✅ 返回上下文最完整 |

### 1.4 教师建设 Local Rail（page-design §14，建设链路最完整）

| 建设子页 | 后端接口 | 状态 |
|---|---|---|
| 资料 | `POST /document/upload`、`/analyze`、`document_upload.py` | ✅ |
| 课程结构 | `POST /document/course/{id}/save`、`GET /course/{id}` | ✅ |
| 教学讲授（讲稿） | `POST /document/course/{id}/script/snapshot`、`GET /script/versions`、`POST /script/rollback/{id}` | ✅ 讲稿版本+回滚完整 |
| 页面映射 | `mapping.py`（GET/auto/ai-match/put/batch/apply） | ✅ |
| 媒体生成 | `document_tts`、`video_generation`、`ppt_generation` | ✅ TTS/视频/AI-PPT 三类 |
| 课程校验 | **无独立质量门禁接口** | ❌（仅 canary_v2 是影子质量门，非建设发布门禁） |
| 发布记录 | `POST /document/course/{id}/publish`、`/unpublish`；讲稿有 versions/rollback，但**课程发布无版本记录/回滚** | ⚠️ 发布有，版本记录/回滚无 |

---

## 2. 缺口清单（按 P0–P2 优先级）

> 优先级口径：P0 = 阻塞 page-design §28 P0 核心链路或破坏可信/安全边界；P1 = §28 P1 知识与实验/平台支撑；P2 = §28 P2 后续增强。

### P0 - 阻塞核心链路 / 信息架构代差

| # | 缺失接口/能力 | 影响范围 | 依据 |
|---|---|---|---|
| P0-1 | **`/app` 信息架构路由体系**（首页/课程/实验室/资源库/任务/课程内 7 二级页） | 全站。前端仍是 `/teacher`/`/student`/`/player` 扁平结构，page-design 的 L1/L2/Local Rail 无法落地 | `router/index.js` 全文无 `/app`；page-design §2、§4 |
| P0-2 | **代码实验台 + Coding Agent 端点**（PRACTICE 试一试、§13 Coding Agent、§19 实验室、§5.4 实验工作区） | 学习状态机 PRACTICE 缺失；实验任务/实验室整域不可用 | `codebench.py`/`agents.py` 未 `include_router`（main.py 无注册） |
| P0-3 | **可视化端点**（VISUALIZE 看可视化、§7.C 图谱浏览器交互） | 学习状态机 VISUALIZE 缺失；首页图谱浏览器无真实交互端点 | `visualization.py` 未挂载；`graphrag.py` 未挂载 |
| P0-4 | **加入课程申请审核流程**（apply/approve/reject/pending，§9.4、§17.3） | 课程大厅加入方式（申请审核/邀请码）无法实现；成员管理缺审核 | `document.py /enroll` 是直接选课，grep 无 apply/approve/reject 语义 |
| P0-5 | **课程发布版本记录 + 回滚**（§14.9 发布记录、§15.5 版本记录） | 教师建设发布链缺可追溯/回滚；page-design 反复强调"版本可回滚" | 讲稿有 versions/rollback，但课程级 publish 无版本记录接口 |
| P0-6 | **课程校验质量门禁**（§14.8 课程校验 9 组校验） | 发布前无集中质量门禁；"阻断项禁止发布"无法执行 | 无独立 validation 端点（canary_v2 是影子质量门，非发布门禁） |

### P1 - 知识与实验 / 平台支撑

| # | 缺失接口/能力 | 影响范围 | 依据 |
|---|---|---|---|
| P1-1 | **统一任务中心**（todo/created/system/completed，§21） | 无用户待办、系统任务、失败任务重试/日志入口 | 无 task router；仅散落的 video/ppt task 端点 |
| P1-2 | **资源库**（文件/文件夹/最近/回收站/课程引用，§20） | 资源管理缺文件夹/回收站/引用关系 | `asset.py` 仅素材 CRUD，无 folder/trash/recent |
| P1-3 | **笔记接口**（NOTE 做笔记，§12.8） | 学习状态机 NOTE 缺失 | 无 notes 端点 |
| P1-4 | **VERIFY 验证完成 + 学习证据写回**（§12.10） | 实验完成后无法记录证据/返回课程 | `learning_shadow` 是影子 append-only，非正式写回 |
| P1-5 | **知识候选审核**（accept/reject/modify AI 候选，§15.4） | AI 候选无法教师确认进正式结构 | `knowledge.py` 无候选状态机（PROPOSED/ACCEPTED 在 edu-graph/1.0 契约有，但无审核端点） |
| P1-6 | **认知判断接口**（§7.E 学习证据与认知判断、§11.2C 学习信号） | 首页/概览的"系统回应/学习信号"无数据源 | `cognitive.py` 未挂载；`learning/1.0` MasteryState 契约存在但无暴露端点 |
| P1-7 | **安全合规 + 沙箱权限配置**（§18.5、§18.6） | 教师无法配置课程安全策略/沙箱预设 | `safety_dryrun_shadow` 是影子且 `v1_blocked=False` 永不阻断；无正式安全策略配置端点 |
| P1-8 | **成员分组 + 泛雅成员同步预览**（§17.4、§17.5） | 分组/同步预览缺失 | `platform.py` 有 syncEnrollment 但无分组、无"同步前预览变化" |

### P2 - 后续增强（page-design §28 明确后置）

| # | 缺失接口/能力 | 影响范围 |
|---|---|---|
| P2-1 | SSE 流式检索 / RetrievalTrace 回放（§7.D 多图 RAG 动画） | 前后端均无 EventSource/StreamingResponse |
| P2-2 | 图谱版本冲突治理（§15.5 版本对比、§22.7 Conflict） | GraphSnapshot 契约有 active pointer 可回退，但无冲突对比端点 |
| P2-3 | CTF 隔离靶场（§18.5、§27.5） | 沙箱预设枚举在 page-design 有，后端无 CTF 隔离环境实现 |
| P2-4 | 真实 canary（G5B）解锁 dense/vector/rerank | G5B 阻塞于 CLAUDE.md 约束（依赖安装/付费服务） |
| P2-5 | 教师预览学生视角（§1.4） | 无"预览模式"标记/不写正式进度的端点语义 |

---

## 3. 数据字段差异（已支持接口的前端所需 vs 后端返回）

### 3.1 `POST /api/v1/chat/ask`（UNDERSTAND 提问，核心）

| 前端所需（page-design §6.7 SystemResponsePanel、§12.5） | 后端返回（chat.py:148-156） | 差异 |
|---|---|---|
| 系统观察/依据/建议动作/可接受修改 | `answer`(str) | ⚠️ 缺"依据""建议动作"结构化字段 |
| 原文引用（来源类型/文件名/页码/片段/关联说明/状态） | `ragSources`(list，仅 path+content+score) | ⚠️ 缺 source_type/page_number/document_version/publish_status/引用状态 |
| 检索轨迹（阶段/耗时） | 无 `retrieval_trace` | ❌ 无结构化 trace（audit 报告已确认） |
| 理解度判断 | `understanding.level`/`score`(已返回) | ✅ |

### 3.2 `GET /api/v1/player/init/{course_id}`（LEARN 正常讲解）

| 前端所需（§12.2、§6.9 LearningTrack） | 后端返回（player.py:32 PlayerInitData） | 差异 |
|---|---|---|
| 课程名/章节/知识点/完成状态/当前节点/返回点 | course_title/nodes(含 node_id/chapter/title/timestamp/index/is_completed)/saved_progress | ✅ 基本齐全 |
| PPT 逐页内容/图片 | ppt_pages/slide_images | ✅ |
| 知识点跳转权限（教师允许时） | `GET /player/knowledge-points/{id}` 有 | ✅ |

### 3.3 `GET /api/v1/evidence-v2/documents/{id}/evidence`（CITATION，影子）

| 前端所需（§6.8 CitationBlock） | 后端契约（evidence/1.0 EvidenceSpan） | 差异 |
|---|---|---|
| 来源类型(PPT/教材/讲义…) | 无 `source_type` 字段 | ⚠️ 缺（audit 已确认） |
| 文件名/资料名 | `artifact_id`/`document_id`（是 ID 非名） | ⚠️ 需前端二次解析名 |
| 页码/章节 | `page_or_slide` | ✅ |
| 引用片段 | `text_snippet` | ✅ |
| 引用状态(精确/近似/失效/已更新) | `status`(ACTIVE/STALE/SUSPENDED) | ⚠️ 语义部分对应，需映射 |
| publish_status | **无** | ❌ 缺（audit + graph-browser 报告均列为 P0） |
| retrieval_score | `score` | ✅ |
| document_version | `version_ref` | ✅ |

> 注：G4 默认该端点返回**空列表/abstain**，所以字段差异当前不影响实际数据，但 G5B 解锁真数据后会暴露 `publish_status`/`source_type` 缺口。

### 3.4 `GET /api/v1/mapping/{course_id}`（页面映射，教师建设）

| 前端所需（§14.6） | 后端返回（mapping.py） | 差异 |
|---|---|---|
| 节点↔页范围映射 | node_id/page_start/page_end | ✅ |
| 映射状态(已映射/部分/未映射/冲突/来源失效) | 无显式状态字段 | ⚠️ 需前端推导 |
| 多来源片段 | 单 page_start/end | ⚠️ 不支持多片段（§14.6 要求"添加多个来源片段"） |

---

## 4. 版本差异（稳定版 / 影子版 / 实验版）

> 口径：**稳定版** = main.py 注册的 13 个 V1 router（M7 基线）；**影子版** = V2-shadow（document_v2/evidence_v2 + platform/shadow 6 模块，7 旗管控，默认 off，fake provider）；**实验版** = canary G5A + retrieval-demo（admin-only，框架级，无真实模型数据）。

| 能力域 | 稳定版 V1 | 影子版 V2-shadow | 实验版 canary/demo |
|---|---|---|---|
| 文档解析 | ✅ document.py upload/analyze（真解析） | ✅ doc_shadow（fake，映射 V1->document-ir/1.0，默认 off） | ✅ canary 框架跑（fake 输入） |
| 证据/引用 | ❌（chat 仅返回 ragSources 路径+content） | ✅ evidence_v2（c25172e0 后：有 sidecar 课程可返回**非空** Evidence + Citation 校验；无 sidecar 仍空） | ✅ canary 框架（无真数据） |
| 引用校验 | ❌ | ✅ citations/validate（abstain/no_evidence） | ✅ canary 框架 |
| 页面图像渲染 | ✅ document.py /slide/{page_num}（V1 有） | ⚠️ evidence_v2 /pages/{n}/image 返回 503 `PAGE_RENDERING_NOT_AVAILABLE_IN_G4` | - |
| 知识图谱 | ⚠️ knowledge.py 知识点/关系 CRUD（无图谱浏览） | ✅ graph_shadow（fake，InMemoryGraphStore，PROPOSED 状态，默认 off） | ✅ canary 框架 |
| 学习事件 | ✅ progress.py（V1 进度写回） | ✅ learning_shadow（fake，append-only，默认 off） | ✅ canary 框架 |
| 学生记忆 | ❌ | ✅ memory_candidate_shadow（fake，would_inject=False，默认 off） | ✅ canary 框架 |
| 安全治理 | ❌ | ✅ safety_dryrun_shadow（**真** P1-08 evaluator，v1_blocked=False，默认 off） | ✅ canary 框架 |
| 质量门禁 | ❌ | - | ✅ canary_v2 quality_gate（3 维度，model_quality 恒 NOT_EVALUATED） |
| 检索演示 | ❌ | - | ✅ retrieval-demo（admin-only，DEMO_RETRIEVAL_MODE 独立旗，dev/test 环境） |
| 代码实验台/Coding Agent | ❌ | ❌ | ❌（codebench.py/agents.py 未挂载，三版全无） |
| 认知模型 | ❌ | ❌ | ❌（cognitive.py 未挂载） |
| 可视化 | ⚠️ 仅 progress.py /visualization/{id} | ❌ | ❌（visualization.py 未挂载） |

**关键版本差异结论**：
- **影子版已支持但稳定版未上线**：证据/引用、引用校验、知识图谱候选、学生记忆、安全治理、学习事件结构化——这 6 块在 V1 稳定版完全不存在，仅以影子形式（默认 off + fake）存在于 V2。
- **R2 检索主链接入（本次新增）**：`qa_service.ask_question_with_rag` 现在在 V1 检索后、LLM 前插入 R2 sidecar 影子 seam；`DOCUMENT_KG_RUNTIME_MODE=v2_shadow` 且课程有 sidecar 时，R2（BM25+BGE Dense+RRF+Citation 闭环）替换 V1 检索喂给 LLM；默认 v1_only = 纯 V1 不变，fail-closed 回落。学生提问主链从"V1 TreeRAG 独占"变为"旗控可选 R2"。
- **三版全无**：代码实验台、Coding Agent、认知模型、可视化（独立）——这四个 page-design 核心域连影子都没有，是真正的"零实现"。
- **影子版的"已支持"是契约级而非数据级**：evidence-v2 端点存在且契约冻结，但 G4 返回空/abstain，真数据要等 G5B 解锁真 provider。

---

## 5. 依赖风险（调用顺序 / 并发 / 超时 / 旗级联）

| # | 风险 | 说明 | 依据 |
|---|---|---|---|
| R-1 | **前端 5 旗 + 后端 7 旗 + 环境 2 旗的多层 gate 不一致** | 前端 `studentLearningWorkspace`/`teacherProductionWorkspace`/`knowledgeMappingWorkspace`/`graphBrowser`/`retrievalDemo` 默认全 false；后端 7 旗默认 v1_only/disabled。**前端旗开但后端旗关**会导致前端调 evidence-v2 拿 503，且无统一降级提示 | featureFlags.js + feature_flags.py |
| R-2 | **影子旗依赖级联降级，前端无法预知** | 后端 `STUDENT_MEMORY_MODE` 依赖 `LEARNING_EVENT_MODE`，`EVIDENCE_CITATION_MODE` 依赖 `DOCUMENT_KG_RUNTIME_MODE`->`DOCUMENT_PIPELINE_VERSION`。前端开启某旗但上游未 v2 时，后端静默降级到 V1 + `fallback_reason`，前端可能显示"已启用"实则空跑 | feature_flags.py DAG |
| R-3 | **evidence-viewer 三接口并发 `Promise.allSettled` 但 page-image 必 503** | `EvidenceViewerPage.vue` 用 `Promise.allSettled` 并发拉 evidence/citations/pages，但 `/pages/{n}/image` 在 G4 恒返回 503 `PAGE_RENDERING_NOT_AVAILABLE_IN_G4`，导致持续部分失败（虽 fail-closed 不崩，但用户体验为"永远缺图"） | evidence_v2.py + audit 报告 |
| R-4 | **QA 链路无超时治理** | `POST /chat/ask` 同步调用 LLM，无 SSE/流式，长问题易超时；影子 evidence_shadow 有 60s 超时但 V1 主链路无显式超时 | chat.py + qa_service.py |
| R-5 | **学习分支返回依赖 jump-stack 状态，跨标签页/刷新丢失** | `prerequisite/jump`+`/return`+`/jump-stack` 是进程内栈，page-design §12.11 要求 `return_target` 持久化以保证返回正确位置；当前栈在刷新后可能丢上下文 | prerequisite.py |
| R-6 | **建设链路多接口无原子性** | 资料->结构->讲稿->映射->媒体->发布是 6 步，任一步失败无事务回滚；page-design §22.4 Partial Success 要求显示成功/失败明细，当前发布 `/publish` 无批量结果返回 | document.py publish |
| R-7 | **孤儿文件误导"能力存在"判断** | codebench/cognitive/graphrag/visualization/agents.py 存在于 endpoints 目录，易被误判为"已实现"。前端对应视图也存在但无路由。**风险：照文件清单估工时会严重低估实际接线量** | main.py 未 include_router |

---

## 6. 建议行动（短期 / 长期）

### 短期（1–2 个迭代，对齐 §28 P0 + 消除信息架构代差）

1. **路由架构迁移先行（P0-1）**：在 `router/index.js` 引入 `/app` 体系，将现有 `/teacher`/`/student`/`/player` 作为 flag-off 的 legacy 回落（复用已有 `featureFlags` + 回落模式，与 evidence-viewer/graph-browser 同纪律）。**不要新建第二套页面**，而是给现有 Dashboard/Player 套上 `/app/course/:id/*` 的 URL 外壳 + 二级导航 + Local Rail。这是阻塞其他所有页面验收的前置。

2. **挂载 5 个孤儿端点或明确标记"实验能力"（P0-2/P0-3/P1-6）**：对 `codebench.py`/`visualization.py`/`cognitive.py`/`agents.py`/`graphrag.py` 二选一：(a) 补 `include_router` 并加 admin-only + flag（最小成本让能力可访问）；(b) 若实现不完整，按 page-design §0.1 + §6.11 `CapabilityMaturityTag` 标"实验能力/研究预览"且**不挂路由**（合规克制，符合"不伪造"纪律）。**禁止维持现状的"文件在、路由不在、能力似有似无"**。

3. **补加入申请审核流程（P0-4）**：在 `document.py` enroll 旁新增 `POST /course/{id}/join-request`、`GET /course/{id}/join-requests`、`POST /join-request/{id}/{approve|reject}`，复用 `Course` 模型扩展 join_method 字段。这是课程大厅 + 成员管理两个页面的共同阻塞。

4. **课程发布版本记录（P0-5）**：仿照讲稿 `script/versions`+`rollback` 模式，给 `document.py /publish` 增加 `GET /course/{id}/publish-versions` + `POST /course/{id}/rollback/{version}`。讲稿已有可复用模式，成本低。

5. **evidence 链补 `publish_status`/`source_type`（§3.3 字段缺口）**：`course_model.py` 已有 `CourseStatus`，需贯穿到 `EvidenceSpan`/`RetrievedChunk`。这是 audit 与 graph-browser 两份报告共同列的 P0，G5B 解锁真数据前必须补，否则前端 CitationBlock 无法显示来源状态。

6. **统一旗状态端点**：新增 `GET /api/v1/feature-flags/effective` 返回后端 7 旗 + 级联降级后的 effective 值 + fallback_reason，供前端 `featureFlags` 同步，消除 R-1/R-2 的前后端旗不一致。

### 长期（对齐 §28 P1/P2 + G5B 解锁）

7. **统一任务中心（P1-1）**：抽象 `task` 聚合层，归一 video/ppt/tts/sync 异步任务为 `TaskResult`/`TaskStatus`（契约已 consumed），前端 `generation_tasks.js` 扩展为全任务中心客户端。

8. **资源库 + 笔记 + VERIFY 证据写回（P1-2/P1-3/P1-4）**：资源库在 `asset.py` 上扩 folder/trash/recent；笔记新建 `notes` 端点；VERIFY 把 `learning_shadow` 从影子 append-only 升级为正式学习证据写回（依赖 G6 v2_preferred）。

9. **知识候选审核端点（P1-5）**：`edu-graph/1.0` 契约已有 `ReviewStatus`(PROPOSED/ACCEPTED/REJECTED)，补 `POST /knowledge/candidates/{id}/{accept|reject|modify}` 端点，让 graph_shadow 的 PROPOSED 节点可被教师确认进正式结构。

10. **安全合规 + 沙箱配置正式化（P1-7）**：把 `safety_dryrun_shadow`（当前 v1_blocked=False 永不阻断）升级为可配置课程安全策略 + 沙箱预设的正式端点，对接 page-design §18.5 三层边界。

11. **G5B 解锁真 provider（P2-4）**：按 canary 文档固定顺序 Docling->PaddleOCR->Embedding->Reranker->LLM 逐项人工 gate，解除 CLAUDE.md 约束后接真模型，让 evidence/graph/检索 trace 有真数据，graph-browser 的 RetrievalTracePanel 才能从"显式空态"变为真实轨迹。

12. **SSE 流式 + RetrievalTrace 回放（P2-1）**：G5B 之后补 `trace_schema_version=1` + `/graph/replay` + `StreamingResponse`，完成 audit 报告 V1 最低闭环。

---

## 7. 后续进展：c25172e0 R2 sidecar 真实化 + 主链接入（2026-07-23）

提交 `c25172e0`（`feat(shadow): retrieve test-course evidence sidecars with R2`）后，本报告 §0/§4 中"影子版全是空壳数据"的判定需要部分修正。

### 7.1 RAG 检索：从演示面真实化到主链接入

**c25172e0 做了什么**（演示面真实化）：
- retrieval-demo 的 provider 从退役 fixture 升级为 `CourseSidecarR2Provider`（`platform/retrieval_demo/course_provider.py`），是**真实**实现：本地 BM25（`src.bm25`）+ 本地 BGE Dense（`src.dense.BgeSmallZhEmbedder`，带模型权重 sha256 校验）+ RRF 融合（`src.rrf.fuse`），命中带 Evidence ID/页码/块 ID/Citation key 并做 citation 闭环校验。
- 成功解析后自动生成 `DocumentIR -> 课程隔离 Evidence sidecar`；R2 仅消费该 sidecar，不读 qrels/Reviewed Silver/生产 ORM。
- `evidence_v2` 端点可返回**非空** sidecar Evidence 并校验 Citation（修正 §4"Evidence 返回空列表/abstain"）。
- R3 图扩展永久关闭（`GRAPH_EXPANSION_PRODUCTION_CANDIDATE_ENABLED=false`），不参与检索（见 `docs/research/graph_retrieval/生产检索基线决议_R2_RRF.md`）。
- 边界：retrieval-demo 全部 `admin_only`，前端"deliberately not mounted inside Chat/StudentPlayer"，**V1 主链未变**。

**本次（c25172e0 之上）做了什么**（主链接入）：
- 新增 `platform/shadow/r2_retrieval_shadow.py`：`trigger_r2_retrieval_shadow` 在 `qa_service.ask_question_with_rag` 的 V1 检索后、LLM 前 seam 触发，沿用 G3C evidence_shadow 纪律。
- `DOCUMENT_KG_RUNTIME_MODE=v2_shadow` 且课程有 sidecar 且 R2 返回 citation-closed 命中时，R2 检索结果**替换**喂给（唯一一次、仍 V1 的）LLM 调用的 `rag_context`/`rag_sources`；无 second LLM call。
- 默认 `v1_only` = 纯 V1 TreeRAG，行为与接入前**完全一致**；无 sidecar/R2 abstain/运行时异常一律 `triggered=False` 回落 V1（business fail-closed）。RISK-03：无 course_id 不全局检索。
- `qa_service` 返回新增 `retrieval_source`（`none`/`v1_treerag`/`v2_r2_sidecar`）元信息，向后兼容。
- 测试：`backend/tests/demo_shadow/test_r2_retrieval_shadow_mainline.py`（8）+ `test_smoke_mainline_default.py`（1）= 9 passed，覆盖旗 off/上游冲突/无 sidecar/R2 ok/R2 abstain/provider 异常 fail-closed/无 scope/llm_calls==0/默认 V1 不变。

### 7.2 判定更新

| 维度 | §0/§4 原判定 | c25172e0 + 主链接入后 |
|---|---|---|
| RAG 检索（BM25+Dense+RRF） | retrieval-demo 用 fake fixture | **演示面 + 主链均已真实接入**（主链旗控，默认 V1） |
| Evidence/Citation | evidence-v2 返回空/abstain | 有 sidecar 课程可返回非空 + Citation 校验 |
| 图谱接入检索 | graph_shadow 影子 | **决议排除**（R3 永久关闭，非生产候选） |
| 学生提问主链 | V1 TreeRAG 独占 | 旗控可选 R2；默认仍 V1（行为不变） |
| page-design §12.5 提问拿带 Citation 的 RAG 回答 | ❌ | ⚠️ **后端链路通**（旗开+有 sidecar 时），但前端 `/chat/ask` 仍按 V1 渲染、未消费 `retrieval_source`；学生端默认 flag off |

### 7.3 仍未解决（沿用 §2/§5 编号）

- **图谱 + RAG 整体仍不算"工程接入"**：图谱被决议排除出检索，R2 未含图谱扩展。page-design §7.C/§15 的图谱浏览交互仍无真实图谱检索端点支撑。
- **P0-1 路由代差未动**：`/chat/ask` 主链虽接入 R2，但前端 router 仍是 `/teacher`/`/student` 扁平结构，page-design 的 `/app/course/:id/learn` 不存在。
- **R-1/R-2 旗不一致未解**：主链接入复用 `DOCUMENT_KG_RUNTIME_MODE`，但前端无对应旗同步；学生端默认 flag off，R2 主链在学生提问路径上默认不生效（符合影子纪律，但意味着学生当前拿不到 R2 回答）。
- **G5B 真模型 canary 仍阻塞**：R2 用的是本地真 BGE 模型（非 fake），但 canary 的 `model_quality` 维度仍恒 `NOT_EVALUATED`，回答质量/abstain 校准未做。

### 7.4 证据

- 提交：`c25172e0`（R2 sidecar 演示面）+ 本次主链接入提交
- 核心：`backend/app/platform/shadow/course_evidence_sidecar.py`、`backend/app/platform/retrieval_demo/course_provider.py`、`backend/app/platform/shadow/r2_retrieval_shadow.py`（新）、`backend/app/services/qa_service.py`（seam）
- 决议：`docs/research/graph_retrieval/生产检索基线决议_R2_RRF.md`
- 测试：`backend/tests/demo_shadow/test_r2_retrieval_shadow_mainline.py`、`test_smoke_mainline_default.py`（9 passed）

---

## 附：判定依据索引

- **路由注册**：`backend/app/main.py`（16 个 include_router，13 V1 + 4 V2/shadow）
- **孤儿文件**：`codebench.py`/`cognitive.py`/`graphrag.py`/`visualization.py`/`agents.py` 头部"接口端点"但 main.py 未注册；`router.py` 空注释
- **前端路由**：`frontend/src/router/index.js`（无 `/app`，扁平 `/teacher`/`/student`/`/player`/`/admin`/`/evidence-viewer`/`/graph-browser`/`/demo/retrieval`）
- **前端旗**：`frontend/src/config/featureFlags.js`（5 旗默认 false）
- **契约**：`docs/refactor/product1/contracts/registry.md`（14 契约 frozen-major，G1–G4）
- **影子模块**：`backend/app/platform/shadow/*`（6 模块，fake provider 除 safety）+ `core/feature_flags.py`（7 旗 + DAG + fail-fast/fail-closed）
- **字段形状**：`chat.py:148-156`、`player.py:32`、`mapping.py:25`、`evidence/1.0` EvidenceSpan、`retrieval/schemas.py` RetrievedChunk
- **前置审计**：`research-report-frontend-verification.md`、`knowledge-graph-rag-implementation-audit.md`、`graph-browser-implementation.md`（三份均聚焦图谱/RAG，未覆盖全局路由覆盖度——本报告补此空白）
