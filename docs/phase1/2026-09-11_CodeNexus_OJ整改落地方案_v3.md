# CodeNexus OJ 整改落地方案 v3

- 版本：v3（在 `CodeNexus_OJ_生产级整改方案_v2.md` 基础上，落实评审 A–H 八条修正）
- 日期：2026-09-11
- 仓库：`Ouroboros-ga/ai-course-system`，分支 `dev-liu`
- 前置文档：
  - `docs/phase1/2026-09-11_CodeNexus_OJ方案评审.md`（v1 评审 + v2 评审附录 A）
  - `docs/architecture/oj-current-state.md`（实测现状盘点，OJ-000 产出）
  - `docs/adr/ADR-0001-oj-domain-consolidation.md`（架构裁定）
  - `docs/phase1/2026-09-11_CodeNexus_OJ整改改动说明.md`（本次改动说明）

---

## 0. 路线（不变）

**不新建第二套 OJ。把现有 `experiment_*` 域正式定义成 OJ bounded context，
按 vertical slice 搬家拆分，补 Activity / Scoreboard / Analytics / 学生页面。**

沿用 v2 §0 的「不做 / 要做」清单，本版在此之上补八条修正（见 §4）。

---

## 1. 八条修正的落点

| # | 修正 | 落点 |
|---|---|---|
| A | §21 补「P0 新增/修改列」 | 本文档 §3.2 |
| B | 拆 `RunState` / `RunVerdict`，排在 Scoreboard 之前 | **PR-01**，本文档 §5 |
| C | Run 状态落地方式二选一（**选定加列**） | ADR-0001 决定 4 |
| D | ADR 补「目录约定裁定」 | ADR-0001 决定 2；落点 **`backend/app/domain/oj/`** |
| E | DoD 门禁改为 pytest characterization | 本文档 §7 |
| F | DoD 加「双路径同 policy，禁 router 级权限分支」 | 本文档 §7 |
| G | 前缀策略二选一（**选定：都不改**） | ADR-0001 决定 6 |
| H | 三条既有事实写入 | 本文档 §2.2 |

---

## 2. 复用基数（实测，2026-09-11）

### 2.1 直接复用，0 行新写

| 层 | 内容 | 行数 |
|---|---|---|
| 后端 | `services/experiment_service.py` | 2261 |
| 后端 | `models/experiment_model.py`（13 表） | 526 |
| 后端 | `api/v1/endpoints/experiments.py`（26 端点） | 1194 |
| 后端 | `api/v1/endpoints/sandbox.py` | 192 |
| 后端 | `services/sandbox_client.py` | 332 |
| 后端 | `platform/agents/contracts/sandbox.py` + `providers/sandbox/coding.py` | 295 |
| 后端 | `platform/tasks/*.py`（含 `experiment_run_queue.py` 163） | 3580 |
| 前端 | `components/codebench/` 5 组件 | 2429 |
| 前端 | `api/experiments.js` + `experimentPublishWorkflow.js` + `experimentPublishContract.js` | 248 |
| 前端 | `CourseExperimentsPage.vue` + `TeacherExperimentPanel.vue` | 2514 |
| 测试 | `tests/test_experiments.py` | 1991 |
| 测试 | `tests/test_experiment_sandbox_contract.py` + `test_p1_7_judge0_sandbox_port.py` + `test_sandbox.py` | 1177 |
| 测试 | `api/__tests__/apiContracts.test.cjs` | 1701 |
| | **合计复用基数** | **18440** |

### 2.2 三条既有事实（决定我们少干活）

1. **「Run 自定义输入」已存在** —— `sandbox_client.py:163-168` 的 `submit_code(..., stdin="")`，
   `sandbox.py:49` 请求体的 `stdin` 字段（`:170` 透传）。
   **不需要新建**，学生侧只差接进题目上下文 + `run_type` 区分。
2. **「hidden testcase 不进学生 DTO」已实现** —— `experiments.py:572` 注释原文：
   「学生视图：返回隐藏测试条目但不暴露 stdin/expected_stdout；教师视图完整暴露」
   （配套 `:198-211`）。**是回归项，不是待建项。**
3. **学生题库/自练挂点已预留** —— `ExperimentDefinition.visibility="course_catalog"` /
   `origin` / `owner_student_id` / `expires_at`（`experiment_model.py:87-90`）。
   题库页**不需要新表**，只差 `difficulty` / `tags`。

另外：**已有 1177 行判题契约测试**，已锁住
ACM 终局语义（全 AC 才满分 / 任一非 AC 归零）、免费沙箱配额 10 次窗口、
正式执行租约跨进程单持有、Judge0 Port 构造与降级（unavailable / internal_error）、
课程与学生双隔离、artifacts 读取与 stdout 截断、bootstrap 注入。
→ **characterization 缺口比 v2 估计的小得多**（见 §3.4）。

---

## 3. 预计修改的代码量

### 3.1 三分类总表

| 分类 | 后端 | 前端 | 测试 | 文档 | 合计 | 占比 |
|---|---|---|---|---|---|---|
| **复用已有**（0 行新写） | 8380 | 5191 | 4869 | — | **18440** | 57.7% |
| **搬运重构**（行为不变，行数基本不变） | 3787 | — | 620 | 250 | **4657** | 14.6% |
| **原创新增** | 3960 | 3300 | 1500 | 1200 | **9960** | 31.2% |
| **引用开源**（代码级） | 0 | 0 | 0 | 0 | **0** | 0% |
| | | | | | **33057** | 100% |

> **原创 : 复用 = 9960 : 18440 ≈ 1 : 1.85** —— 符合「尽量少写原创代码」的目标。
> 若把搬运重构也计入「不新增业务逻辑」，则非原创占比 **70.3%**。

### 3.2 原创新增拆解

#### P0（真缺口 + 治理前置）

| 模块 | 后端 | 前端 | 测试 | 文档 | 小计 |
|---|---|---|---|---|---|
| `domain/oj/activities/`（models/schemas/repository/service/policies/api） | 1140 | — | 300 | 200 | 1640 |
| `domain/oj/scoreboard/`（policy + homework + service） | 260 | — | 120 | 90 | 470 |
| `domain/oj/problems/` 净新增（api 装配 + difficulty/tags） | 320 | — | 80 | 120 | 520 |
| `domain/oj/submissions/` 净新增（学生 façade + run_type/run_state） | 380 | — | 100 | 100 | 580 |
| `domain/oj/judging/verdicts.py` + orchestrator 净增 | 300 | — | 140 | 90 | 530 |
| `domain/oj/__init__.py` + `router.py` + 装配 | 140 | — | 40 | 60 | 240 |
| Alembic 迁移 ×3 | 180 | — | — | — | 180 |
| 学生页面（题库 / 我的提交 / 提交详情 / Activity 列表+详情） | — | 1640 | — | 100 | 1740 |
| 教师 Activity 管理页 | — | 640 | — | 80 | 720 |
| 前端 api client ×4 | — | 300 | — | — | 300 |
| characterization 补缺口 | — | — | 620 | — | 620 |
| ADR + inventory | — | — | — | 700 | 700 |
| **P0 小计** | **2720** | **2580** | **1400** | **1450** | **8150** |

#### P1（补齐完整 OJ 产品壳）

| 模块 | 后端 | 前端 | 测试 | 文档 | 小计 |
|---|---|---|---|---|---|
| OI / ICPC scoreboard + freeze | 210 | — | 140 | 60 | 410 |
| Analytics（queries + schemas + api） | 670 | — | 120 | 90 | 880 |
| 教师 Analytics 页 | — | 420 | — | 40 | 460 |
| `oj_announcements` | 120 | 120 | 40 | 30 | 310 |
| `oj_scoreboard_snapshots` | 90 | — | 40 | 30 | 160 |
| `oj_problem_knowledge_weights` + 编辑 UI | 150 | 180 | 60 | 40 | 430 |
| 集成 / E2E 测试 | — | — | 400 | — | 400 |
| **P1 小计** | **1240** | **720** | **800** | **290** | **3050** |

**原创合计 = 8150 + 3050 ≈ 11200**（与 §3.1 的 9960 差异来自四舍五入与文档重叠，按 **~10000 行** 规模规划）

### 3.3 搬运重构拆解（行为不变）

| 动作 | 行数 | 要求 |
|---|---|---|
| `experiment_service.py` 2261 → 7 个 service | 2261 | 0 行为变化，characterization 全绿 |
| `experiments.py` 1194 → 4 个 `api.py` | 1194 | URL 与响应体逐字节不变 |
| `sandbox_client.py` 332 → `judging/providers/judge0.py` | 332 | 唯一出口，Port 契约不变 |
| 合计 | **3787** | 配 620 行 characterization |

### 3.4 引用开源代码：0 行（含理由）

**结论：代码级引用为 0，只做设计参考。**

| 项目 | 许可 | 我们的用法 | 代码迁移 |
|---|---|---|---|
| QDUOJ | MIT | 参考 Problem admin UX / 题库列表 / 提交列表 / rank 表现 | **0**（其 Django ORM 与 SQLModel 不兼容，移植需重写，成本 > 自写） |
| DOMjudge | GPL-2.0-or-later | 参考 ICPC scoreboard / freeze / penalty / rejudge 语义 | **0** |
| DMOJ | AGPL-3.0 | 参考 test group / partial score / special judge 设计 | **0**（AGPL 不引入） |
| Hydro | AGPL 为主 | 参考产品 UX / problem package | **0**（AGPL 不引入） |
| SDUOJ | AGPL-3.0 | 参考服务拆分思路 | **0**（AGPL 不引入） |

**预留口子**：若后续确需移植 MIT 来源片段（如 QDUOJ 的 rank 算法），
单列并在文件头保留 copyright notice，**上限 ≤ 200 行**，且必须在本表登记。

---

## 4. PR 序列（已按修正重排）

| PR | 内容 | 是否改 schema | 预计新增 | 依赖 |
|---|---|---|---|---|
| **PR-00** | 现状盘点 + ADR（**0 行代码**） | 否 | 文档 700 | — |
| **PR-01** | **Run 状态 / 判定分离**（`RunState` / `RunVerdict` + `run_state` 列 + 迁移 + 测试）**（已实施）** | **是（+1 列）** | 430 + 测试 180 | PR-00 |
| **PR-02** | `domain/oj/` 骨架 + Judge0 出口收拢（**已实施**；**未留 shim**，理由见改动说明 §6.2） | 否 | 260 | PR-00 |
| **PR-03** | 拆 `experiment_service` → problems services | 否 | 120 | PR-02 |
| **PR-04** | 拆 `experiment_service` → attempt / run services | 否 | 150 | PR-03 |
| **PR-05** | 判定词汇归位判题域（映射表搬出业务服务）**（已实施）** | 否 | 60 | PR-02 |
| **PR-06a** | `intelligence/`：diagnosis + explanation 归位（**已实施**，不碰 `experiment_service`） | 否 | 90 | PR-02 |
| **PR-06b** | `intelligence/`：`CodingHintService` 归位（**须等 PR-04**，在 `experiment_service.py` 内） | 否 | 170 | PR-04 |
| **PR-07** | Activity 域（DB + models + service + policies） | 是（+3 表） | 1140 | PR-05 |
| **PR-08** | Activity admin APIs | 否 | （含 PR-07） | PR-07 |
| **PR-09** | `difficulty` / `tags` + 迁移（**PR-10 的前置**）**（已实施**，取值口径与回填策略见改动说明 §9**）** | 是（+2 列） | 180 | PR-02 |
| **PR-10** | 学生题库 / 我的提交 / 提交详情 façade | 否 | 1060 | PR-09 |
| **PR-11** | HomeworkScoreboard | 否 | 260 | PR-07 |
| **PR-12** | 学生 Activity 页 + 教师 Activity 管理页 | 否 | 960 | PR-08 |
| **PR-13** | Run 状态 SSE（复用现有 task_events 轮询） | 否 | 180 | PR-01 |
| **PR-14** | Analytics | 否 | 670 | PR-11 |
| **PR-15** | OI / ICPC scoreboard + freeze | 是（+1 表） | 300 | PR-11 |
| **PR-16** | LearningEvent 集成 | 否 | 200 | PR-14 |
| **PR-17** | 删除死壳 `codebench.py` + 旧路由 | 否 | **-30** | PR-10 |

**第一阶段（可交付闭环）= PR-00 → PR-01 → PR-02 → PR-03 → PR-04 → PR-05 → PR-06**
= 治理前置 + Run 语义分离 + 骨架 + 拆分 + Judge0 收拢 + intelligence 归位
（约 **1900 行代码 + 700 行文档**，无新业务、行为不变）

> **实施进度（2026-09-11）**：PR-00 / 01 / 02 / 05 / **06a** 已完成并提交
> （`498216cb`、`4d5e1c23`）。
> **PR-03 / 04 受阻**：`experiment_service.py` 内有他线（学生工作台）212 行在途代码，
> 拆分会与之冲突。因此 PR-06 按落点拆为两半，先做不依赖 PR-04 的 **06a**，
> `CodingHintService` 归位（**06b**）等 PR-04。
> **PR-09 已实施**（前置只有 PR-02，不被他线阻塞）：两列 + 迁移 `oj20260911v2` +
> 域模块 `domain/oj/problems/` + 62 例测试。**服务层只做最小追加**，
> 提交时以「HEAD + 我的 5 处改动」重建 blob 精确入库，他线 `starter_code` 行留在工作树。
> 顺带修掉一个**继承的失败测试**：`test_migration_ledger_idempotent_on_repeated_upgrade`
> 写死账本条数 `== 10`，PR-01 就已击穿（实测 11），已改为断言幂等不变量（见改动说明 §9）。

**第二阶段（业务闭环）= PR-07 → PR-08 → PR-09 → PR-10 → PR-11 → PR-12**
= Activity 域 + 学生页面 + Homework scoreboard（约 **4200 行**）

**第三阶段（完整壳）= PR-13 → PR-17**（约 **2800 行**）

---

## 5. PR-01 的硬要求（本方案最关键的修正）

### 5.1 问题

`backend/app/models/experiment_model.py:242-252`：

```python
class RunOutcome(str, Enum):
    PENDING = "pending"                      # ← 状态
    ACCEPTED = "accepted"                    # ← 判定
    WRONG_ANSWER = "wrong_answer"
    ...
```

**状态与判定混在一个枚举。** 做 Activity/Scoreboard 时立刻卡住：
ICPC 要按 verdict 判罚时、Homework 要按 score 求和，
两者都需要「这次 run 还在跑」≠「判成了某个结果」。

### 5.2 目标形态

```python
class RunState(str, Enum):     # 新增列 run_state
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    SYSTEM_ERROR = "system_error"

class RunVerdict(str, Enum):   # 由 RunOutcome 去掉 PENDING 后原样保留 9 值
    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    RUNTIME_ERROR = "runtime_error"
    COMPILATION_ERROR = "compilation_error"
    INTERNAL_ERROR = "internal_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
```

### 5.3 兼容策略（不回填、不破坏既有语义）

- `RunOutcome` **保留为聚合结果枚举**，成员一个不改（含 `PENDING`），
  已有读取方继续工作。
- 新增 `run_state` 列，默认 `queued`，**对既有行按 `outcome` 回填**：
  `outcome == pending → queued`，其余 → `finished`。
- 新增 `run_type` 列，默认 `submission`；`TEST` / `REFERENCE_PREVIEW` 由后续 PR 写入。
- 提供 `RunOutcome.to_state()` / `to_verdict()` 映射，**算分链路只读 `RunVerdict`**。

### 5.4 为什么必须在 Scoreboard 之前

若先做 Scoreboard 再拆枚举，`oj_activity_problems.max_score` 的算分链路
要跟着改两遍。**顺序不可调。**

---

## 6. 目录落点（ADR-0001 决定 2）

```text
backend/app/domain/oj/          ← 选定。与 domain/ 既有五个领域模块并列
├── __init__.py
├── router.py
├── problems/
├── submissions/
├── judging/
│   ├── ports.py
│   ├── verdicts.py             ← RunState / RunVerdict
│   ├── orchestrator.py
│   └── providers/judge0.py     ← sandbox_client.py 搬家
├── intelligence/
├── activities/
├── scoreboard/
└── analytics/
```

**不新增 `backend/app/modules/`**（实测不存在；引入即成为第三套目录约定）。
现有两套：分层（`AGENTS.md` §2.1）+ 垂直 `platform/agents/<agent>/`（§2.3）；
`domain/` 已装 `education_graph` / `knowledge_bundle` / `learning` / `safety` / `student_memory`。

---

## 7. Definition of Done（已按修正 E / F 改写）

### 重构 DoD

- [ ] **pytest characterization tests 全绿，且新增用例数 ≥ 被拆 public 方法数。**
      （`apiContracts.test.cjs` 是**读源码 + 正则**，拆 service 时不会红，
      **只作附加检查，不作行为回归门禁**）
- [ ] 原功能 URL 行为与响应体逐字节不变。
- [ ] `experiment_service.py` 明显缩小。
- [ ] Judge0 HTTP 只有一个出口。
- [ ] OJ 模块不能绕过 `SandboxPort`。
- [ ] **同一资源的两个路径必须调用同一个 policy / service 函数；
      不允许任何 router 级权限分支或角色分支。**
      （现存反例：`experiments.py:319-327` 的 `list_definitions` 里
      `if context.role.value == "student"` —— 视图差异必须下沉到 serializer/service）
- [ ] 没有双写 problem / submission。
- [ ] diagnosis / hint / explanation 无功能回归。

### Activity DoD

- [ ] 同一 Activity 固定 `problem_version_id`。
- [ ] 所有学生拿到相同版本。
- [ ] 自由练习仍可使用最新发布版本。
- [ ] teacher scope 正确。
- [ ] activity 时间约束生效。
- [ ] score 可重算且 deterministic。

### 安全 DoD

- [ ] 学生拿不到 hidden testcase —— **回归测试保持绿**（已实现，见 §2.2）。
- [ ] 学生拿不到 Judge0 token / credentials。
- [ ] 客户端不能提高 resource limit。
- [ ] network policy 继续 fail-closed。
- [ ] quota / lease 继续复用现有机制。

### 运维 DoD

- [ ] task backlog 可查询。
- [ ] `run_id` 可串联日志。
- [ ] Judge0 不可用时任务可恢复。
- [ ] idempotency 仍有效。
- [ ] re-run / cancel 不制造重复最终状态。

---

## 8. 每阶段禁止事项（沿用 v2 §37，补两条）

**PR-00 ~ PR-06 禁止**：

```text
新建 oj_problem / oj_problem_version / oj_testcase / oj_submission / oj_judge_job
替换 CodeMirror
引入 Celery / Redis Queue
修改 Judge0 部署
新增 backend/app/modules/ 目录
改动任何已有 URL 的响应体结构
```

**PR-07 之后允许新增**：Activity / Scoreboard / Analytics，但仍禁止复制已有 Experiment 功能。

**全程禁止**：

```text
复制 AGPL 来源代码（DMOJ / Hydro / SDUOJ）
用 apiContracts.test.cjs 的绿证替代行为回归
在 router 层新增权限或角色分支
```

---

## 9. 命名债（已接受的取舍，ADR-0001 决定 6）

物理表名与新表前缀**都不改**：

```text
Python Domain:   Problem / ProblemVersion / Submission
Physical DB:     experiment_definitions / experiment_versions / experiment_runs
New tables:      experiment_activities / experiment_activity_problems / ...
API Path:        /api/v1/experiments/*（不引入 /oj canonical 前缀）
```

理由：`/experiments` 与 `experiment_*` 是前端 49 个 API client、108 条契约测试、
75 个迁移的既有资产；改名风险 ≥ 收益。**「experiment 是历史命名」记为已接受的债，
不假装它中性**——待 OJ 域稳定后如需 rename，单独开一期。

> 注意：本决定与 v2 §21 的 `oj_activities` 命名**相反**。
> v2 一边论证「前缀不重要」（不改旧表）一边引入新前缀，
> 结果是 `oj_activity_problems.problem_definition_id → experiment_definitions.id`
> 这种混合命名，前缀反而成为「新旧分界」的永久标记。本版统一为不改。
