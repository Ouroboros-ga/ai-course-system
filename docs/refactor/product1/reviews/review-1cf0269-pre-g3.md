# 冻结点 1cf0269 只读整体复核报告

> 复核人: P1-00
> 日期: 2026-07-14
> 复核对象: `feature/product1-integration` @ `1cf0269`（第三批冻结点，G3 起点）
> 复核性质: 只读。未修改任何生产代码、ORM、Migration、公开 API、生产 endpoint、公共配置或前端共享文件。
> 结论: **复核通过**，可起草 ADR-0006。发现 3 项 minor 瑕疵（不阻断 G3，建议 G3A 前补齐）。

## 1. 工作区状态

| 项 | 结果 |
| --- | --- |
| integration 分支 | `feature/product1-integration` |
| HEAD | `1cf02697d294ab514571aef560311ca3779f8933`（`1cf0269`） |
| 工作树 | 干净（`git status --short` 空） |
| worktree 数 | 9 个 agent worktree（P1-01~P1-08、P1-10），均在各自分支；P1-09 worktree 未建（G3 未启动，符合预期） |

各 agent worktree HEAD 与已合流 commit 一致：
- P1-01 `99c1137`、P1-02 `cd7b0f1`、P1-03 `c0462f5`、P1-04 `ad36f2e`、P1-05 `4d5f63b`、P1-06 `eb1d0f0`、P1-07 `9d37644`、P1-08 `a77ec65`、P1-10 `abf4213`

9 个 agent 分支均 **0 unmerged commits**（全部已合流到 `1cf0269`）。

## 2. Owner 边界复核（共享文件未被越权修改）

对比 M7 基线 `f98ce19` -> `1cf0269`，所有 P1-09 独占的共享生产文件 **UNCHANGED**：

| 文件 | 状态 |
| --- | --- |
| `backend/app/main.py` | UNCHANGED ✓ |
| `backend/app/core/config.py` | UNCHANGED ✓ |
| `backend/app/api/v1/endpoints/document.py` | UNCHANGED ✓ |
| `backend/app/api/v1/endpoints/chat.py` | UNCHANGED ✓ |
| `backend/app/services/document_service.py` | UNCHANGED ✓ |
| `backend/app/services/qa_service.py` | UNCHANGED ✓ |
| `backend/app/services/progress_service.py` | UNCHANGED ✓ |
| `backend/app/services/prerequisite_service.py` | UNCHANGED ✓ |
| `backend/app/models/database.py` | UNCHANGED ✓ |
| `backend/app/common/db_migrator.py` | UNCHANGED ✓ |
| `frontend/src/router/index.js` | UNCHANGED ✓ |
| `frontend/src/utils/request.js` | UNCHANGED ✓ |
| `frontend/src/views/TeacherDashboard.vue` | UNCHANGED ✓ |
| `frontend/src/views/StudentDashboard.vue` | UNCHANGED ✓ |
| `frontend/src/components/SplitVideoPlayer.vue` | UNCHANGED ✓ |
| `backend/pyproject.toml` / `uv.lock` | UNCHANGED ✓ |
| `frontend/package.json` / `package-lock.json` | UNCHANGED ✓ |

仅 2 个文件变更，均为 P1-10 合法所有权范围：
- `backend/tests/conftest.py`：纯增量（+50 行，8 个新 P1-10 fake fixture，追加在 `temp_media_dir` 后，未动现有 fixture 与 `pytest_sessionfinish`）
- `backend/tests/fakes.py`：纯增量（9 个原有 Fake 类**全部保留**，新增 7 个：FakeParserProvider/FakeRetrieverProvider/FakeMasteryProvider/FakeSafetyProvider/FakeMemoryStore/FakeLearningEventStore/FakeCitationValidator）。无弱化、无删除、无断言改写。

**结论**：P1-09 共享生产文件零触及；P1-10 测试基建改动合法且纯增量。Owner 边界严格。

## 3. 契约版本一致性

registry.md 登记的 13 个 frozen-major 契约 + 代码内声明对照：

| 契约 | registry 版本 | 代码内声明 | 一致性 |
| --- | --- | --- | --- |
| DocumentIR/Geometry (P1-01) | `document-ir/1.0` | `CURRENT_SCHEMA_VERSION = SchemaVersion(major=1, minor=0)` | ✓ 一致 |
| LearningEvent/Evidence (P1-07) | `learning/1.0` | `EVENT_VERSION="1.0"` / `EVIDENCE_VERSION="1.0"` | ✓ 一致 |
| SafetyDecision (P1-08) | `safety/1.0` | docstring 声明（无常量） | ⚠ minor：无常量 |
| EducationalUnit/GraphSnapshot (P1-05) | `edu-graph/1.0` | `ONTOLOGY_VERSION="edu-graph/1.0"` | ✓ 一致 |
| StudentMemory (P1-06) | `student-memory/1.0` | `STUDENT_MEMORY_VERSION` 常量 | ✓ 一致 |
| ParserProvider (P1-02) | `parser-provider/1.0` | docstring 声明 | ⚠ minor：无常量 |
| EvidenceSpan/Bundle (P1-03) | `evidence/1.0` | docstring `evidence/1` | ⚠ **版本字符串不一致**（registry `1.0` vs 代码 `1`） |
| TextTransformMap (P1-03) | `text-transform/1.0` | docstring `text-transform/1.0` | ✓ 一致 |
| Citation (P1-03) | `citation/1.0` | docstring `citation/1.0` | ✓ 一致 |
| RetrievedChunk (P1-03) | minor 增量 | optional 字段 | ✓ 一致 |
| retrieval-provider (P1-03) | `retrieval-provider/1.0` | - | ✓ 一致 |

**发现 3 项 minor 瑕疵**（不阻断 G3）：
1. **P1-03 Evidence 版本字符串不一致**：registry 登记 `evidence/1.0`，代码 docstring 写 `evidence/1`。建议统一为 `evidence/1.0`。
2. **P1-03 evidence/citation 无版本常量**：仅 docstring 声明，无 `EVIDENCE_VERSION`/`CITATION_VERSION` 常量。G3 接线时消费者无法从代码读取版本做 fail-closed 校验。建议补常量。
3. **P1-07 mastery provider_version 内部不一致**：`contracts.py` 默认 `"1.0"`（两段），`rule_baseline.py:208` 用 `"1.0.0"`（三段）。provider 自身版本（非 schema 契约），但应统一。
4. **P1-08 safety / P1-02 parser 无版本常量**：仅 docstring，建议补常量便于 G3 校验。

以上均为文档/常量补齐，不涉及契约语义变更，建议作为 G3A 前置小任务（minor，各 owner 补常量 + 统一字符串）。

## 4. 跨域依赖方向（无循环）

各 agent 模块 `app.*` 导入方向复核：

| 模块 | 导入方向 | 循环 | 结论 |
| --- | --- | --- | --- |
| P1-01 document_intelligence | 无 `app.*` 导入（纯标准库） | - | ✓ 最底层契约 |
| P1-02 parser providers | 相对导入 `..source_artifact`/`..registry`/`..planner`（P1-01 同包） | 无 | ✓ 消费 P1-01 |
| P1-03 evidence/retrieval | 仅自身（evidence/retrieval 内部互引） | 无 | ✓ 不导入 P1-02/05/07/08 |
| P1-05 education_graph | `evidence.contracts`（P1-03）+ 自身；P1-01 用 str 引用（`doc_id:str`/`block_ids:List[str]`） | 无 | ✓ 消费 P1-01(str)+P1-03 |
| P1-06 student_memory | 仅自身；P1-07 用 str 引用（`evidence_refs:List[str]`） | 无 | ✓ 消费 P1-07(str) |
| P1-07 learning/mastery | 无 `app.*` 导入（纯标准库） | 无 | ✓ 最底层契约 |
| P1-08 safety | 无 `app.*` 导入（纯标准库） | 无 | ✓ 最底层契约 |

**循环依赖全部拆除**（符合规划 §6 拆除策略）：
- DocumentIR↔Evidence：Evidence 字符串引用 stable block refs，不导入 DocumentIR 类 ✓
- Memory↔Cognition：Memory 字符串引用 LearningEvidence evidence_ids，不导入 P1-07 ✓
- Retrieval↔Graph：Graph 可选引用 evidence.contracts（P1-03），不调用 QA ✓
- Safety↔QA：Safety 无 QA 导入（QA hook 由 P1-09 接）✓
- Provider↔DocumentService：Provider 用相对导入消费 P1-01，不导入旧 DocumentService ✓

## 5. 测试可重现性

在 `1cf0269` 干净重跑（共享 venv `E:/smartcarb/ai-course-system/backend/.venv`）：

| 套件 | 结果 | 与历史一致 |
| --- | --- | --- |
| Product 1 全量（8 目录） | 663 passed | ✓ 与第三批冻结时一致 |
| 现有回归（13 文件） | 116 passed, 0 failed | ✓ 与 G1/G2 一致，零回归 |

测试目录覆盖：document_intelligence(111) + providers(122) + learning(106) + safety(86) + evidence/retrieval(59) + student_memory(76) + education_graph(79) + product1(24) = 663。P1-04 前端 127 node 测试独立运行（不在 pytest 计数）。

测试可重现，无 flaky，无外部服务依赖（全 fake/离线）。

## 6. 契约状态汇总

- **frozen-major**: 13 个（DocumentIR/Geometry、LearningEvent/Evidence/Mastery、SafetyDecision、EducationalUnit/GraphSnapshot、StudentMemory、ParserProvider、EvidenceSpan/Bundle、TextTransformMap、Citation、RetrievedChunk、retrieval-provider）
- **consumed**: 1 个（TaskResult/TaskStatus，R2B/R2C 现有）
- **draft**: 1 个（公开 V2 API DTO，留 G4）

至此除公开 V2 API DTO 外，全部跨域契约已冻结。G3 上游契约齐备。

## 7. 复核结论

**通过**。`1cf0269` 满足 G3 启动前置：
- 工作区干净，9 agent 分支全合流
- P1-09 共享生产文件零触及，P1-10 测试基建改动纯增量
- 13 契约 frozen-major，跨域依赖无循环
- 663 + 116 测试可重现，零回归

**3 项 minor 瑕疵**（建议 G3A 前补齐，不阻断 ADR-0006 起草）：
1. P1-03 Evidence 版本字符串统一（`evidence/1` -> `evidence/1.0`）
2. P1-03/P1-08/P1-02 补版本常量（便于 G3 fail-closed 校验）
3. P1-07 mastery provider_version 统一（两段 vs 三段）

建议在 ADR-0006 中将这 3 项列为 G3A 进入门禁的前置小任务。

## 8. 复核期间未执行的操作

- 未修改任何文件（生产代码、ORM、Migration、公开 API、endpoint、配置、前端共享、conftest/fakes）
- 未 commit / push / merge / rebase
- 未安装依赖
- 未调用真实外部服务
- 未创建/删除 worktree
