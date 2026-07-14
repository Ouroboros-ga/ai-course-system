# ADR-0004: G2 Isolated Implementation Freeze (second batch)

- 状态: Accepted
- 日期: 2026-07-14
- 决策者: P1-00
- 影响范围: P1-04、P1-05（第三批）、P1-09（集成接线）

## 背景

G1（ADR-0003）冻结了 P1-01/07/08/10 的契约。第二批 P1-02、P1-03、P1-06 在 G1 冻结 SHA `657bfe5` 上实现隔离模块（Provider、Evidence/Retrieval、Memory），目标是 G2 Isolated Implementation Gate：各模块离线单元/contract tests 通过，但默认不启用、不写 V1。

## 执行记要

第二批 3 个后台子 agent（`general-purpose`，显式 `cd` 到各自 worktree）：
- **隔离成功**：首批的混布问题未复发，3 个 agent 都在自己 worktree 工作（`ai-course-p1-02/03/06`，均 HEAD `657bfe5`）。
- **API 超时影响报告**：P1-02 和 P1-06 在完成实现+测试后、输出完成报告前因 API 超时终止（与首批 P1-07 同样的 `API Error: The operation timed out`），完成报告缺失。但文件和测试都已写完，P1-00 直接跑测试和 grep 验证补全 review（不依赖缺失的报告）。P1-03 正常返回报告，但其测试计数夸大（声称 63，实际 59），功能无缺陷。

## 冻结的契约与模块

| 模块/契约 | Owner | 版本 | 状态 | Agent 分支 | 分支 HEAD |
| --- | --- | --- | --- | --- | --- |
| ParserProvider/Registry + QualityDecision | P1-02 | `parser-provider/1.0` | frozen-major | `agent/p1-02-parser-quality` | `cd7b0f1` |
| EvidenceSpan/EvidenceBundle | P1-03 | `evidence/1.0` | frozen-major | `agent/p1-03-evidence-retrieval` | `c0462f5` |
| TextTransformMap/ChunkSegment/SemanticChunk | P1-03 | `text-transform/1.0` | frozen-major | `agent/p1-03-evidence-retrieval` | `c0462f5` |
| RetrievedChunk（evidence optional 增量） | P1-03 | minor 增量 | frozen-major | `agent/p1-03-evidence-retrieval` | `c0462f5` |
| Citation/CitationValidationResult | P1-03 | `citation/1.0` | frozen-major | `agent/p1-03-evidence-retrieval` | `c0462f5` |
| BM25/Vector/Reranker Provider 协议 | P1-03 | `retrieval-provider/1.0` | frozen-major | `agent/p1-03-evidence-retrieval` | `c0462f5` |
| StudentMemory/MemoryEntry | P1-06 | `student-memory/1.0` | frozen-major | `agent/p1-06-student-memory` | `eb1d0f0` |

未冻结：EducationalUnit/GraphEvidence（P1-05，待实现）；公开 V2 API DTO（P1-09，G4）。

## G2 冻结 SHA

本 ADR + registry 更新提交后的 `feature/product1-integration` HEAD。包含：
- G1 冻结点 `657bfe5`
- P1-02 `cd7b0f1` + merge `adb08e9`
- P1-03 `c0462f5` + merge `376ec68`
- P1-06 `eb1d0f0` + merge `a0a14c6`
- 本 ADR + registry/merge-list 更新

第三批（P1-04 Viewer、P1-05 Graph）worktree 须从此冻结 SHA 创建：P1-04 消费 P1-03 Evidence/Geometry/Citation；P1-05 消费 P1-01 DocumentIR + P1-03 Evidence。

## 验证证据

- Product 1 全量测试：584 passed（document_intelligence 111 + providers 122 + learning 106 + safety 86 + evidence/retrieval 59 + student_memory 76 + product1 24）
- 现有回归套件：116 passed（M4A/M4B/M7/R1/R2B/R2C/retrieval/scope），零回归
- 3 个 agent 分支工作树干净；integration 合流零冲突
- 所有权边界：每个 agent 仅改各自目录；无共享文件（main.py/config.py/document.py/qa_service.py/chat.py/ORM/migration/conftest.py/fakes.py）被改
- 关键不变量：
  - RISK-03（跨课程污染）：P1-03 missing scope 返回空（不回退全局），无 block_id 不伪造 citation key，NO_EVIDENCE abstain=True
  - RISK-05（隐私/删除）：P1-06 SOFT/HARD_DELETED 语义，DISABLED 不读写，(student_id,course_id) scope 跨课程默认拒绝
  - P1-02 QualityDecision 明确分离 quality failure 与 runtime failure，不编造结构

## 模块状态（G2 准入）

- **P1-02**：Provider/质量路由/探测/规划/reconciliation + native PPTX provider + Docling/OCR fake。默认不接 upload 主链（P1-09 接线在 G3）。
- **P1-03**：Evidence/Citation/检索 Provider 协议 + RRF。RetrievedChunk evidence 字段 optional（TreeRetrieverProvider 暂不填充，DocumentIR-backed provider 接入后填充）。Citation 未接 QAService（P1-09 在 G3 接 hook）。
- **P1-06**：Memory 领域 + Repository protocol + fake（无 ORM）。前端 feature 独立。未接 QA 上下文注入（P1-09 在 G3）。

## 解锁的下游

- **P1-04**（Evidence Viewer）：P1-03 Evidence/Citation + P1-01 Geometry 已冻结 -> **可启动**。
- **P1-05**（教育图谱）：P1-01 DocumentIR + P1-03 Evidence 已冻结 -> **可启动**。
- **P1-09**（集成接线）：G2 模块齐备后可进入 G3 Shadow Integration（默认 v1_only，shadow 接入主链）。

## 合流负责人

P1-00 审批 + P1-10 独立门禁。本 ADR 由 P1-00 以 P1-00 + P1-09 双身份执行合流与冻结。
