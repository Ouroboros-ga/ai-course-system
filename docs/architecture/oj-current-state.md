# OJ 域现状盘点（OJ-000）

- 产出日期：2026-09-11
- 方式：**逐条实测**（`ls` / `wc -l` / `grep` / `sed` 读源码），非文档推断
- 分支：`dev-liu`
- 用途：OJ bounded context 治理的基线台账。**任何「要不要新建」的判断先查这里。**

---

## 1. 结论速览

```text
活体 OJ 域 ≈ 4800 行后端 + 5191 行前端 + 4869 行测试
codebench.py 是 1 行死壳，不是 OJ 入口
真缺口只有 Activity / Scoreboard / Analytics / 学生页面
```

---

## 2. Routes

### 2.1 `api/v1/endpoints/experiments.py`（1194 行，**25 个端点**）

| # | 方法 | 路径 | 行 | 归属（迁移后） |
|---|---|---|---|---|
| 1 | GET | `/course/{course_id}/definitions` | 307 | problems |
| 2 | POST | `/course/{course_id}/definitions` | 349 | problems |
| 3 | GET | `/course/{course_id}/definitions/{experiment_id}` | 379 | problems |
| 4 | PUT | `/course/{course_id}/definitions/{experiment_id}` | 407 | problems |
| 5 | POST | `/course/{course_id}/definitions/{experiment_id}/publish` | 437 | problems |
| 6 | POST | `/course/{course_id}/definitions/{experiment_id}/archive` | 464 | problems |
| 7 | GET | `/{experiment_id}/versions` | 491 | problems |
| 8 | POST | `/{experiment_id}/versions` | 519 | problems |
| 9 | GET | `/versions/{version_id}` | 557 | problems |
| 10 | PUT | `/versions/{version_id}` | 583 | problems |
| 11 | POST | `/versions/{version_id}/activate` | 616 | problems |
| 12 | POST | `/versions/{version_id}/lock` | 643 | problems |
| 13 | POST | `/{experiment_id}/attempts` | 676 | submissions |
| 14 | GET | `/attempts/{attempt_id}` | 708 | submissions |
| 15 | POST | `/attempts/{attempt_id}/runs`（**202**） | 738 | submissions |
| 16 | POST | `/versions/{version_id}/reference-preview` | 872 | judging |
| 17 | GET | `/attempts/{attempt_id}/runs` | 904 | submissions |
| 18 | GET | `/runs/{run_id}` | 931 | submissions |
| 19 | POST | `/runs/{run_id}/cancel` | 950 | submissions |
| 20 | POST | `/attempts/{attempt_id}/agent-hints` | 987 | intelligence |
| 21 | GET | `/attempts/{attempt_id}/agent-hints` | 1017 | intelligence |
| 22 | POST | `/agent-hints/{hint_id}/review` | 1044 | intelligence |
| 23 | POST | `/runs/{run_id}/diagnosis` | 1077 | intelligence |
| 24 | POST | `/runs/{run_id}/explanation` | 1108 | intelligence |
| 25 | GET | `/runs/{run_id}/diagnosis` | 1171 | intelligence |

### 2.2 `api/v1/endpoints/sandbox.py`（192 行，**3 个端点**）

| 方法 | 路径 | 行 | 说明 |
|---|---|---|---|
| GET | `/health` | 52 | 沙箱健康 |
| POST | `/course/{course_id}/execute` | 69 | **支持 `stdin` 自定义输入**（请求模型 `:49`） |
| GET | `/languages` | 182 | 语言白名单 |

### 2.3 `api/v1/endpoints/codebench.py`

```text
1 行。全文： # 代码实验台相关接口端点
```

**死壳。未注册任何路由。** PR-17 删除。

### 2.4 已确认不存在的路由

- `/api/v1/oj/*` —— 全仓 0 命中
- homework / contest / scoreboard 任何路由 —— 0 命中

---

## 3. Tables（`models/experiment_model.py`，526 行，**13 张**）

| 表 | 行 | 语义 | 状态 |
|---|---|---|---|
| `experiment_definitions` | 54 | ≈ Problem（身份） | KEEP |
| `experiment_versions` | 106 | ≈ ProblemVersion（快照 + `is_locked`） | KEEP |
| `experiment_test_cases` | 165 | ≈ TestCase | KEEP |
| `experiment_attempts` | 205 | ≈ Attempt（`version_id` 固化不可漂移） | KEEP |
| `experiment_runs` | 255 | ≈ Submission / Run | KEEP |
| `coding_challenge_offers` | 324 | 对话式代码挑战邀约 | KEEP（他域） |
| `coding_evidence_episodes` | 359 | 编码学习证据 | KEEP（证据域） |
| `sandbox_execution_leases` | 386 | 正式执行租约 | KEEP（配额域） |
| `free_sandbox_quota_windows` | 399 | 免费沙箱配额窗口 | KEEP（配额域） |
| `experiment_lab_projections` | 415 | 实验台投影 | KEEP |
| `experiment_recommendations` | 434 | 实验推荐 | KEEP |
| `experiment_run_artifacts` | 459 | 运行产物（stdout/stderr/compile） | KEEP |
| `coding_hint_records` | 491 | 提示审计（`hint_level` / `reason_codes` / `policy_version`） | KEEP |

### 3.1 关键字段实测

**`ExperimentDefinition`**（`:46-95`）：

```text
title / description / statement_object_key / language_whitelist
default_version_id          ← 注意：不叫 current_published_version_id
publish_status / knowledge_node_ids / max_attempts / cooldown_minutes
origin（默认 "teacher"）/ visibility（默认 "course_catalog"）
owner_student_id / expires_at
```

**无 `difficulty`，无 `tags`。**（全仓唯一 `difficulty` 在 `coding_challenge_offers:342`，另一张表）

**`ExperimentVersion`**（`:106-152`）：`version_number` / `passing_score`（`Field(ge=1.0, le=1.0)` 钉死 1.0）/
`starter_code` / `is_locked` / `is_active` / `reference_preview_verified_at`。

**`ExperimentRun`**（`:255-312`）：

```text
run_id / attempt_id / course_id / student_id / task_id / idempotency_key
language / source_code / normalized_source_hash / evidence_quality
outcome: RunOutcome  ← 单一枚举，PENDING 与判定混用
passed_count / total_count / score
compile_ok / compile_message / runtime_message / test_summary
cpu_time_ms / wall_time_ms / memory_kb
error_code / error_message
submitted_at / finished_at / cancel_requested_at
```

**无 `state` / `status` 列。无 `run_type` 列。**
运行态挂在 `task_id` → `TaskRecord`。

**`RunOutcome`**（`:242-252`）—— 9 值，`PENDING` 与判定混用：

```text
PENDING / ACCEPTED / WRONG_ANSWER / TIME_LIMIT_EXCEEDED / MEMORY_LIMIT_EXCEEDED
RUNTIME_ERROR / COMPILATION_ERROR / INTERNAL_ERROR / SANDBOX_UNAVAILABLE
```

---

## 4. Services

| 文件 | 行 | 说明 |
|---|---|---|
| `services/experiment_service.py` | **2261** | **最大治理对象**。含定义/版本/发布/尝试/运行/判题编排/参考解校验 |
| `services/sandbox_client.py` | 332 | Judge0 唯一现成出口 |
| `platform/agents/contracts/sandbox.py` | 37 | `SandboxPort` |
| `platform/agents/providers/sandbox/coding.py` | 258 | Sandbox Provider |
| `platform/tasks/*.py` | 3580 | DB 持久化任务框架（含 `experiment_run_queue.py` 163） |

### 4.1 `sandbox_client.py` 已具备（勿重写）

```text
SubmissionStatus        判定枚举
SandboxResourceLimits   资源限制对象
SandboxResult           is_accepted / is_error / is_timeout / is_memory_exceeded
SandboxClient.submit_code(source_code, language, stdin="", expected_output="", limits=None)
SandboxClient.health_check()
SandboxUnavailableError fail-closed
```

### 4.2 任务框架已具备（勿替换）

```text
platform/tasks/
  worker.py            LocalTaskWorker + _ConcurrencyController
  runner.py / status.py / result.py / handlers.py
  experiment_run_queue.py   ← 判题队列
  course_draft_build_queue.py / document_parse_queue.py
  knowledge_build_queue.py / media_manifest_queue.py
表：tasks / task_events / task_resource_links / idempotency_keys
配额：platform_task_concurrency_service.py
```

### 4.3 已知 smells

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| S1 | `experiment_service.py:1112` `_outcome_to_reason` | 判定→`reason` 的 10 条映射表**手写在业务服务里** | **PR-05 已修**：搬进 `domain/oj/judging/verdicts.py::REASON_BY_STATUS` |
| S2 | `experiments.py:319-327` | `list_definitions` 里 `if context.role.value == "student"` —— **endpoint 级角色分支** | 双路径前必须下沉到 serializer |
| S3 | `experiment_model.py:242-252` | `RunOutcome` 状态与判定混用 | **PR-01** |
| S4 | `experiment_service.py` | 2261 行万能 service | PR-03 / PR-04 拆 |
| S5 | `api/v1/endpoints/codebench.py` | 1 行死壳 | PR-17 删 |

---

## 5. Frontend

| 文件 | 行 | 状态 |
|---|---|---|
| `components/codebench/CodeWorkbench.vue` | 1066 | **复用**（CodeMirror 6） |
| `components/codebench/CodeTestCases.vue` | 416 | 复用 |
| `components/codebench/CodeEditor.vue` | 335 | 复用 |
| `components/codebench/CodeOutput.vue` | 322 | 复用 |
| `components/codebench/CodeToolbar.vue` | 290 | 复用 |
| `app/components/course/TeacherExperimentPanel.vue` | 2076 | 复用 |
| `app/pages/course/CourseExperimentsPage.vue` | 438 | 复用 |
| `api/experiments.js` | 123 | 复用 |
| `api/experimentPublishWorkflow.js` | 71 | 复用 |
| `api/experimentPublishContract.js` | 54 | 复用 |

**编辑器是 CodeMirror 6，不是 Monaco。**（`CodeEditor.vue:12-24` 导入 `@codemirror/*`）

### 5.1 前端调用方

```text
frontend/src/app/pages/course/CourseExperimentsPage.vue
frontend/src/app/components/course/TeacherExperimentPanel.vue
frontend/src/app/pages/course/CourseLayout.vue
frontend/src/app/pages/lab/LabLayout.vue
frontend/src/components/codebench/CodeWorkbench.vue
frontend/src/app/router.js
```

### 5.2 现有页面 vs 缺口

| 页面 | 状态 |
|---|---|
| 教师出题工作台 | **已有**（`TeacherExperimentPanel.vue` 2076 行，2026-09-11 重置为双列四段） |
| 学生做题台 | **已有**（`CodeWorkbench`） |
| Run 自定义输入 | **已有**（`POST /sandbox/course/{id}/execute` 带 `stdin`） |
| 学生题库列表 | **缺** |
| 我的提交 / 提交详情 | **缺** |
| Activity 列表 / 详情 | **缺** |
| 教师 Activity 管理 | **缺** |
| Scoreboard | **缺** |
| OJ Analytics | **缺** |

---

## 6. Tests（既有基线，勿重复实现）

| 文件 | 行 | 已锁住的行为 |
|---|---|---|
| `tests/test_experiments.py` | 1991 | 定义/版本/发布/锁定/尝试/运行 |
| `tests/test_experiment_sandbox_contract.py` | 151 | **ACM 终局**（全 AC 才满分 / 任一非 AC 归零）、免费配额 10 次窗口、正式租约跨进程单持有 |
| `tests/test_p1_7_judge0_sandbox_port.py` | 408 | Judge0 Port 构造、降级（unavailable / internal_error）、课程与学生双隔离、artifacts 读取、stdout 截断、bootstrap 注入 |
| `tests/test_sandbox.py` | 618 | 沙箱客户端 |
| `api/__tests__/apiContracts.test.cjs` | 1701 | **前端/后端源码正则断言**（非 HTTP 契约） |
| 合计 | **4869** | |

> **重要**：`apiContracts.test.cjs` 是**读源码 + 正则匹配**，不是 HTTP 级契约测试。
> **拆 `experiment_service.py` 时它不会红。** 行为回归门禁必须靠 pytest。

---

## 7. 已确认的既有事实（决定「不用做」）

| 事实 | 证据 |
|---|---|
| 「Run 自定义输入」已存在 | `sandbox_client.py:163-168` `stdin=""`；`sandbox.py:49` 请求字段，`:170` 透传 |
| 「hidden testcase 不进学生 DTO」已实现 | `experiments.py:572` 注释 + `:198-211` `_serialize_test_case` |
| 学生题库/自练挂点已预留 | `experiment_model.py:87-90` `origin` / `visibility` / `owner_student_id` / `expires_at` |
| 版本冻结已有一层（attempt 级） | `experiment_attempts.version_id`「尝试开始时激活的版本，固化不可漂移」 |
| 标准代码全 AC 校验已存在 | `POST /versions/{id}/reference-preview`（`experiments.py:872`） |
| AI 诊断 / 提示 / 讲解 / 教师复核已上线 | `experiments.py:987-1171` + `coding_hint_records` |
| Judge0 版本 | `deploy/judge0/docker-compose.yml:33` = `judge0/judge0:1.13.1` |
| 依赖现状 | `backend/pyproject.toml` 有 fastapi/sqlmodel/alembic/psycopg2-binary/httpx/boto3/pydantic-settings；**无 celery / 无 redis** |

---

## 8. 目录约定现状（ADR-0001 决定 2 的输入）

`backend/app/` 现有顶层：`api / audio_storage / collectors / common / core / domain /
engine / external_apis / models / platform / schemas / scripts / services / tools / utils`

| 约定 | 形态 | 权威 |
|---|---|---|
| 分层 | `api/` `services/` `models/` `domain/` `core/` `platform/` `schemas/` | `AGENTS.md` §2.1 |
| 垂直切片 | `platform/agents/{edu,prep,coding,research}/` | `AGENTS.md` §2.3 |

`domain/` 已装：`education_graph/` `knowledge_bundle/` `learning/` `safety/` `student_memory/`

**`backend/app/modules/` 不存在。** 引入即成为第三套约定 → 本方案不引入。

---

## 9. 缺口清单（真正要新建的）

```text
P0  活动域        activity / activity_problem / activity_scope
P0  Homework 排名  homework 计分
P0  学生页面      题库列表 / 我的提交 / 提交详情 / Activity 列表 + 详情
P0  教师 Activity 管理页
P0  列变更        ExperimentRun.run_state / run_type
P0  列变更        ExperimentDefinition.difficulty / tags
P1  OI / ICPC 排名 + freeze + 快照
P1  Analytics（overview / trend / problems / knowledge-nodes / students / activities）
P1  活动公告、知识点权重
```
