# ADR-0006: Product 1 V2 Shadow 集成顺序、隔离边界与回滚策略

- 状态: Proposed（草案，待人工审批）
- 日期: 2026-07-14
- 决策者: P1-00（起草），P1-09（执行），人工审批（启动前）
- 影响范围: G3 Shadow Integration 全程；P1-09 独占的共享生产文件
- 性质: **方案文档，不修改任何 ORM、Migration、公开 API、生产 endpoint、公共配置或前端共享文件**。审批通过后 P1-09 方可按本 ADR 执行。

## 0. 前置：复核结论

冻结点 `1cf0269` 已通过 P1-00 只读整体复核（见 `docs/refactor/product1/reviews/review-1cf0269-pre-g3.md`）：
- 工作区干净，9 agent 分支全合流，13 契约 frozen-major，跨域依赖无循环，663+116 测试可重现零回归。
- P1-09 共享生产文件零触及；P1-10 测试基建改动纯增量。
- 3 项 minor 瑕疵（P1-03 evidence 版本字符串 `evidence/1` vs `evidence/1.0`、P1-02/03/08 缺版本常量、P1-07 mastery provider_version 两段/三段不一致）→ 列为 G3A 进入门禁前置。

## 1. 背景与约束

G3 是 Product 1 V2 集成的**首次触及共享生产文件**的 Gate。此前 G1/G2/第三批所有工作都在各 agent 私有目录，未碰主链。G3 由 P1-09 独占执行（角色卡 + CLAUDE.md §文件所有权）。

### 1.1 共享文件现状（复核确认）

| 文件 | 现状 | 风险 |
| --- | --- | --- |
| `backend/app/main.py` | `app.include_router(...)` 注册 11 个 router；`document.router` 注册两次（`/api/v1/document` + `/api/v1/chat/file`） | 路由顺序敏感；新增 router 须独立 prefix |
| `backend/app/core/config.py` | pydantic-settings `Settings`，`extra="ignore"`；**无任何 V2 feature flag** | G3 须新增 flag，默认 `v1_only` |
| `backend/app/api/v1/endpoints/document.py` | ~2768 行，27 路由；**重复 `/courses`(680/1025) 与 `/course/{id}/save`(885/1110)** | 多人改会破坏路由顺序与 M7 回归 |
| `backend/app/services/document_service.py` | ~2072 行，解析/Markdown/LLM 脚本/RAG 编排集中 | Provider 与业务编排耦合 |
| `backend/app/models/database.py` | 导入所有 ORM，全局 `engine`，`AI_COURSE_DATABASE_URL` 覆盖默认 sqlite | 新模型/循环依赖/初始化风险集中 |
| `backend/app/common/db_migrator.py` | 固定 `smart_class.db`，sqlite3 直连，**无版本化** | 不可作 V2 大规模迁移机制 |

### 1.2 硬约束（来自 CLAUDE.md + P1-09 角色卡 + 规划 §8.3）

1. **默认 `v1_only`**：所有 V2 能力默认关闭或 shadow-only。
2. **非法配置 fail-closed**：feature flag 取非法值时回退 V1 并记 `fallback_reason`，不伪装 V2 success。
3. **Shadow 不写 V1**：shadow 只写独立 run/artifact/table，不覆盖 `Course/ScriptNode/KnowledgePageMap`、V1 RAG registry、V1 任务状态、用户可见行为。
4. **旧字段/路径不删**：新字段 optional；旧前端/旧客户端可工作。
5. **Migration 独立可回滚**：独立 PR，空库 + 旧库副本测试，down/逻辑回滚方案。
6. **新增 endpoint 独立 router**：不塞进 document.py 大文件。
7. **关闭 flag 即恢复 V1**：任何 V2 阶段失败，关 flag 后系统与 M7 基线等价。
8. **不启用 preferred/V2-only**：除非 P1-00 + P1-10 + 人工批准。
9. **不改私有算法**：P1-01~P1-08 的实现不改；P1-10 测试不弱化。

## 2. Feature Flag 设计

新增到 `config.py` `Settings`（P1-09 实施），全部默认 `v1_only`，非法值 fail-closed：

| Flag | 合法值 | 默认 | 作用域 |
| --- | --- | --- | --- |
| `DOCUMENT_PIPELINE_VERSION` | `v1_only` / `v2_shadow` / `v2_preferred_with_v1_fallback` | `v1_only` | P1-01/02 解析链 |
| `KNOWLEDGE_GRAPH_PIPELINE_VERSION` | 同上 | `v1_only` | P1-05 图谱 |
| `DOCUMENT_KG_RUNTIME_MODE` | 同上 | `v1_only` | 检索+图谱运行时 |
| `EVIDENCE_CITATION_MODE` | `v1_only` / `v2_shadow` | `v1_only` | P1-03 Evidence/Citation 接 QA |
| `STUDENT_MEMORY_MODE` | `disabled` / `shadow` | `disabled` | P1-06 记忆（独立 flag，不与文档总开关捆绑） |
| `LEARNING_EVENT_MODE` | `v1_only` / `v2_shadow` | `v1_only` | P1-07 事件 mapper |
| `SAFETY_GOVERNANCE_MODE` | `disabled` / `shadow` | `disabled` | P1-08 安全 hook |

**fail-closed 规则**：任何 flag 取未列出值 → 视为 `v1_only`/`disabled`，记 `fallback_reason="invalid_flag_value:<flag>=<value>"`，日志告警。**不得**因非法值启用任何 V2 路径。

**独立 flag 原则**：记忆/学情/安全各有独立 flag，不与 `DOCUMENT_PIPELINE_VERSION` 总开关捆绑（规划 §8.3.2）。任一独立 flag 关闭不影响其他。

## 3. G3 分批顺序（G3A ~ G3E）

依赖驱动，每批独立可回滚。每批进入前须满足其门禁，退出前须满足退出门禁。**任何一批不满足退出门禁，不进入下一批。**

### G3A：Feature Flag 基础设施 + 契约版本常量补齐

**目标**：建立 flag 读取与 fail-closed 机制，不接任何业务路径；补齐复核发现的 3 项契约版本瑕疵。

**改动范围（P1-09）**：
- `config.py`：新增上述 7 个 flag（默认 v1_only/disabled）。
- 新增 `backend/app/core/feature_flags.py`（P1-09 新文件）：flag 读取 + 合法值校验 + fail-closed helper + `fallback_reason` 记录。**不导入任何 V2 业务模块**。
- 契约版本常量补齐（各 owner minor，经 P1-00 批准）：P1-03 `EVIDENCE_VERSION`/`CITATION_VERSION` 常量 + `evidence/1`→`evidence/1.0` 统一；P1-02 `PARSER_PROVIDER_VERSION`；P1-08 `SAFETY_VERSION`；P1-07 mastery `provider_version` 统一。

**进入门禁**：
- 复核报告通过（已满足）。
- 3 项契约版本瑕疵的补齐方案经 P1-00 批准（minor，不改语义）。

**退出门禁**：
- `feature_flags.py` 单元测试：合法值返回正确 mode；非法值返回 `v1_only`/`disabled` + `fallback_reason`；所有 flag 默认值断言。
- `config.py` 改动不破坏现有 settings 加载（M7 回归通过）。
- 契约版本常量补齐后，对应 agent 测试全过（663 不回归）。
- P1-10 独立验证 flag fail-closed 行为。
- **默认全 V1**：关闭所有 flag 后系统与 M7 基线 `f98ce19` 行为等价（M7 smoke + 回归通过）。

**回滚**：删 `feature_flags.py` + 还原 `config.py` flag 行。无数据影响。

### G3B：Document 解析 Shadow（P1-01/02 接入上传旁路）

**目标**：上传文档时，`DOCUMENT_PIPELINE_VERSION=v2_shadow` 下并行运行 V2 解析（P1-02 Provider → P1-01 DocumentIR），结果写入**独立 shadow artifact store**（P1-01 json_artifact_store），V1 主链不变。

**改动范围（P1-09）**：
- `document_service.py`：加 adapter seam（不重写解析逻辑），在 V1 解析后**异步/并行**触发 V2 shadow 解析，写 shadow store，记 trace/diff。V2 失败记 `fallback_reason`，不影响 V1。
- `document.py`：**不改现有 27 路由**；如需新 endpoint（如查询 shadow artifact），用**独立 router**（`/api/v1/document-v2/...`）注册到 main.py，不进 document.py。
- 不写 V1 表；shadow artifact 路径与 V1 `Course/ScriptNode/KnowledgePageMap` 隔离。

**进入门禁**：
- G3A 退出通过。
- P1-01 DocumentIR + P1-02 Provider 契约 frozen（已满足）。
- shadow store 原子写/路径穿越/校验和测试通过（P1-01 已有 111 测试）。

**退出门禁**：
- shadow 模式下：V1 主链行为与 M7 等价（上传/课程/脚本/发布/M7 smoke 通过）；V2 shadow artifact 生成且可回放；V2 失败 → `fallback_reason` 记录，V1 不受影响。
- shadow diff 报告：V1 vs V2 解析结果对比（不要求一致，要求可追溯）。
- 关闭 flag → 无 shadow 副作用，V1 完全不变。
- P1-10 独立验证：无 V1 表写入、无用户可见行为变化。
- 无真实 Docling/PaddleOCR 调用（fake/离线）。

**回滚**：关 `DOCUMENT_PIPELINE_VERSION` flag → V2 shadow 停止；shadow artifact 保留只读审计；V1 不变。

### G3C：Evidence/检索/Citation Shadow（P1-03 接 QA）

**目标**：`EVIDENCE_CITATION_MODE=v2_shadow` 下，QA 检索并行运行 V2 Evidence-aware RetrievalGateway（P1-03），产出 Citation + EvidenceSpan，与 V1 `ragSources` 对比。V1 QA 响应不变。

**改动范围（P1-09）**：
- `qa_service.py`：加 hook seam，V1 检索后并行触发 V2 检索 + Citation 校验，记 shadow trace。V2 结果**不返回给用户**（除非 G6 preferred）。
- `chat.py`：不改现有路由；CitationValidator 作为 seam 注入，不导入具体 Provider。
- V1 `ragSources` 响应结构不变；V2 evidence 字段为 shadow-only，不入 V1 响应。

**进入门禁**：
- G3B 退出通过（DocumentIR shadow 可用，Evidence 依赖 stable block IDs）。
- P1-03 Evidence/Citation/Retrieval 契约 frozen（已满足）。
- RISK-03 跨课程污染测试通过（missing scope 返回空，已验证）。

**退出门禁**：
- shadow 模式：V1 QA 响应与 M7 等价；V2 检索 trace 可追溯到 stable evidence/block；无证据时 `should_abstain` 不伪造 citation。
- 跨课程/跨文档隔离：V2 检索不泄漏其他课程数据（对抗测试）。
- 关闭 flag → V1 QA 完全不变。
- P1-10 独立验证 citation 正确率（contract 级，非模型质量）。

**回滚**：关 flag → V2 检索停止；V1 `ragSources` 不变。

### G3D：学情/记忆/安全 Shadow（P1-06/07/08 接入）

**目标**：三个独立 flag 分别控制。`LEARNING_EVENT_MODE=v2_shadow` 下，进度/测验/问答/跳转映射为 LearningEvent（P1-07）写 shadow event store。`STUDENT_MEMORY_MODE=shadow` 下，记忆 Repository（P1-06）以只读/shadow 上下文注入 QA。`SAFETY_GOVERNANCE_MODE=shadow` 下，SafetyEvaluator（P1-08）作为 hook 评估但不阻断（shadow 仅记录决策）。

**改动范围（P1-09）**：
- `progress_service.py` / `prerequisite_service.py`：加 event mapper seam（shadow，不双写无幂等事件）。
- `qa_service.py`：记忆上下文注入 seam（token 预算）；安全 hook seam（shadow 记录 SafetyDecision，不阻断）。
- 三者均独立 flag，互不捆绑。

**进入门禁**：
- G3C 退出通过。
- P1-06/07/08 契约 frozen（已满足）。
- RISK-05（记忆隐私/删除）+ RISK-06（学情可解释）测试通过（已验证）。

**退出门禁**：
- shadow 模式：V1 进度/问答/跳转行为与 M7 等价；V2 event/memory/safety shadow 可追溯；记忆关闭时不读不写；安全 shadow 不阻断 V1。
- 跨学生/课程越权对抗测试通过（P1-06/P1-10）。
- 学情结论可列出 LearningEvidence refs（P1-07）。
- 关闭任一 flag → 该 V2 路径停止，V1 不变。
- P1-10 独立验证隐私/删除/审计边界。

**回滚**：分别关三个 flag；shadow 数据保留只读审计；V1 不变。

### G3E：图谱 Shadow + 前端挂载 + Shadow Diff 报告（P1-05/04）

**目标**：`KNOWLEDGE_GRAPH_PIPELINE_VERSION=v2_shadow` 下，从 Evidence 支撑的 EducationalUnit 生成图谱候选（P1-05）写 shadow graph store，不接 V1 `KnowledgePoint/KnowledgeRelation`。前端 Evidence Viewer（P1-04）以独立路由挂载（只读，不进现有 dashboard/player）。

**改动范围（P1-09）**：
- 图谱：shadow graph store（P1-05 GraphStore fake 基础上 P1-09 实现 Repository），不写 V1 知识表。
- 前端：`router/index.js` 加独立路由挂载 `EvidenceViewerWithPanel`（P1-04），**不修改** `SplitVideoPlayer/TeacherDashboard/StudentDashboard`。`utils/request.js` 不改；新 API 用独立 `api/evidence.js`。
- Shadow diff 报告：汇总 G3B~G3E 的 V1 vs V2 对比，machine-readable（P1-10 quality_gate_report）。

**进入门禁**：
- G3D 退出通过。
- P1-04/05 契约 frozen（已满足）。
- P1-04 前端 `npm run build` 通过（G3 首次需 node_modules，P1-09 在 worktree 装）。

**退出门禁**：
- shadow 模式：V1 知识 CRUD 与 M7 等价；V2 图谱 shadow 可回溯 Evidence；图谱失败不影响文档检索。
- 前端 Viewer 独立路由可访问，不影响现有页面；坐标高亮 fail-closed（RISK-02）。
- 关闭 flag → 图谱 shadow 停止，前端路由可保留（只读）或移除。
- P1-10 独立验证图谱 accepted 可回溯 Evidence、前端不影响主链。
- Shadow diff 报告完整（G3B~G3E）。

**回滚**：关 `KNOWLEDGE_GRAPH_PIPELINE_VERSION` flag → 图谱 shadow 停止；前端路由移除或保留只读；V1 不变。

## 4. 最小 Migration 策略

G3 各批 shadow 数据**优先用独立 artifact store（JSON/文件）**，不新增 ORM 表。仅当 shadow 数据需查询/索引时，P1-09 才设计 migration，且：

1. **独立 PR**：每个 migration 单独 PR，不与业务接线混提交。
2. **新增表 only**：只加 V2 shadow 表（如 `p1_shadow_*`），不改 V1 表结构。
3. **空库 + 旧库副本测试**：在空库和 `smart_class.db` 副本上各跑一次，验证 schema 应用 + down 回滚。
4. **down/逻辑回滚方案**：每个 migration 须有 down（drop shadow 表）+ 逻辑回滚（关 flag + 清 shadow 数据）。
5. **不依赖 `db_migrator.py`**：该机制无版本化，G3 migration 用独立版本化脚本（P1-09 设计）。
6. **G3 阶段不迁移 V1 数据**：V2 shadow 表为新生成数据，不搬运 V1 历史数据（留 G4/G5）。

**G3A~G3E 预期 migration 量**：最小化。G3A 无 migration（仅 flag）；G3B shadow artifact 用文件 store（无 migration）；G3C/D/E 视查询需求决定是否加 shadow 表。**默认不加 ORM 表**，除非 shadow 报告需要查询。

## 5. 独立 Router 策略

- 所有 V2 新 endpoint 用**独立 router 文件**（如 `backend/app/api/v1/endpoints/document_v2.py`、`evidence_v2.py`），独立 prefix（`/api/v1/document-v2/`、`/api/v1/evidence-v2/`）。
- 在 `main.py` 用 `app.include_router(v2_router, prefix=..., tags=["Product1-V2-shadow"])` 注册，**不进 document.py/chat.py 大文件**。
- V2 endpoint 默认 shadow/只读，需 flag 开启；未开 flag 时返回 503 或空。
- 旧 endpoint 路径/字段/响应**完全不变**。

## 6. 回滚总策略

**任意批次任意时刻回滚**：
1. 关对应 flag（`v2_shadow` → `v1_only` / `shadow` → `disabled`）。
2. 停止新 V2 run（进行中的 shadow run 可完成或中止，不写 V1）。
3. V2 shadow 数据保留只读审计（不立即删，除非用户要求）。
4. 验证 M7 smoke + 回归通过 → 系统与 M7 基线等价。
5. 图谱通过 active snapshot pointer 回退（P1-05 设计）。
6. Migration 回滚：drop shadow 表（down），V1 表未动。

**关 flag 即恢复 V1** 是每批退出门禁的硬性验证项。

## 7. P1-09 执行约束

- 每批开始前 P1-09 须报告：身份、分支、HEAD、worktree、批准契约、计划改动的共享文件、migration 影响、flag、fallback、回滚、测试。
- 每批结束 P1-09 须报告：回归结果、migration 证据、flag 与默认值、fallback 行为、回滚指令、外部服务使用、git checks。
- **不 commit/push/merge/rebase/装依赖**，除非用户明确授权。
- P1-10 独立门禁：每批退出前 P1-10 出具独立验证（不替业务 agent 宣布通过）。
- P1-00 审批每批进入/退出。

## 8. G3 不做的事

- 不启用 `v2_preferred_with_v1_fallback`（G6）或 `v2_only`。
- 不删旧字段/路径/endpoint。
- 不把 V2 结果写入 V1 表/索引/任务状态。
- 不改 P1-01~P1-08 私有算法。
- 不弱化 P1-10 测试。
- 不调用真实 Docling/PaddleOCR/向量模型/LLM（shadow 用 fake/离线；真实服务对比留 G5 canary）。
- 不迁移 V1 历史数据到 V2（留 G4/G5）。
- 不修改 M7 维护分支 `refactor/codemind-v3`。

## 9. 审批与启动

本 ADR 为方案，**不修改任何生产代码**。审批流程：
1. 人工审批本 ADR + 复核报告 `review-1cf0269-pre-g3.md`。
2. 审批通过后，P1-09 worktree 从 `1cf0269` 创建（`agent/p1-09-integration` 分支）。
3. P1-09 按 G3A → G3E 顺序执行，每批进入/退出经 P1-00 + P1-10 + 人工确认。
4. 任一批次不满足退出门禁，停止，不进入下一批。

## 10. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| document.py/document_service.py 改动破坏 M7 | G3B 仅加 adapter seam，不改现有路由/逻辑；独立 router 承载新 endpoint |
| Migration 误伤 V1 | 只加 shadow 表，不改 V1 表；空库+旧库副本+down 回滚 |
| Flag 非法值启用 V2 | fail-closed：非法值→v1_only，记 fallback_reason |
| Shadow 写 V1 表 | 退出门禁硬验证无 V1 表写入（P1-10） |
| 前端挂载破坏现有页面 | 独立路由，不改 dashboard/player/request.js |
| 图谱双事实源 | V2 图谱独立 shadow store，不写 V1 KnowledgePoint/KnowledgeRelation |
| 跨课程/学生污染 | RISK-03/05 对抗测试每批退出验证 |
