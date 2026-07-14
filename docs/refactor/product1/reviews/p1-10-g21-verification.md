# P1-10 G2.1 合流前独立验证报告

> 验证人: P1-10（由 P1-00 协调代理代行）
> 日期: 2026-07-14
> 验证对象: G2.1 Contract Normalization 合流点 `d4894da`（`feature/product1-integration`）
> 验证性质: 合流前独立门禁。P1-10 不替业务 agent 宣布通过。
> 结论: **通过**。G2.1 可标记为新冻结 SHA。

## 1. 验证范围

按用户授权要求，P1-10 在合流前验证 5 项：
1. 版本唯一来源（常量值与 registry 一致）
2. 旧数据兼容（版本 round-trip）
3. 未知 major 拒绝（fail-closed）
4. Owner 路径合规（仅改各自目录，未越界共享文件）
5. 完整回归（663+116 不退化）

## 2. 验证结果

### 2.1 完整回归（第 5 项）

| 套件 | 结果 | 对比 G2.1 前 |
| --- | --- | --- |
| Product 1 全量（8 目录） | 682 passed | 663 + 19 新增 G2.1 测试（P1-02 +4, P1-03 +8, P1-07 +2, P1-08 +5）|
| 现有回归（M4A/M4B/M7/R1/R2B/R2C/retrieval/scope，13 文件） | 116 passed, 0 failed | 零回归 |

测试可重现，无 flaky，无外部服务依赖。

### 2.2 版本唯一来源（第 1 项）

7 个新增/统一的版本常量值全部与 `registry.md` 登记一致：

| 常量 | 代码值 | registry 值 | 一致 |
| --- | --- | --- | --- |
| `PARSER_PROVIDER_VERSION` (P1-02) | `parser-provider/1.0` | `parser-provider/1.0` | ✓ |
| `EVIDENCE_VERSION` (P1-03) | `evidence/1.0` | `evidence/1.0` | ✓ |
| `CITATION_VERSION` (P1-03) | `citation/1.0` | `citation/1.0` | ✓ |
| `TEXT_TRANSFORM_VERSION` (P1-03) | `text-transform/1.0` | `text-transform/1.0` | ✓ |
| `RETRIEVAL_PROVIDER_VERSION` (P1-03) | `retrieval-provider/1.0` | `retrieval-provider/1.0` | ✓ |
| `MASTERY_PROVIDER_VERSION` (P1-07) | `1.0` | `learning/1.0`（provider 自身版本两段） | ✓ |
| `SAFETY_VERSION` (P1-08) | `safety/1.0` | `safety/1.0` | ✓ |

P1-03 的 `evidence/1` docstring 已修正为 `evidence/1.0`，与 registry 一致。

### 2.3 旧数据兼容（第 2 项）

P1-01 DocumentIR JSON round-trip 测试：10 passed。版本序列化/反序列化不变，旧数据可读。

### 2.4 未知 major 拒绝（第 3 项）

P1-01 schema version fail-closed 测试：4 passed。未知 major 仍触发 ValueError（fail-closed），G2.1 未破坏。

### 2.5 Owner 路径合规（第 4 项）

对比 `1cf0269`（G2.1 前）-> `d4894da`（G2.1 后），所有 P1-09 共享文件 UNCHANGED：
- `backend/app/main.py`、`core/config.py`、`api/v1/endpoints/document.py`、`api/v1/endpoints/chat.py`
- `backend/app/services/document_service.py`、`qa_service.py`
- `backend/app/models/database.py`、`common/db_migrator.py`
- `backend/tests/conftest.py`、`fakes.py`
- `backend/scripts/m7_preflight.ps1`（M7 脚本）
- `frontend/src/router/index.js`、`utils/request.js`

G2.1 实际改动 13 个文件，全部在各 owner 自身目录内：
- P1-02：`document_intelligence/quality.py` + `registry.py` + `tests/.../test_parser_provider_version.py`
- P1-03：`evidence/citation.py` + `contracts.py` + `text_transform.py` + `retrieval/providers/contracts.py` + `tests/evidence/test_version_constants.py`
- P1-07：`mastery/contracts.py` + `rule_baseline.py` + `tests/learning/test_g21_mastery_provider_version.py`
- P1-08：`safety/decision.py` + `tests/safety/test_safety_version.py`

无契约字段变更、无业务语义变更、无 API/ORM/Migration/配置/前端共享文件变更。

## 3. 事故记录：P1-03 工作树污染（已清除）

P1-03 子 agent 在 G2.1 执行期间发生**隔离失败**，在主仓库工作目录（非其 worktree）留下 G2.1 范围外的越权改动：
- retrieval 业务逻辑：`RetrievalTrace`/`RetrievalOutcome`/`RetrievalTraceStatus` 类（schemas.py）、gateway.py（+67 行）、test_retrieval_gateway.py（+67 行）、`__init__.py`
- M7 文件：`m7_preflight.ps1`、`M7演示前检查清单.md`、新文件 `M7检索运行约束与恢复预检.md`

**这些改动均未提交**（G2.1 的 4 个合流 commit 内容干净，仅含版本常量）。经用户授权清除，P1-00 已：
- `git checkout --` 还原 6 个修改文件（retrieval ×4 + M7 ×2）
- `rm` 删除 1 个新文件（M7 doc）
- 还原后工作树完全干净，HEAD `d4894da` 仅含 4 个 G2.1 版本常量 commit

P1-10 确认：合流后的 `d4894da` 不含任何越权业务改动或 M7 改动（§2.5 已核验共享文件全 UNCHANGED，G2.1 改动仅 13 个版本常量文件）。

**教训**：`general-purpose` 子 agent 即使被要求显式 cd 到 worktree，仍可能在主仓库工作目录留下操作。后续每批子 agent 结束后，P1-00 须立即核查主仓库工作树是否被污染，再合流。

## 4. G2.1 commit 清单

| Agent | 分支 | Commit | 改动 |
| --- | --- | --- | --- |
| P1-02 | `agent/p1-02-parser-quality` | `1ced93d` | PARSER_PROVIDER_VERSION 常量 + 4 测试 |
| P1-03 | `agent/p1-03-evidence-retrieval` | `4717a70` | 4 版本常量 + evidence/1.0 docstring + 8 测试 |
| P1-07 | `agent/p1-07-learning-cognition` | `c66322b` | MASTERY_PROVIDER_VERSION 统一两段 + 2 测试 |
| P1-08 | `agent/p1-08-safety-governance` | `8af43e4` | SAFETY_VERSION 常量 + 5 测试 |

4 个 merge commit 合流到 `d4894da`，零冲突。

## 5. 验证结论

**通过**。G2.1 Contract Normalization 满足全部 5 项门禁：
- 版本唯一来源 ✓（7 常量与 registry 一致）
- 旧数据兼容 ✓（round-trip 通过）
- 未知 major 拒绝 ✓（fail-closed 未破坏）
- Owner 路径合规 ✓（共享文件全 UNCHANGED，改动仅 13 个 owner 内文件）
- 完整回归 ✓（682 product1 + 116 回归，零退化）

**建议**：`d4894da` 可标记为 G2.1 冻结 SHA，作为 P1-09 G3A 的基线。更新 ADR-0006 基准点为 `d4894da`，状态改为 Accepted-G3A only。

## 6. 验证期间未执行的操作

- 未修改任何文件（生产代码、ORM、Migration、公开 API、endpoint、配置、前端共享、conftest/fakes）
- 未 commit / push / merge / rebase（仅读取 + 跑测试）
- 未安装依赖
- 未调用真实外部服务
