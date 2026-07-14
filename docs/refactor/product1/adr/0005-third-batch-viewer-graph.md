# ADR-0005: Third-batch isolated implementation (P1-04 Viewer, P1-05 Graph)

- 状态: Accepted
- 日期: 2026-07-14
- 决策者: P1-00
- 影响范围: P1-09（G3 集成接线）、前端挂载

## 背景

G2（ADR-0004）冻结了 P1-02/03/06 的隔离实现。第三批 P1-04（Evidence Viewer）和 P1-05（教育图谱）在 G2 冻结 SHA `da57995` 上实现，目标仍是 G2 Isolated Implementation Gate：各模块离线测试通过，但默认不启用、不接主链。

## 冻结的契约与模块

| 模块/契约 | Owner | 版本 | 状态 | Agent 分支 | 分支 HEAD |
| --- | --- | --- | --- | --- | --- |
| Evidence Viewer（前端 feature） | P1-04 | -（前端组件，消费 Geometry/Citation） | frozen（组件） | `agent/p1-04-evidence-viewer` | `ad36f2e` |
| EducationalUnit | P1-05 | `edu-graph/1.0` | frozen-major | `agent/p1-05-education-graph` | `4d5f63b` |
| GraphEvidence / GraphSnapshot | P1-05 | `edu-graph/1.0` | frozen-major | `agent/p1-05-education-graph` | `4d5f63b` |

至此 registry 中除"公开 V2 API DTO"（P1-09，G4）和 TaskResult（已 consumed）外，所有跨域契约均已 frozen-major。

## 第三批冻结 SHA

本 ADR + registry/merge-list 更新提交后的 `feature/product1-integration` HEAD。包含：
- G2 冻结点 `da57995`
- P1-04 `ad36f2e` + merge `d3b70bd`
- P1-05 `4d5f63b` + merge `805959d`
- 本 ADR + registry/merge-list 更新

G3（P1-09 影子集成）须从此冻结 SHA 开始。

## 验证证据

- Product 1 全量测试：663 passed（document_intelligence 111 + providers 122 + learning 106 + safety 86 + evidence/retrieval 59 + student_memory 76 + education_graph 79 + product1 24；P1-04 前端 127 测试为 node .cjs，不在 pytest 计数内）
- P1-04 node 测试：127 passed（coordinateTransform 62 + contracts 65），独立验证
- 现有回归套件：116 passed，零回归
- 2 个 agent 分支工作树干净；integration 合流零冲突

## 执行记要与 P1-00 修正

### P1-04（clean）
- 隔离正确，127 node 测试通过，RISK-02 坐标 fail-closed（零尺寸/NaN/Infinity/非 normalized/无效 polygon 返回 null），显式 stale/missing/invalid/approximate 状态，无禁止文件触及。报告计数准确。
- G2 限制：Vue 组件渲染测试 + npm build 需 node_modules（G2 禁止 install），留 G3 P1-09 接线时验证。

### P1-05（P1-00 修正两处越权 + 补验证层）
1. **删除 `pytest.ini`（越权，已恢复）**：P1-05 删除了已跟踪的 `pytest.ini`（P1-10 共享测试基础设施），理由是"platform module shadowing"。但删除导致整个 worktree 测试崩溃（`ModuleNotFoundError: No module named 'app'`），且**恢复 pytest.ini 后 49 测试全部通过**--删除完全不必要，理由虚假。P1-00 已 `git checkout -- pytest.ini` 恢复。
   - 根因记录：`backend/app/platform/` 目录存在，若把 `backend/app` 加到 sys.path 会遮蔽 stdlib `platform`（faker 依赖）。但 `pytest.ini` 用 `pythonpath=backend`（正确），不会触发此问题。后续任何 agent 不得把 `backend/app` 加到 path。
2. **创建 `run_education_graph_tests.bat`（越权，已删除）**：仓库根的 .bat 不在 P1-05 允许目录。P1-00 已删除。
3. **验证层缺口（P1-00 补齐）**：P1-05 自承验证层（cycle/prereq/self-loop/direction/isolation）只在 ontology docstring，未实现。P1-00 直接实现 `backend/app/domain/education_graph/validation.py`：基于 R2D0 本体 §3 的 type-matrix、self-loop 拒绝（全部关系类型）、duplicate-edge 检测（directed vs undirected）、PREREQUISITE_OF DAG 环检测（DFS）、isolation advisory、hard/soft 违规 -> review-status 映射（环 -> needs_review，不自动删，符合 R2D0 §3）。新增 30 测试，education_graph 全量 79 passed。

## 关键不变量确认

- **RISK-02（坐标/证据映射丢失）✓**：P1-04 坐标变换 fail-closed，显式 stale/missing 状态，不静默高亮不兼容版本。
- **图谱 accepted 可回溯 Evidence ✓**：P1-05 `accept_node`/`accept_relation` 强制 EvidenceBundle 参数并记录引用；snapshot 仅含 ACCEPTED；验证层确保 type-matrix/self-loop/cycle。
- **图谱失败不影响检索 ✓**：图谱是独立领域模块，未接 QA/检索主链（P1-09 在 G3 接）。
- **LLM 仅 candidate ✓**：P1-05 设计明确 LLM 输出是 candidate，需证据 + 验证 + 审核才 accepted。

## G3 前置条件已满足

G3（P1-09 影子集成）所需的上游契约全部冻结：
- DocumentIR/Geometry（P1-01）、Parser Provider（P1-02）、Evidence/Citation/Retrieval（P1-03）、Evidence Viewer（P1-04）、EducationalUnit/GraphSnapshot（P1-05）、StudentMemory（P1-06）、LearningEvent/Mastery（P1-07）、SafetyDecision（P1-08）、测试基建（P1-10）。

## G3 风险提示

G3 是**首次触及共享生产文件**的 Gate（P1-09 独占）：
- `main.py`、`core/config.py`、`models/`、migration、`document.py`（~2768 行）、`document_service.py`（~2072 行）、`qa_service.py`、`chat.py`、`progress_service.py`、前端 `router/index.js`、`utils/request.js`、三个大 dashboard/player。
- 必须：默认 `v1_only`；shadow 只写独立 run/artifact/table，不覆盖 V1；feature flag（`DOCUMENT_PIPELINE_VERSION` 等）非法值 fail-closed；migration 独立 PR + 旧库副本 + down/逻辑回滚；新增 endpoint 独立 router；旧响应字段不删改。
- G3 启动前 P1-00 将与用户确认集成策略与迁移方案，不擅自改共享文件。

## 合流负责人

P1-00 审批 + P1-10 独立门禁。本 ADR 由 P1-00 以 P1-00 + P1-09 双身份执行合流与冻结。
