# Product 1 契约登记表 (Contract Registry)

> Owner: P1-00（主协调与契约治理）
> 维护规则：本登记表由 P1-00 唯一维护。业务 Agent 不得直接编辑本文件，需通过《契约变更申请》（见 `versioning-rules.md`）提交，P1-00 审批后登记。
> 状态口径：`draft`（仅设计/草拟）→ `frozen-major`（major 已冻结，可被消费者依赖）→ `consumed`（已有消费者接入并通过 contract test）。

## 1. 契约清单

| 契约 | Owner | 消费方 | 向后兼容要求 | 变更审批 | 当前版本 | 状态 | 冻结 Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `DocumentIR` / block union | P1-01 | P1-02、P1-03、P1-05、P1-09、P1-10 | stable ID 不受 run/time/status 影响；旧 minor 可读 | P1-00 + 所有直接消费者 | `document-ir/1.0` | frozen-major | G1 ✅ |
| `Geometry` / `Polygon` | P1-01 | P1-02、P1-03、P1-04、P1-10 | 明确坐标空间、原点、页尺寸、旋转；不得静默换单位 | P1-00 + P1-04 | `document-ir/1.0` | frozen-major | G1 ✅ |
| `EvidenceSpan` / `EvidenceBundle` | P1-03 | P1-04、P1-05、P1-08、P1-09、P1-10 | 必须引用存在的 artifact/version/block；失效显式返回 | P1-00 + P1-01 | `evidence/1.0` | frozen-major | G2 ✅ |
| `TextTransformMap` / `ChunkSegment` / `SemanticChunk` | P1-03 | 检索、Citation Validator、评测 | chunk 变更不能丢原字符映射 | P1-00 + P1-10 | `text-transform/1.0` | frozen-major | G2 ✅ |
| `RetrievedChunk` | P1-03 | QA、图检索、评测 | 保留现有内部字段；evidence 字段 optional 增量后逐步必填 | P1-00 + P1-09 | 过渡版+evidence optional | frozen-major（minor 增量） | G2 ✅ |
| `Citation` / `CitationValidationResult` | P1-03 | P1-04、P1-08、P1-09、P1-10 | citation key 稳定；无证据不能生成伪 key | P1-00 + P1-04/P1-08 | `citation/1.0` | frozen-major | G2 ✅ |
| `EducationalUnit` | P1-05 | 图谱、脚本兼容投影、学情映射 | 只引用 DocumentIR stable IDs；层级调整有版本 | P1-00 + P1-01 | `edu-graph/1.0` | frozen-major | G2 ✅ |
| `GraphEvidence` / `GraphSnapshot` | P1-05 | 检索、审核、P1-09 存储 | snapshot 不可变；active pointer 可回退；accepted 必有 Evidence | P1-00 + P1-03/P1-09 | `edu-graph/1.0` | frozen-major | G2 ✅ |
| `LearningEvent` | P1-07 | P1-06、报告、推荐、评测 | append-only 事实；更正用新事件；幂等键稳定 | P1-00 + P1-06/P1-09 | `learning/1.0` | frozen-major | G1 ✅ |
| `LearningEvidence` / `MasteryState` | P1-07 | P1-06、教师报告、推荐 | 结论必须保留 event refs、provider/version | P1-00 + P1-10 | `learning/1.0` | frozen-major | G1 ✅ |
| `StudentMemory` / `MemoryEntry` | P1-06 | QA 上下文、学生/教师视图、审计 | 删除/关闭语义不可弱化；跨课程默认不共享 | P1-00 + P1-08/P1-09 | `student-memory/1.0` | frozen-major | G2 ✅ |
| `ParserProvider` / `QualityDecision` / `ParsePlan` | P1-02 | P1-09（接线）、P1-10（评测） | 消费 document-ir/1.0；质量失败与运行时失败分离；不编造结构 | P1-00 + P1-01 | `parser-provider/1.0` | frozen-major | G2 ✅ |
| `SafetyDecision` / `AuditEvent` | P1-08 | QA、检索、前端、审计 | reason code 稳定；平台底线不能被课程策略覆盖 | P1-00 + P1-09/P1-10 | `safety/1.0` | frozen-major | G1 ✅ |
| `TaskResult` / `TaskStatus` | P1-09（维护现有契约） | 所有异步/外部任务 | 不改变 R2B/R2C 现有映射；只增 optional metadata | P1-00 + P1-10 | 现有版 | consumed | — |
| 公开 V2 API DTO | P1-09 | 前端、P1-10 | 旧路径和原字段不删改；新字段可选；旧前端可工作 | P1-00 + 前端 contract review | — | draft | G4 |

## 2. 冻结规则

- 契约进入 `frozen-major` 前，消费者不得将其字段当作稳定依赖实现。
- `major.minor`：删字段、改语义、改 ID 算法、扩大默认可见范围属于 major；新增 optional 字段属于 minor。
- 未知 major 必须 fail-closed。
- 契约 Owner 负责修改；消费者不得直接编辑契约定义文件。
- 任何变更须：ADR + schema diff + contract tests + P1-00 与 P1-10 审批（按上表“变更审批”列）。
- `RetrievedChunk` 当前为过渡版（`chunk_id` 仅为内存树节点 ID），不能冒充 DocumentIR block/evidence ID；待 P1-03 增量绑定 stable source/version/block/evidence 后，经 P1-00 + P1-09 审批再逐步必填。

## 3. 当前可启动边界

- 第一批（P1-01、P1-07、P1-08、P1-10）可同时启动契约草拟与实现；均不依赖其他契约冻结。
- P1-03 可起草 Evidence 契约，但实现必须等待 P1-01 stable block/geometry 冻结。
- P1-02 须等待 P1-01 `DocumentIR` minor 冻结。
- P1-04、P1-05 须等待 `Evidence`/`Geometry` 契约冻结。
- P1-06 须等待 `LearningEvent`/`LearningEvidence` 冻结。
- P1-09 共享文件接线须等待对应 contract test 与质量门禁通过。
