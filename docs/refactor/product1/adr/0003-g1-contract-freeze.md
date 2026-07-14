# ADR-0003: G1 Contract Freeze

- 状态: Accepted
- 日期: 2026-07-14
- 决策者: P1-00
- 影响范围: P1-02、P1-03、P1-04、P1-05、P1-06（第二批及以后）

## 背景

《分配方案》§8.1 定义 G1 Contract Gate：schema/ID/scope/delete contract tests 通过后，P1-01、P1-03、P1-07、P1-08 的契约可合流。本 ADR 记录第一批（P1-01、P1-07、P1-08、P1-10）的 G1 冻结。

ADR-0002 启动了第一批。实际执行中发生隔离失败（见下"执行记要"），经抢救、分发、修复后，4 个 agent 的契约均已验证通过并合流到 `feature/product1-integration`。

## 冻结的契约

| 契约 | Owner | 版本 | 状态 | Agent 分支 | Agent 分支 HEAD |
| --- | --- | --- | --- | --- | --- |
| `DocumentIR` / block union | P1-01 | `document-ir/1.0` | frozen-major | `agent/p1-01-document-ir` | `99c1137` |
| `Geometry` / `Polygon` | P1-01 | `document-ir/1.0` | frozen-major | `agent/p1-01-document-ir` | `99c1137` |
| `LearningEvent` | P1-07 | `learning/1.0` | frozen-major | `agent/p1-07-learning-cognition` | `9d37644` |
| `LearningEvidence` / `MasteryState` | P1-07 | `learning/1.0` | frozen-major | `agent/p1-07-learning-cognition` | `9d37644` |
| `SafetyDecision` / `AuditEvent` | P1-08 | `safety/1.0` | frozen-major | `agent/p1-08-safety-governance` | `a77ec65` |
| Product 1 测试基建 | P1-10 | -（基础设施） | frozen（基建） | `agent/p1-10-quality-gate` | `abf4213` |

P1-03（Evidence/Retrieval/Citation）、P1-05（EducationalUnit/GraphEvidence）、P1-06（StudentMemory）契约本轮**未冻结**，仍为 draft，待其 owner 实现。

## 冻结 SHA

G1 冻结 SHA = `657bfe5`（`feature/product1-integration`，2026-07-14）。该 SHA 包含：
- ADR-0001/0002 协调基线（`2c743f7`）
- P1-01 DocumentIR 契约（`3bb8224` + 版本号统一 `99c1137`）
- P1-07 LearningEvent 契约（`9d37644`）
- P1-08 SafetyDecision 契约（`a77ec65`）
- P1-10 测试基建（`abf4213`）
- 4 个 merge commit（`4cf7ddd`/`7ea1266`/`b8d09e9`/`135e273`）
- domain 顶层 `__init__.py` 接线（`b7b71e5`）
- 本 ADR + registry/merge-list 更新

后续批次（P1-02、P1-03 等）的 worktree 与分支须从该冻结 SHA 创建，确保能看到已冻结契约与协调文档。

## 验证证据

- Product 1 契约测试：327 passed（document_intelligence 111 + learning 106 + safety 86 + product1 24）
- 现有回归套件：116 passed（M4A/M4B/M7/R1/R2B/R2C/retrieval/scope），零回归
- 4 个 agent 分支工作树干净；integration 线合流零冲突
- 所有权边界：每个 agent 仅改各自目录；P1-10 对共享 `conftest.py`/`fakes.py` 的扩展未弱化现有 fake，回归通过
- BKT/IRT/DKT 保持 interface-only（`compute` raise TypeError，无算法实现）

## 版本号约定

P1-01 最初用三段式 `document-ir/1.0.0`，已统一为 `document-ir/1.0`（`major.minor`），与 `versioning-rules.md` 一致。Provider/scorer 自身版本（如 `provider_version="1.0.0"`）不是契约 schema 版本，保留三段式。

## 执行记要：第一批隔离失败与抢救

第一批 4 个后台子 agent（`general-purpose`，因自定义 agent 类型未注册）预期自动隔离 worktree，但 `settings.json` 的 `bgIsolation: worktree` 对 Agent 工具启动的子 agent **未生效**。4 个 agent 全部继承主会话遗留的 Bash 工作目录（`ai-course-p1-01`），工作全部混布在该 worktree。

抢救措施（用户授权"抢救+分发到各分支"）：
1. 将各 agent 工作从 `ai-course-p1-01` 复制到各自预建 worktree（`ai-course-p1-07/08/10`），逐个隔离验证测试。
2. 清理 `ai-course-p1-01`，仅留 P1-01 工作，共享 `conftest.py`/`fakes.py` 还原到 `f98ce19`。
3. P1-07 有 5 个测试失败（重派子 agent 因 API 超时未编辑），由 P1-00 直接修复：quiz 聚合改用 `is_correct` metadata；BKT/IRT/DKT `compute` 从 `@abstractmethod` 改为 raise TypeError（保持 interface-only 且满足 capability + is_abstract 两组测试）；rule_baseline 加权跳过无证据规则。

教训已记入项目记忆：后续批次不依赖 `bgIsolation`，改为显式要求每个子 agent `cd` 到自己的预建 worktree；预建 worktree 基于含协调文档的冻结 SHA。

## 解锁的下游

- **P1-02**（解析 Provider）：须基于本冻结 SHA（P1-01 `document-ir/1.0` minor 已冻结）。
- **P1-03**（Evidence/Retrieval/Citation）：须基于本冻结 SHA（P1-01 stable block/geometry 已冻结）。
- **P1-04**（Evidence Viewer）：须等 P1-03 Evidence/Geometry 契约冻结。
- **P1-05**（教育图谱）：须等 P1-03 Evidence 契约冻结。
- **P1-06**（学生记忆）：须等 P1-07 LearningEvent/LearningEvidence 冻结（**已满足**，可启动）。

## 合流负责人

P1-00 审批 + P1-10 独立门禁。本 ADR 由 P1-00 以 P1-00 + P1-09 双身份执行合流与冻结（P1-09 共享文件接线职责由协调代理代行，因当前无独立 P1-09 agent 实例）。
