# ADR-0006: Product 1 V2 Shadow 集成顺序、隔离边界与回滚策略

- 状态: **Accepted (G3A only)** - Rev 1 经人工二次审批通过；G2.1 契约规范化已完成并通过 P1-10 独立验证（见 reviews/p1-10-g21-verification.md），新冻结 SHA = `d4894da`。仅授权启动 G3A；G3B 及以后仍逐批人工放行。P1-09 worktree 须从 `d4894da` 创建。
- 日期: 2026-07-14（初版）/ 2026-07-14（Rev 1）/ 2026-07-14（Accepted-G3A）
- 决策者: P1-00（起草），P1-09（执行），人工审批（启动前）
- 影响范围: G2.1 契约规范化 + G3 Shadow Integration 全程；P1-09 独占的共享生产文件
- 性质: **方案文档，不修改任何 ORM、Migration、公开 API、生产 endpoint、公共配置或前端共享文件**。审批通过后 P1-09 方可按本 ADR 执行。
- G2.1 冻结 SHA: `d4894da`（G3A 基线；P1-09 由此创建 worktree）

## 0. 修订说明（Rev 1，回应人工审阅 9 项）

初版 ADR-0006 经人工逐段审阅，发现 4 个实质性阻断项 + 5 个边界/措辞问题。Rev 1 修订：
1. **G3D Memory Shadow 注入 QA 会改变 V1 回答** -> G3D 拆为 G3D1/G3D2/G3D3；Memory Candidate Shadow **不得注入正式 QA Prompt**。
2. **G3E 前端挂载与"公开 API DTO 留 G4"冲突** -> G3E 拆为 G3E1/G3E2；**正式前端挂载延后至 G4**（G4A DTO 冻结 / G4B Viewer 挂载）；G3 阶段 P1-04 仅用 fixture/mock/dev page。
3. **Flag 合法值含 `v2_preferred_with_v1_fallback` 与"G3 不启用 preferred"冲突** -> G3 仅允许 `v1_only`/`v2_shadow`；`v2_preferred_with_v1_fallback` 移至 G6。**配置非法 = 启动级 fail-fast（拒绝启动）；shadow 运行错误 = 业务级 fail-closed（V1 继续 + fallback_reason）**。
4. **G3A 由 P1-09 修领域契约越权** -> 新增 **G2.1 Contract Normalization**，由 P1-02/03/07/08 各领域 owner 补版本常量，形成新冻结 SHA；P1-09 从新 SHA 起步。
5. G3B：明确 **commit-then-trigger**（V1 commit 成功后提交 V2 任务）+ 资源规则（单课程单任务/幂等/队列满跳过/超时/abandoned/不占 M7 GPU 端口/磁盘配额）。
6. G3C：**禁止第二次 LLM 调用**；对比 V1 ragSources vs V2 candidates，不比较两份生成答案。
7. V2 Router：增加权限（管理员/内部）、课程隔离、去敏、统一 503 + `SHADOW_FEATURE_DISABLED`、shadow 数据保留期。
8. 措辞：citation "正确率" -> "完整性/可解析性/作用域隔离/证据链存活率"；V1 vs V2 diff -> "contract/integration diff"（非质量对比）。
9. 复核报告路径修正：播放器真实路径 `frontend/src/components/chat/player/SplitVideoPlayer.vue`，16 个播放器共享文件已逐个核验；main.py 实际 14 个 `include_router`。

## 1. 前置：复核结论（已修正）

冻结点 `1cf0269` 复核**有条件通过**（见 `docs/refactor/product1/reviews/review-1cf0269-pre-g3.md`，路径修正后成立）：
- 工作区干净，9 agent 分支全合流，13 契约 frozen-major，跨域依赖无循环，663+116 测试可重现零回归。
- P1-09 共享生产文件零触及（含 16 个播放器/composable 共享文件，按真实路径核验）；P1-10 测试基建改动纯增量。
- main.py 实际 14 个 `include_router`（13 distinct，document.router 注册两次 = 规划 §2.3 重复路由危险点）。
- 3 项 minor 契约版本瑕疵 -> **G2.1 规范化补齐**（不由 P1-09 修）。

## 2. 硬约束（贯穿 G2.1 + G3 全程）

1. **默认 `v1_only`/`disabled`**：所有 V2 能力默认关闭或 shadow-only。
2. **配置非法 = 启动级 fail-fast**：feature flag 取未列出值时，**应用拒绝启动**，明确报错（不静默回退，不掩盖配置错误）。例如 `DOCUMENT_PIPELINE_VERSION=v2_shdaow`（拼写错）-> 启动失败，提示合法值。
3. **Shadow 运行错误 = 业务级 fail-closed**：配置合法但 V2 shadow 执行失败（超时/异常/不可用）-> V1 继续运行，记 `fallback_reason`，不伪装 V2 success，不影响用户。
4. **Shadow 不改变 V1 用户可见行为**：shadow 不得注入正式 QA Prompt、不得阻断 V1、不得改 V1 响应、不得写 V1 表/索引/任务状态。Memory 注入正式回答属 G6 preferred，非 G3。
5. **旧字段/路径/endpoint 不删**：新字段 optional；旧前端/旧客户端可工作。
6. **Migration 独立可回滚**：独立 PR，空库 + 旧库副本测试，down/逻辑回滚。
7. **新增 endpoint 独立 router**：独立文件 + 独立 prefix，不进 document.py/chat.py 大文件。
8. **关闭 flag 即恢复 V1**：任何 V2 阶段失败，关 flag 后系统与 M7 基线等价。
9. **不启用 preferred/V2-only**：除非 P1-00 + P1-10 + 人工批准（G6）。
10. **不改私有算法**：P1-01~P1-08 实现不改；P1-10 测试不弱化。

## 3. Feature Flag 设计（G3 仅 v1_only/v2_shadow）

新增到 `config.py` `Settings`（P1-09 在 G3A 实施）。**G3 阶段合法值仅 `v1_only`/`v2_shadow`**（记忆/安全为 `disabled`/`shadow`）。`v2_preferred_with_v1_fallback` 与 `v2_only` **不在 G3 合法枚举内**，移至 G6。

| Flag | G3 合法值 | 默认 | 作用域 |
| --- | --- | --- | --- |
| `DOCUMENT_PIPELINE_VERSION` | `v1_only` / `v2_shadow` | `v1_only` | P1-01/02 解析链 |
| `KNOWLEDGE_GRAPH_PIPELINE_VERSION` | `v1_only` / `v2_shadow` | `v1_only` | P1-05 图谱 |
| `DOCUMENT_KG_RUNTIME_MODE` | `v1_only` / `v2_shadow` | `v1_only` | 检索+图谱运行时 |
| `EVIDENCE_CITATION_MODE` | `v1_only` / `v2_shadow` | `v1_only` | P1-03 Evidence/Citation 接 QA |
| `STUDENT_MEMORY_MODE` | `disabled` / `shadow` | `disabled` | P1-06 记忆（独立 flag） |
| `LEARNING_EVENT_MODE` | `v1_only` / `v2_shadow` | `v1_only` | P1-07 事件 mapper |
| `SAFETY_GOVERNANCE_MODE` | `disabled` / `shadow` | `disabled` | P1-08 安全 hook |

**两层错误处理（关键）**：
- **配置错误（启动级 fail-fast）**：flag 值不在合法枚举 -> `Settings` 校验失败，应用拒绝启动，错误信息列出合法值。不回退、不告警后继续。
- **Shadow 运行错误（业务级 fail-closed）**：配置合法但 V2 执行失败 -> 视为该批未运行，记 `fallback_reason="shadow_runtime_error:<flag>:<reason>"`，V1 不受影响。

**独立 flag 原则**：记忆/学情/安全各有独立 flag，不与 `DOCUMENT_PIPELINE_VERSION` 总开关捆绑。任一关闭不影响其他。

## 4. 执行顺序总览

```
G2.1 契约版本规范化（领域 owner）-> 新冻结 SHA
  -> ADR-0006 二次审批 Accepted
  -> G3A Flag 与 fail-fast/fail-closed 机制 -> 人工放行
  -> G3B Document Shadow（commit-then-trigger）-> 人工放行
  -> G3C Evidence Retrieval Shadow（不二次调用 LLM）-> 人工放行
  -> G3D1 LearningEvent Shadow -> G3D2 Memory Candidate Shadow（不注入 QA）-> G3D3 Safety Dry-run
  -> G3E1 Graph Shadow -> G3E2 Shadow Diff Report
  -> G4A Evidence API DTO 冻结 -> G4B Evidence Viewer 正式挂载
  -> G5 Canary -> G6 Preferred
```

每批进入前须满足进入门禁，退出前须满足退出门禁。**任何一批不满足退出门禁，不进入下一批。** 每批人工放行。

## 5. G2.1 Contract Normalization（G3 前置，领域 owner 执行）

**目标**：补齐 3 项契约版本瑕疵，形成新冻结 SHA。**不由 P1-09 执行**（领域契约属各 owner）。

**分工**：
- **P1-02**：新增 `PARSER_PROVIDER_VERSION = "parser-provider/1.0"` 常量（quality.py/registry.py）。
- **P1-03**：新增 `EVIDENCE_VERSION="evidence/1.0"`、`CITATION_VERSION="citation/1.0"`、`TEXT_TRANSFORM_VERSION="text-transform/1.0"` 常量；docstring `evidence/1` -> `evidence/1.0` 统一。
- **P1-07**：统一 mastery `provider_version`（`contracts.py` 默认与 `rule_baseline.py` 一致，两段或三段取其一，建议两段 `1.0` 与 learning/1.0 风格一致）。
- **P1-08**：新增 `SAFETY_VERSION = "safety/1.0"` 常量。
- **P1-00**：更新 registry.md（版本常量已补齐，状态不变仍 frozen-major）。
- **P1-10**：独立验证各 owner 改动为纯常量新增/字符串统一，无契约语义变更，对应测试不回归。

**进入门禁**：复核报告通过（已满足）。
**退出门禁**：
- 各 owner 分支测试全过（无回归）。
- P1-10 确认无语义变更。
- 合流到 integration，**新冻结 SHA**（记为 G2.1 冻结点）。
- P1-09 worktree 从**新冻结 SHA**创建（不从 `1cf0269`）。

**回滚**：各 owner revert 常量 commit。无数据影响。

## 6. G3 批次详述

### G3A：Feature Flag 基础设施

**目标**：建立 flag 读取 + 启动级 fail-fast + 业务级 fail-closed 机制，不接任何业务路径。

**改动范围（P1-09）**：
- `config.py`：新增 7 个 flag（G3 合法值仅 v1_only/v2_shadow/disabled/shadow），用 pydantic 枚举校验实现**启动级 fail-fast**（非法值拒绝启动）。
- 新增 `backend/app/core/feature_flags.py`（P1-09 新文件）：flag 读取 + 合法值校验 + 业务级 fail-closed helper（`fallback_reason` 记录）。**不导入任何 V2 业务模块**。

**进入门禁**：G2.1 退出通过（新冻结 SHA 存在）。
**退出门禁**：
- `feature_flags.py` 单元测试：合法值返回正确 mode；**非法值触发启动失败**（fail-fast）；shadow 运行错误返回 v1_only + `fallback_reason`（fail-closed）；所有 flag 默认值断言。
- `config.py` 改动不破坏现有 settings 加载（M7 回归通过）。
- **默认全 V1**：关闭所有 flag 后系统与 M7 基线 `f98ce19` 行为等价（M7 smoke + 回归通过）。
- P1-10 独立验证 fail-fast 与 fail-closed 两种路径。

**回滚**：删 `feature_flags.py` + 还原 `config.py`。无数据影响。

### G3B：Document 解析 Shadow（commit-then-trigger）

**目标**：`DOCUMENT_PIPELINE_VERSION=v2_shadow` 下，V1 上传成功后并行运行 V2 解析（P1-02 Provider -> P1-01 DocumentIR），结果写**独立 shadow artifact store**，V1 主链不变。

**触发时机（commit-then-trigger，硬约束）**：
```
V1 文件已稳定落盘
  -> V1 数据库事务 commit 成功
  -> V1 主流程成功状态已确定
  -> 提交 V2 Shadow 任务（异步）
```
**禁止**：在 V1 数据库事务内部执行 V2；让上传接口同步等待完整 V2 解析结束。

**资源规则（V2 不得拖垮 V1）**：
- 单课程最多 1 个运行中 shadow 任务；同 artifact+config 幂等（重复提交跳过）。
- 队列满时跳过并记 `fallback_reason="shadow_queue_full"`，**不阻塞 V1**。
- 每任务最大超时；进程中断后任务标记 `abandoned`。
- **Shadow 不得占用 M7 必须的 GPU/端口**（Duix/数字人/TTS 资源）。
- Shadow 磁盘配额 + 清理周期（过期 shadow artifact 清理）。

**改动范围（P1-09）**：
- `document_service.py`：加 adapter seam（不重写解析逻辑），V1 commit 成功后异步触发 V2 shadow，写 shadow store + trace/diff。V2 失败记 `fallback_reason`。
- `document.py`：**不改现有 27 路由**；新 endpoint 用独立 router（`/api/v1/document-v2/...`）。
- 不写 V1 表；shadow artifact 路径与 V1 `Course/ScriptNode/KnowledgePageMap` 隔离。

**进入门禁**：G3A 退出通过；P1-01/02 契约 frozen（已满足）；shadow store 原子写/路径穿越/校验和测试通过。
**退出门禁**：
- shadow 模式：V1 主链与 M7 等价（上传/课程/脚本/发布/M7 smoke 通过）；V2 shadow artifact 生成且可回放；V2 失败 -> `fallback_reason`，V1 不受影响。
- **contract/integration diff**（非质量对比）：V1 vs V2 解析产物结构对比，证明 shadow 链路可运行、产物可追踪、diff 格式可生成。**不证明 V2 解析质量优于 V1**（真实 Docling/PaddleOCR 对比留 G5 canary）。
- 关闭 flag -> 无 shadow 副作用，V1 完全不变。
- P1-10 独立验证：无 V1 表写入、无用户可见行为变化、资源规则生效。
- 无真实 Docling/PaddleOCR 调用（fake/离线）。

**回滚**：关 flag -> V2 shadow 停止；shadow artifact 保留只读审计；V1 不变。

### G3C：Evidence/检索/Citation Shadow（不二次调用 LLM）

**目标**：`EVIDENCE_CITATION_MODE=v2_shadow` 下，V1 QA 检索后并行运行 V2 Evidence-aware RetrievalGateway（P1-03）+ Citation 校验，记 shadow trace。**V1 QA 响应不变**。

**硬约束（关键）**：
> G3C 只运行 V2 检索、证据绑定、Citation 校验。**不再次调用生成模型，不产生第二份用户答案。**

否则一次学生提问会变成 V1 调 LLM + V2 调 LLM，增加成本/延迟/数据外发/不稳定。

**对比对象**：V1 `ragSources` vs V2 `RetrievedChunk`/`Evidence`/`Citation` candidates（检索与证据层对比），**不比较两份生成答案**。

**改动范围（P1-09）**：
- `qa_service.py`：加 hook seam，V1 检索后并行触发 V2 检索 + Citation 校验（**不调 LLM**），记 shadow trace。V2 结果**不返回给用户**。
- `chat.py`：不改现有路由；CitationValidator 作为 seam 注入，不导入具体 Provider。
- V1 `ragSources` 响应结构不变；V2 evidence 字段 shadow-only。

**进入门禁**：G3B 退出通过；P1-03 契约 frozen（已满足）；RISK-03 跨课程污染测试通过。
**退出门禁**：
- shadow 模式：V1 QA 响应与 M7 等价；V2 检索 trace 可追溯到 stable evidence/block；无证据时 `should_abstain` 不伪造 citation。
- 跨课程/跨文档隔离：V2 检索不泄漏其他课程数据（对抗测试）。
- **无第二次 LLM 调用**（P1-10 验证 shadow trace 不含生成模型调用）。
- 关闭 flag -> V1 QA 完全不变。
- P1-10 独立验证 **citation 完整性、可解析性、作用域隔离和证据链存活率**（contract 级，非语义"正确率"；语义正确率留金标 QA 评测 G5）。

**回滚**：关 flag -> V2 检索停止；V1 `ragSources` 不变。

### G3D1：LearningEvent Shadow

**目标**：`LEARNING_EVENT_MODE=v2_shadow` 下，进度/测验/问答/跳转映射为 LearningEvent（P1-07）写**独立 shadow event store**，不改变正式业务。

```
真实学习行为 -> 映射为 LearningEvent -> 写独立 Shadow Store -> 不改变正式业务
```

**改动范围（P1-09）**：`progress_service.py`/`prerequisite_service.py` 加 event mapper seam（shadow，不双写无幂等事件，不写 V1 表）。
**进入门禁**：G3C 退出通过；P1-07 契约 frozen。
**退出门禁**：V1 进度/跳转与 M7 等价；shadow event store 可回放；事件幂等键正确；关 flag -> V1 不变。
**回滚**：关 flag -> shadow 停止。

### G3D2：Memory Candidate Shadow（不注入正式 QA）

**目标**：`STUDENT_MEMORY_MODE=shadow` 下，从 LearningEvent -> LearningEvidence -> 候选 MasteryState -> 候选 StudentMemory Context，**保存并比较，但不注入正式 QA Prompt**。

```
LearningEvent -> LearningEvidence -> 候选 MasteryState -> 候选 StudentMemory Context -> 保存并比较
```

**硬约束（关键）**：
> Memory Candidate Shadow **不得注入正式 QA Prompt**。可离线记录"如果使用该记忆，将给模型提供哪些上下文"，但不真正影响学生得到的回答。

只要把学生记忆加入正式 QA Prompt，即使只读/不写库/不展示，大模型最终回答也可能改变，违反"V1 QA 响应和用户可见行为不变"。正式注入属 G6 preferred。

**改动范围（P1-09）**：记忆候选生成 seam（写 shadow candidate store）；**不接 qa_service Prompt 构造**。
**进入门禁**：G3D1 退出通过；P1-06 契约 frozen；RISK-05 隐私/删除测试通过。
**退出门禁**：候选 memory 可追溯 evidence refs + generation reason；跨学生/课程隔离；记忆关闭时不读不写；**正式 QA 回答与 M7 等价（P1-10 对抗验证 memory 未影响 Prompt）**。
**回滚**：关 flag -> 候选生成停止。

### G3D3：Safety Dry Run

**目标**：`SAFETY_GOVERNANCE_MODE=shadow` 下，SafetyEvaluator（P1-08）评估用户请求，记录 `would_allow`/`would_refuse`，**不阻断 V1**。

```
用户请求 -> SafetyEvaluator -> 记录 would_allow / would_refuse -> 不阻断 V1
```

**改动范围（P1-09）**：安全 hook seam（shadow 记录 SafetyDecision，不阻断 V1 流程）。
**进入门禁**：G3D1 退出通过；P1-08 契约 frozen。
**退出门禁**：V1 问答/上传与 M7 等价（safety 不阻断）；shadow 决策可追溯 reason code；平台底线测试；关 flag -> V1 不变。
**回滚**：关 flag -> safety shadow 停止。

### G3E1：Graph Shadow

**目标**：`KNOWLEDGE_GRAPH_PIPELINE_VERSION=v2_shadow` 下，从 Evidence 支撑的 EducationalUnit 生成图谱候选（P1-05）写**独立 shadow graph store**，不接 V1 `KnowledgePoint/KnowledgeRelation`。

**改动范围（P1-09）**：shadow graph store（P1-05 GraphStore fake 基础上 P1-09 实现 Repository）；不写 V1 知识表；图谱失败不影响文档检索。
**进入门禁**：G3D3 退出通过；P1-05 契约 frozen。
**退出门禁**：V1 知识 CRUD 与 M7 等价；V2 图谱 shadow 可回溯 Evidence；accepted 节点/边必有 Evidence；关 flag -> 图谱 shadow 停止。
**回滚**：关 flag + active snapshot pointer 回退。

### G3E2：Shadow Diff Report

**目标**：汇总 G3B~G3E1 的 V1 vs V2 对比，machine-readable（P1-10 quality_gate_report）。**contract/integration diff**（非质量对比）。
**进入门禁**：G3E1 退出通过。
**退出门禁**：diff 报告覆盖 G3B~G3E1 全部 shadow 路径；P1-10 独立出具。

## 7. G3 阶段前端策略（不正式挂载）

**G3 阶段 P1-04 Evidence Viewer 不接入正式 Router**。可用：
- 固定 JSON fixture；
- Mock API；
- Story/独立开发页面（dev page，不进 router）；
- 本地演示数据。

**正式前端挂载延后至 G4**（见 §8），因前端调用后端会形成跨前后端 DTO，与"公开 V2 API DTO 留 G4"冲突。

## 8. G4：API DTO 冻结 + 前端正式挂载（G3 后）

### G4A：Evidence API DTO 冻结
**目标**：冻结 `internal-evidence-api/1.0`（后端 Evidence API 响应 ↔ 前端 Viewer 输入的 DTO）。
**进入门禁**：G3E2 退出通过。
**退出门禁**：DTO 契约 + contract test 冻结；P1-00 + 前端 contract review。

### G4B：Evidence Viewer 正式挂载
**目标**：`router/index.js` 加独立路由挂载 `EvidenceViewerWithPanel`（P1-04）。**不改** `SplitVideoPlayer/TeacherDashboard/StudentDashboard`。`utils/request.js` 不改；新 API 用独立 `api/evidence.js`。
**进入门禁**：G4A 退出通过；P1-04 `npm run build` 通过。
**退出门禁**：独立路由可访问，不影响现有页面；坐标高亮 fail-closed（RISK-02）。

## 8A. G5A：质量门禁框架（Canary，不接真实服务）

**背景**：G5 Canary 原意为"真实 V2 数据流 + 质量对比"（真实 Docling/PaddleOCR/向量模型/LLM 对比 V1，金标 QA 语义正确率）。但 G2 阶段 P1-02/P1-03 只实现了 Protocol 接口 + Fake 实现（真实 provider 需装依赖/下模型/接真实服务），V1 本身亦离线/本地（TreeRAG + 统计 keyword + 自有 DocumentParser，无向量模型）。真实 canary 与 CLAUDE.md「不装依赖/不接真实付费服务」冲突。经人工决策，G5 拆为 G5A（质量门禁框架，不接真实服务）+ G5B（真实 provider canary，待约束解除）。

### G5A：质量门禁框架
**目标**：把 G3/G4 deferred 的"质量层"从静态描述（g3e2-shadow-diff-report.json，手工撰写）升级为运行时计算的结构化质量指标 + 端到端 canary 可运行性 + canary 范围控制。**不接真实服务**（不调 `process_document`、不调 `llm_client`、不调真实 Docling/OCR/向量）。

**改动范围（P1-09）**：
- 新增 `platform/canary/quality_gate.py`：运行时聚合 G3B~G3E1 shadow trace JSON，计算质量指标 + PASS/FAIL 判定（硬约束：`llm_calls_total==0`、`would_inject_any==False`、`v1_blocked_any==False`、`v1_tables_touched_any==False`、`accepted_traces_evidence_all==True`、`scope_isolation_rate==1.0`；informational：`citation_abstain_rate`）。
- 新增 `platform/canary/canary_runner.py`：all-flags-on（patch 各 shadow 模块 flag 读取函数，非改真实 settings）下用 fake/fixture V1 输入调 6 个 trigger，证明全链路端到端可运行 + trace 生成 + 质量门禁可计算；canary 范围控制（`course_ids` allowlist，非全局）。
- 新增 `api/v1/endpoints/canary_v2.py`：admin-only `/api/v1/canary-v2/run` + `/report`（503 SHADOW_FEATURE_DISABLED when flag off，遵 §9）。
- `main.py` +1 import +1 include_router。
- 测试 + 本节 ADR。

**进入门禁**：G4B 退出通过。
**退出门禁**：
- 质量门禁聚合从 trace 正确计算指标；verdict 逻辑正确（全健康 PASS，任一硬约束违反 FAIL）。
- all-flags-on canary 端到端：6 路径 triggered、trace 生成、质量门禁 PASS；范围控制（allowlist 外课程跳过）；**无真实服务调用**（`llm_client.chat` 不被调用，`real_services_called==False`）。
- P1-10 独立验证：scope（canary/ 新增 + main.py +1/+1 + 本节）、V1/共享文件 UNCHANGED、无真实服务、回归 +新测试 0 新失败。
- 关 flag -> canary 503（flag-gated）。

**回滚**：关 flag -> canary endpoint 503；canary 模块独立，不影响 V1。

### G5A.1：质量门禁语义修订（G5A 冻结前修订）
**目标**：修正 G5A 的语义缺陷：(1) 空输入/缺失字段/零样本/零分母由"空真 PASS"改为 `NOT_EVALUATED`/`INSUFFICIENT_DATA`（"无数据"不得读为"通过"）；(2) 区分三维度 `execution_safety`（V1 隔离保证）/ `contract_integrity`（契约/引用不变式）/ `model_quality`（真实模型质量），G5A 阶段 `model_quality` 强制 `NOT_EVALUATED`（无真实模型）；(3) `real_services_called` 由可审计 Provider 调用记录（`ProviderCallLog`）推导，不再硬编码。

**改动范围（P1-09）**：
- `quality_gate.py`：`MetricStatus` 枚举（pass/fail/not_evaluated/insufficient_data）；`QualityMetric` 加 `dimension` 字段；`DimensionVerdict` 三维度聚合；空/零分母 -> INSUFFICIENT_DATA；`model_quality` 维度恒 NOT_EVALUATED；verdict 四态。
- `canary_runner.py`：`ProviderCallRecord` + `derive_real_services_called(log)`；`CanaryRunResult.provider_call_log`；`real_services_called` 由 log 推导（G5A 空 log -> False）。
- `canary_v2.py`：响应加 `dimensions` + `model_quality_status`。
- 测试重写（31 tests）。

**退出门禁**：三维度区分；空/零/缺 -> NOT_EVALUATED/INSUFFICIENT_DATA（非 PASS）；model_quality 恒 NOT_EVALUATED；real_services_called log 推导；P1-10 验证 -> **冻结 G5A**。

### G5A 状态：**FROZEN**（G5A + G5A.1 完成，P1-10 验证通过）

### G5B-0：真实 canary 准备（仅方案，不执行）
**目标**：准备金标集规范、指标阈值、Provider 兼容矩阵、隔离环境方案、放行顺序，**不安装到生产、不接生产主链、不调用真实付费服务**。
**产出**：`docs/refactor/product1/canary/` 下 5 份 spec（gold-standard-dataset-spec / metric-thresholds / provider-compatibility-matrix / isolation-environment-plan / g5b-rollout-order）。
**状态**：G5B-0 完成（文档就绪）。G5B-N（N≥1，真实 provider 接入）**未放行**。

### G5B：真实 provider canary（待约束解除）
**目标**：实现真实 V2 provider（Docling/PaddleOCR/向量模型/reranker）+ 真实质量对比（金标 QA 评测、真实解析质量）。
**前置**：人工解除 CLAUDE.md「不装依赖/不接真实付费服务」约束；真实 provider 实现（P1-02/P1-03）；金标评测集。
**放行顺序（固定）**：Docling -> PaddleOCR -> Embedding -> Reranker -> LLM，逐项人工放行，不跳序不并行。
**状态**：未放行，待约束解除 + 人工 go。

## 9. 独立 V2 Router 权限与隐私约束

所有 V2 shadow endpoint（`/api/v1/document-v2/`、`/api/v1/evidence-v2/` 等）须遵守：
- **访问控制**：仅管理员或内部测试身份；必须校验 course 权限；**不得允许学生读取其他课程 Evidence**。
- **去敏**：不得公开原始本地文件路径；不得返回 Provider 原始敏感配置；**默认不记录完整 Memory 和学生输入**（审计去敏）。
- **Shadow 数据保留**：明确保留期（过期清理）；仅用于 diff/审计，不用于 V1 业务。
- **未启用响应统一**：flag 未开时返回 **503 + 结构化 `SHADOW_FEATURE_DISABLED`**（不返回空结果，避免被调用方误判为成功）。

## 10. 最小 Migration 策略

G3 各批 shadow 数据**优先用独立 artifact store（JSON/文件）**，不新增 ORM 表。仅当需查询/索引时 P1-09 才设计 migration：
1. 独立 PR；只加 V2 shadow 表（`p1_shadow_*`），不改 V1 表。
2. 空库 + 旧库副本测试 + down 回滚。
3. 不依赖无版本化的 `db_migrator.py`；用独立版本化脚本。
4. G3 阶段不迁移 V1 历史数据（留 G4/G5）。

**G3A~G3E 预期 migration 量**：最小化。G3A 无 migration；G3B shadow artifact 用文件 store；G3C/D/E 视查询需求。默认不加 ORM 表。

## 11. 回滚总策略

任意批次任意时刻：
1. 关对应 flag（`v2_shadow`->`v1_only` / `shadow`->`disabled`）。
2. 停止新 V2 run（进行中 shadow run 可完成或中止，不写 V1）。
3. V2 shadow 数据保留只读审计（不立即删，除非用户要求）。
4. 验证 M7 smoke + 回归 -> 与 M7 基线等价。
5. 图谱通过 active snapshot pointer 回退。
6. Migration 回滚：drop shadow 表（down），V1 表未动。

**关 flag 即恢复 V1** 是每批退出门禁硬验证项。

## 12. P1-09 执行约束

- 每批开始前报告：身份、分支、HEAD、worktree、批准契约、计划改动共享文件、migration 影响、flag、fallback、回滚、测试。
- 每批结束报告：回归结果、migration 证据、flag 与默认值、fallback 行为、回滚指令、外部服务、git checks。
- **不 commit/push/merge/rebase/装依赖**，除非用户明确授权。
- P1-10 独立门禁：每批退出前 P1-10 出具独立验证。
- P1-00 审批每批进入/退出。

## 13. G3 不做的事

- 不启用 `v2_preferred_with_v1_fallback`（G6）或 `v2_only`。
- 不把 Memory 注入正式 QA Prompt（G6）。
- 不二次调用生成模型（G3C）。
- 不正式挂载前端 Viewer（G4）。
- 不删旧字段/路径/endpoint。
- 不把 V2 结果写入 V1 表/索引/任务状态。
- 不改 P1-01~P1-08 私有算法；不弱化 P1-10 测试。
- 不调用真实 Docling/PaddleOCR/向量模型/LLM（shadow 用 fake/离线；真实对比留 G5）。
- 不迁移 V1 历史数据（G4/G5）。
- 不修改 M7 维护分支 `refactor/codemind-v3`。
- 不由 P1-09 修领域契约版本（G2.1 各 owner 修）。

## 14. 审批与启动

本 ADR 为方案，**不修改任何生产代码**。审批流程：
1. 人工审批本 ADR（Rev 1）+ 修正后复核报告。
2. **G2.1**：P1-02/03/07/08 各自补版本常量 -> P1-00 更新 registry -> P1-10 验证 -> 新冻结 SHA。
3. ADR-0006 标记 Accepted。
4. P1-09 worktree 从 G2.1 新冻结 SHA 创建。
5. P1-09 按 G3A -> G3E2 顺序执行，每批人工放行。
6. G4（DTO 冻结 + 前端挂载）在 G3 全部退出后。

## 15. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| document.py/document_service.py 改动破坏 M7 | G3B 仅加 adapter seam，不改现有路由；独立 router 承载新 endpoint |
| Memory 注入改变 V1 回答 | G3D2 硬约束不注入 QA Prompt；正式注入留 G6 |
| 前端挂载形成未冻结 DTO | G3 不挂载；G4A 先冻结 DTO 再 G4B 挂载 |
| Flag 非法值误开 V2 | 启动级 fail-fast（拒绝启动） |
| 配置错误被掩盖 | fail-fast 明确报错，不静默回退 |
| Shadow 写 V1 表 | 退出门禁硬验证无 V1 表写入（P1-10） |
| V2 拖垮 V1（CPU/内存/磁盘/延迟） | G3B 资源规则：单课程单任务/幂等/队列满跳过/超时/不占 M7 GPU/磁盘配额 |
| G3C 二次调 LLM | 硬约束不调；P1-10 验证 trace 无生成模型调用 |
| V2 Router 越权/泄漏 | 管理员only + course 隔离 + 去敏 + 503 SHADOW_FEATURE_DISABLED |
| Migration 误伤 V1 | 只加 shadow 表；空库+旧库副本+down |
| 图谱双事实源 | V2 独立 shadow store，不写 V1 KnowledgePoint |
| 跨课程/学生污染 | RISK-03/05 对抗测试每批验证 |
