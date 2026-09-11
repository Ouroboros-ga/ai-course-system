# ADR-0001：OJ 域整合（不新建第二套 OJ）

- 状态：**Accepted**
- 日期：2026-09-11
- 决策人：家良（采纳砚的评审建议）
- 相关：`docs/architecture/oj-current-state.md`、`docs/phase1/2026-09-11_CodeNexus_OJ整改落地方案_v3.md`
- 背景来源：外部方案 v1（`CodeNexus_OJ_生产级重构与实现方案.md`）→ 评审 → v2 → 评审 → v3

---

## 背景

外部方案 v1 依据 `backend/app/api/v1/endpoints/codebench.py` 只有一行注释，
判断「旧 OJ 业务没有写到不可拔出的程度，现在正是切干净边界的最佳时机」，
并规划新建 `oj_problem` / `oj_problem_version` / `oj_submission` / `oj_judge_job` 等表
与第二套 `JudgeProvider` + Judge0 Adapter，引入 Celery + Redis 队列，并将前端
CodeMirror 换成 Monaco。

实测（见 `docs/architecture/oj-current-state.md`）证明该前提错误：

- `codebench.py` 是 1 行死壳，**不是 OJ 入口**
- 活体 OJ 域 ≈ **4800 行后端**（`experiments.py` 1194 / `experiment_service.py` 2261 /
  `experiment_model.py` 526 / `sandbox.py` 192 等），已有 13 张表
- v1 规划的表/组件已全部存在：`experiment_*` 表、`sandbox_client.py`、
  `platform/tasks/` DB 持久化队列、CodeMirror 6 编辑器、
  以及已上线的 diagnosis / hint / explanation 能力

按 v1 原样执行将产生第二套事实源，命中 v1 自己 §41 的第 5 条坑
（「同时维护新旧 submission 表」）。

---

## 决定

### 决定 1：`experiment_*` 域正式定义为 OJ bounded context

现有 `experiment_definitions` / `experiment_versions` / `experiment_test_cases` /
`experiment_attempts` / `experiment_runs` **就是** OJ 的 Problem / ProblemVersion /
TestCase / Attempt / Submission。**不新建等价表。**

### 决定 2：目录落点为 `backend/app/domain/oj/`

不新增 `backend/app/modules/`。

**理由**：仓库已有两套约定——分层（`AGENTS.md` §2.1）与垂直切片
（`platform/agents/<agent>/`，`AGENTS.md` §2.3）。`backend/app/modules/` 实测不存在，
引入即成为第三套约定，且未获 `AGENTS.md` 承认。而 `domain/` 已装
`education_graph` / `knowledge_bundle` / `learning` / `safety` / `student_memory`
五个领域模块，OJ 域逻辑与之并列最自然。

**放弃的选项**：`backend/app/platform/oj/`（与既有 vertical slice 先例一致，
但 `platform/` 语义偏基础设施与 Agent 平台，OJ 是纯业务域）。

### 决定 3：不新写 Judge0 Adapter，收拢现有出口

`services/sandbox_client.py`（332 行）搬入 `domain/oj/judging/providers/judge0.py`，
成为**唯一 Judge0 HTTP 出口**。业务层只认识 `RunVerdict` / `JudgeResult`，
不认识 Judge0 status id / token / payload shape。

### 决定 4：Run 状态落地方式 = **新增 `run_state` 列**

`ExperimentRun` 现无状态列（只有 `outcome` / `submitted_at` / `finished_at` /
`cancel_requested_at`），运行态挂在 `task_id` → `TaskRecord`。

**放弃「Run 状态 = task 状态投影」方案**。理由：`TaskRecord` 是基础设施层概念，
把它当业务状态会让 OJ 域无法脱离 task framework 独立演进，
并拖慢「我的提交」这类只读查询。

### 决定 5：`RunOutcome` 拆为 `RunState` + `RunVerdict`，且**必须在 Scoreboard 之前**

`RunOutcome` 把 `PENDING`（状态）与 `ACCEPTED` / `WRONG_ANSWER`（判定）混在一个枚举，
是状态机与判定语义的耦合。Activity / Scoreboard 一上来就会卡住
（ICPC 按 verdict 算罚时、Homework 按 score 求和，且都需要「还在跑」≠「判成某个结果」）。

**兼容策略**：`RunOutcome` 成员一个不改，保留为聚合结果枚举；
新增 `RunState` / `RunVerdict` 与映射函数；算分链路只读 `RunVerdict`。

### 决定 6：表名与 API 前缀**都不改**（命名为已接受的债）

```text
Physical DB:  experiment_*  （不 rename）
New tables:   experiment_activities / experiment_activity_problems / ...  （沿用既有前缀）
API Path:     /api/v1/experiments/*  （不引入 /oj canonical 前缀）
```

**理由**：`/experiments` 与 `experiment_*` 是前端 49 个 API client、108 条契约测试、
75 个迁移的既有资产；改名风险 ≥ 收益。

**关键**：v2 一边论证「前缀不重要」（故不改旧表）、一边引入 `oj_*` 新前缀，
产生 `oj_activity_problems.problem_definition_id → experiment_definitions.id`
这类混合命名，**前缀反而成为「新旧分界」的永久标记**。本决定统一为不改。

「experiment 是历史命名」**记为已接受的债**，不假装它中性。若 OJ 域稳定后
确需 rename，单独开一期。

### 决定 7：继续使用 `platform/tasks/` DB 持久化队列

**不引入 Celery / Redis**。现有队列已满足 durable / retry / event / idempotency / concurrency
（`tasks` / `task_events` / `task_resource_links` / `idempotency_keys` 四表 + 并发配额服务）。

Redis 仅在**同时满足**以下三条时才引入，且只承担 Pub/Sub，不替换队列：

```text
API 多进程
+ Worker 独立进程
+ 需要低延迟跨进程 SSE push
```

### 决定 8：继续使用 CodeMirror 6

`frontend/src/components/codebench/` 5 组件已支持 python / cpp / java / javascript
与 fold / autocomplete / search / keymap。**不换 Monaco。**

### 决定 9：`diagnosis` / `hint` / `explanation` 是核心 OJ 子域，不是 P2

归入 `domain/oj/intelligence/`。保留 `coding_hint_records` 的
`hint_level` / `reason_codes` / `policy_version` 审计字段。
后续建议补 `model_id` / `prompt_version` / `evidence_ids` / `review_status` / `reviewer_id`。

### 决定 10：行为回归门禁 = pytest characterization，不是源码正则

`frontend/src/api/__tests__/apiContracts.test.cjs`（1701 行）是**读源码 + 正则断言**，
拆 `experiment_service.py` 时不会红。它只作附加检查。

**门禁**：pytest characterization tests 全绿，且新增用例数 ≥ 被拆 public 方法数。

### 决定 11：禁止 router 级权限/角色分支

同一资源的两个路径（若存在）必须调用同一个 policy / service 函数。

**现存反例**：`experiments.py:319-327` 的 `list_definitions` 里
`if context.role.value == "student"` 计算 `student_summaries`。
视图差异必须下沉到 serializer / service 层。

### 决定 12：代码级不引用 AGPL 来源

| 项目 | 许可 | 用法 |
|---|---|---|
| QDUOJ | MIT | 设计参考（Problem admin UX / 题库列表 / 提交列表 / rank）—— **不迁代码** |
| DOMjudge | GPL-2.0-or-later | 设计参考（ICPC scoreboard / freeze / penalty / rejudge） |
| DMOJ / Hydro / SDUOJ | AGPL | **不参考代码**（避免许可传染） |

若后续确需移植 MIT 源码片段，须单列登记并在文件头保留 copyright notice，上限 ≤ 200 行。

---

## 后果

**正面**

- 不产生第二套事实源，无 Dual Write
- 复用 18440 行既有代码，原创仅约 10000 行（原创 : 复用 ≈ 1 : 1.85）
- 保住已经上线的差异化能力（诊断 / 提示 / 讲解 / 教师复核 / 学习证据）
- 不引入新队列、新编辑器、新沙箱，运维面不变

**负面 / 已接受的取舍**

- 命名债：域叫「OJ」而表叫 `experiment_*`、路径叫 `/experiments`
- `experiment_service.py` 2261 行的拆分需要先补 characterization 测试，前期投入不少
- 不引入 `/oj` 前缀意味着新页面也要挂在 `/experiments` 语义下，命名略别扭

---

## 未决项（后续单独裁定）

1. `ExperimentDefinition.difficulty` / `tags` 走新增列还是独立 `experiment_tags` + 关联表
   （倾向新增列：题目身份级属性）
2. `experiment_service.py` 拆成几个 service 的最终边界
3. `Run 状态 SSE` 是否直接复用 Nexus 的 SSE transport 约定
