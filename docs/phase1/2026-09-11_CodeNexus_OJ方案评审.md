# CodeNexus OJ 方案评审（v1 + v2）

- 评审对象：
  - `CodeNexus_OJ_生产级重构与实现方案.md`（v1）
  - `CodeNexus_OJ_生产级整改方案_v2.md`（v2）
- 评审方式：逐条对照 `dev-liu` 仓库实测（文件路径 + 行号），非推测
- 评审时间：2026-09-11
- **v1 评审见下方 §1–§6；v2 评审见文末「附录 A」**

---

## 0. 结论

| 维度 | 判断 |
|---|---|
| **怎么建**（架构原则、边界划分、反屎山规则、验收标准） | **质量高，可直接采用** |
| **从哪开始**（现状盘点、Stage 划分） | **前提错误，按原样执行会造出第二套 OJ 域** |

一句话：

> 这份方案的规则清单和边界主张值得原样保留；但它的现状盘点是错的，
> 会把仓库里已经存在的 ~4000 行 OJ 域变成需要长期共存的第二套事实源，
> 从而踩中它自己 §41 列出的第 5 条坑（「同时维护新旧 submission 表」）。

**处理建议**：保留 §0.2 / §1.2 / §3.3 / §40 / §41 / §42 / §43 / §44；
重写 §0.3 与 Stage A–E；把「新建 `oj_*` 表」改为「搬家 + 重命名 `experiment_*`」；
把 Activity / Scoreboard 提为真正的 P0。

另外，文档标题用「整改」，但正文结构是从零建 OJ 的 greenfield 方案，
两者框架不匹配——这也解释了为什么它会把已经建好的东西当成待建项。

---

## 1. P0：会导致直接返工的前提错误

### P0-1 方案看错了文件，把「空壳」误判为「旧 OJ 的规模」

**方案原文（§0.3）**：

> 反而当前 `backend/app/api/v1/endpoints/codebench.py` 实际上还是
> `# 代码实验台相关接口端点`。也就是说**现在正好是切干净 OJ 边界的最佳时间**：
> 旧 OJ 业务并没有已经写到不可拔出的程度。

**实测**：

- `codebench.py` 全文 1 行：`# 代码实验台相关接口端点` —— 这个文件方案没看错
- **但真正的 OJ 业务不在这个文件里**：

| 文件 | 行数 | 内容 |
|---|---|---|
| `backend/app/api/v1/endpoints/experiments.py` | **1194** | 26 个已注册端点 |
| `backend/app/services/experiment_service.py` | **2261** | 版本/发布/尝试/运行/判题编排 |
| `backend/app/models/experiment_model.py` | **526** | 13 张表 |
| `backend/app/api/v1/endpoints/sandbox.py` | 192 | 语言白名单 / 执行 / 健康检查 |

合计约 **4000 行在跑的活代码**，且是当前前端
`/app/course/:id/experiments` 的真实数据源。

**根因**：方案把「文件名带 code / bench」当成了 OJ 入口，
没有按路由注册表或表结构反查真实业务边界。
仓库里 `codebench.py` 是**遗留死壳**，`experiments.py` 才是活体。

### P0-2 方案要建的 `oj_*` 表，每一张几乎都已经存在

| 方案拟建 | 仓库现状 | 证据 |
|---|---|---|
| `oj_problem` | `experiment_definitions` | `experiment_model.py:54` |
| `oj_problem_version` | `experiment_versions`（`version_number` / `is_locked` / `passing_score=1.0` / `starter_code`） | `:106-148` |
| `oj_testcase` | `experiment_test_cases` | `:165` |
| `oj_submission` | `experiment_runs`（含 `idempotency_key`：「学生正式提交的请求幂等键」） | `:255-286` |
| `oj_submission` 的版本固化 | `experiment_attempts.version_id`：「尝试开始时激活的版本，**固化不可漂移**」 | `:213` |
| `oj_judge_job` | `tasks` / `task_events` / `idempotency_keys` | `task_model.py:60,97,146` |

对应的**行为**也已经有了：

| 方案拟建行为 | 仓库现有端点 | 位置 |
|---|---|---|
| 题目发布 / 下架 | `POST .../definitions/{id}/publish`、`.../archive` | `experiments.py:437,464` |
| 版本冻结 | `POST /versions/{id}/lock` | `experiments.py:643` |
| **标准代码校验** | `POST /versions/{id}/reference-preview`（「临时参考解在当前测试集全 AC 的服务端验证时间；源码不持久化」） | `experiments.py:872`、`experiment_model.py:152` |
| 异步 Submit（不阻塞 HTTP） | `POST /attempts/{id}/runs`，`status_code=202` | `experiments.py:738` |
| 提交撤消 | `POST /runs/{id}/cancel` | `experiments.py:950` |

方案 §7.2 把「教师上传标准代码 → 自动确认全部 AC」称为
「极其建议增加」的 `POST /admin/problems/{id}/validate`——
**这个能力已经在跑**（`reference-preview`）。

**后果**：按方案执行 = 新增一套 `oj_*` 表与 `experiment_*` 长期并存。
这正是方案 §41 第 5 条「同时维护新旧 submission 表」，
以及 §26 自己明令禁止的 Dual Write 前身。

### P0-3 JudgeProvider / Judge0Adapter / verdict 枚举 / fail-closed 全部已存在

| 方案拟建 | 仓库现状 |
|---|---|
| `JudgeProvider(Protocol)` | `backend/app/platform/agents/contracts/sandbox.py`：`SandboxPort` 已定义 |
| `Judge0Adapter` | `backend/app/services/sandbox_client.py`（**332 行**）：`SandboxClient.submit_code()` / `health_check()` |
| verdict 枚举 | 同文件 `SubmissionStatus`；`experiment_model.py:242` `RunOutcome`（`ACCEPTED` / `TIME_LIMIT_EXCEEDED` / `MEMORY_LIMIT_EXCEEDED` …） |
| 资源限制对象化 | 同文件 `SandboxResourceLimits` |
| 结果判定 | 同文件 `SandboxResult.is_accepted / is_error / is_timeout / is_memory_exceeded` |
| fail-closed | 同文件 `SandboxUnavailableError` |
| Provider 实现目录 | `backend/app/platform/agents/providers/sandbox/coding.py` |
| 语言白名单接口 | `GET /api/v1/sandbox/languages`（`sandbox.py:182`） |

方案 §8.1 要写的 `judging/providers/judge0.py` 是**第二套**。

**但方案并非全错**：§8.1 与 §40 Rule 2 指出的问题是**真实的**——
`experiment_service.py:1028` 直接消费 `result.compile_output`，
Judge0 细节与业务编排同处一个 2261 行文件里。
**正确动作是「把已有出口收拢归一」，不是「再写一个 adapter」。**

### P0-4 任务队列已存在，且是 DB 持久化，不是 BackgroundTasks

`backend/app/platform/tasks/` 下的现状：

```text
worker.py                  LocalTaskWorker（_ConcurrencyController 并发控制）
runner.py / status.py / result.py
handlers.py                各业务域 handler 注册
experiment_run_queue.py    ← 判题队列
course_draft_build_queue.py
document_parse_queue.py
knowledge_build_queue.py
media_manifest_queue.py
```

持久化表：`tasks` / `task_events` / `task_resource_links` / `idempotency_keys`
（`task_model.py:60,97,122,146`），并发配额在
`platform_task_concurrency_service.py` + `platform_task_concurrency_configs`。

方案 §12 的论断「不要用 FastAPI BackgroundTasks 判题，必须 Durable Queue」
**方向完全正确，但仓库已经做到了**。再引入 Celery + Redis 就是第二套队列系统。

### P0-5 编辑器已存在，方案推荐的替换属纯 churn

`frontend/src/components/codebench/` 已有完整一套：

```text
CodeEditor.vue      CodeMirror 6（python / cpp / java / javascript 全支持，
                    含 keymap / fold / autocomplete / 括号匹配 / 搜索）
CodeOutput.vue
CodeTestCases.vue
CodeToolbar.vue
CodeWorkbench.vue
```

方案 §14「不要重新造编辑器 → Monaco Editor」把它当新事物。
实际效果是：**把一个已经在跑的 CodeMirror 6 换成 Monaco**，
体积从模块化 CodeMirror 涨到 5MB+ 量级，功能零增益。

### P0-6 把项目唯一的差异化能力降级到 P2

方案 §32 P2 清单包含：

> Special Judge / Interactive / Generator / … / **AI 错误诊断** / AST tracing / variable trace

**实测：这些已经上线**：

| 能力 | 端点 | 位置 |
|---|---|---|
| 运行后诊断 | `POST /runs/{id}/diagnosis`、`GET /runs/{id}/diagnosis` | `experiments.py:1077,1171` |
| 运行后讲解 | `POST /runs/{id}/explanation` | `experiments.py:1108` |
| 教学提示 | `POST /attempts/{id}/agent-hints`、`GET /attempts/{id}/agent-hints` | `experiments.py:987,1017` |
| 教师复核提示 | `POST /agent-hints/{id}/review` | `experiments.py:1044` |
| 提示审计 | `CodingHintRecord`（`hint_level` / `reason_codes` / `policy_version`） | `experiment_model.py:491-512` |

CodeNexus 相对 QDUOJ / DMOJ 的护城河就是
「判分 + 为什么错 + 给提示 + 教师复核 + 落进学习证据」。
方案把它放进 P2「以后再做」，同时把**重新实现 QDUOJ 已有的题库 CRUD** 提为 P0——
**优先级整体倒挂。**

---

## 2. P1：方向对，但需要重新裁定落点

### P1-1 vertical slice 判据正确，落点应是「抽出」而非「新建」

方案 §3.2 的判据（「一个新人看 `submissions` 目录就能看全一条链」）
完全成立，而 `experiment_service.py` 2261 行正是这个判据下的重灾区。

**但正确动作是**：把现有 experiment 域按 vertical slice 拆出，
用 **Alembic 表重命名**迁到 `modules/oj/`，而不是另建一套并存。

```text
modules/oj/
├── problems/        ← 由 experiment_definitions + experiment_versions 迁入
├── submissions/     ← 由 experiment_attempts + experiment_runs 迁入
├── judging/         ← 收拢 services/sandbox_client.py 作为唯一出口
├── activities/      ← 真正新增（见 P1-2）
└── analytics/       ← 真正新增
```

表名可保留 `experiment_*`（避免大爆炸迁移），或一次性 rename 到 `oj_*`。
**关键是同一时刻只有一个事实源。**

### P1-2 Activity / Contest / Scoreboard 是真缺口，方案这块最有价值

实测：

```bash
grep -rlniE "homework|contest|scoreboard" backend/app --include=*.py
# → 仅命中 domain/safety/ 下 4 个文件（无关词匹配），无任何作业/比赛实体
```

方案 §5.12（统一 `oj_activity` + `type` + `scoring_mode`）、
§5.13 `oj_activity_problem`（发布时冻结 `problem_version_id`）、
§5.14 `oj_activity_scope`（班级/课程/个人）、
§9.9 scoreboard 三模式（Homework / OI / ICPC）
**是这份方案里最该照做的部分**，建议整段保留。

### P1-3 Redis 是真实新增基础设施，但方案没说清它解决哪个已存在的瓶颈

方案 §37：只加 `celery[redis]` + `redis`。

现状：`deploy/judge0/docker-compose.yml:146` 里的 redis 只服务 Judge0 自身队列；
仓库 DB 队列不需要 Redis。

**Redis 唯一正当用途**是方案 §7.7 的 SSE 跨进程广播
（API 与 worker 不同进程时）。若同进程，DB 轮询足够。
**先回答「Redis 解决哪个已存在的瓶颈」，再决定是否引入。**

### P1-4 知识点关联方向对，但要接现有绑定方式

方案说「不要新建另一套知识点系统」——正确。
但仓库现状是 `ExperimentDefinition.knowledge_node_ids`（纯 ID 列表），
方案给的是 `oj_problem_knowledge_point` + `weight`。

**两者用途不同**：前者是绑定，后者是掌握度权重。
需要明确「weight 由谁维护、和 `knowledge_node_ids` 什么关系」，
否则又是一处口径分裂。

### P1-5 SSE 而非 WebSocket，判断正确且可复用现有通道

Nexus 前端已在用 SSE（`frontend/src/api/nexus.js`）。
直接复用通道约定，不要新造一套。

### P1-6 ProblemVersion 冻结语义对，但要确认是 activity 级还是 attempt 级

方案 §5.2 主张 `ActivityProblem.problem_version_id` 冻结（activity 级）。
仓库现状是 **attempt 级固化**：`experiment_attempts.version_id`
「尝试开始时激活的版本，固化不可漂移」。

两种都成立，但方案不知道已经做了一层。
**先确认沿用哪种，不要叠两层冻结。**

---

## 3. P2：表述与细节

| 项 | 说明 |
|---|---|
| §36 「freeze Judge0 deployment」 | 好建议。已核实 `deploy/judge0/docker-compose.yml:33` 为 `judge0/judge0:1.13.1`，方案版本号准确 |
| §22 License 表 | 分项核对：QDUOJ=MIT ✅、Judge0=GPL-3.0（独立服务调用不传染，结论正确）✅、DMOJ/AGPL ✅、SDUOJ/AGPL ✅。**该表可用** |
| §17.4 rate limit | 仓库已有 `FreeSandboxQuotaWindow`（配额窗口）+ `SandboxExecutionLease`（执行租约），应复用而非新写限流器 |
| §33.1 单测清单 | 把 `ICPC ranking` / `OI scoring` 列入测试项，但这两项功能本身在 §31 才做 → 会产生无法通过的测试 |
| §24 依赖地图 / §24.1 表状态标签 | 方法正确，**且方案自己要求了这步却跳过了**——这是 P0-1 的直接原因 |
| 全篇未提及 | `AGENTS.md`、`design.md`、契约测试 `frontend/src/api/__tests__/apiContracts.test.cjs`（108 条）、仓库「冻结设计不改」约束。属外部视角方案，未与仓库治理文档对齐 |

---

## 4. 值得原样保留的部分（不要重写）

1. **§0.2 开源拼装基座原则** —— 不原创队列 / 沙箱 / 存储 / 编辑器 / 图表 / ORM / Markdown 引擎 / 鉴权。方向完全正确。
2. **§1.2 浏览器绝不能直连 Judge0 + 那 8 条理由** —— 逐条成立，是 OJ 的安全底线。
3. **§3.3 跨模块只能走 Port + §25 防腐层** —— 正确；仓库已有 `platform/agents/contracts/` 可承载。
4. **§40 十条代码质量规则** —— 全部可用。尤其 Rule 2（API 不直接调 Judge0）、Rule 5（Submission 永远绑定 ProblemVersion）、Rule 6（隐藏 testcase 永不进学生 DTO）。建议直接进 `AGENTS.md` / 模块 `DESIGN.md`。
5. **§41 「最容易重新变屎山的 10 个坑」** —— 这份方案最有价值的产出。**注意：它自己的执行路径会踩第 5 条。**
6. **§42 Stage 顺序**（先打通最小 Judge 纵切 → 再 CRUD → 再 Activity → 最后清 Legacy）—— 顺序正确。
7. **§43 PR 拆分粒度** —— 好，14 个 PR 每个可 review。
8. **§44 Definition of Done 四类验收**（数据一致性 / 安全 / 产品 / 运维）—— 好，可直接用。

---

## 5. 修正后的执行建议

| Stage | 方案原动作 | 修正后动作 |
|---|---|---|
| **0（新增）** | （无） | 写依赖地图，把 `experiment_*` 13 张表登记为 KEEP / WRAP / MIGRATE。方案 §24 自己要求了这步 |
| **A** | 新建 `modules/oj/`，新建 `oj_*` 表 | **不新建表**。用 Alembic 把 `experiment_*` 迁入 `modules/oj/`，表名可保留 |
| **B** | 写 `JudgeProvider` + `Judge0Adapter` | **不新写**。把 `services/sandbox_client.py` 收拢进 `modules/oj/judging/providers/judge0.py` 作为唯一出口，消除 Rule 2 违规 |
| **C** | 引入 Monaco | **沿用 CodeMirror 6**。只补学生题库列表页 / 提交记录页（现缺） |
| **D** | 教师题目 CRUD | **Activity / Contest / Scoreboard**（真缺口，方案 §5.12–§5.14、§9.9 照做） |
| **E** | Celery + Redis | **复用现有 DB 队列**。只在 SSE 跨进程成为真瓶颈时再引入 Redis |

---

## 6. 一句话交付

**保留它的「架构原则 + 规则清单 + 验收标准」，重写它的「现状盘点 + Stage 划分」。
把「新建 `oj_*`」改成「搬家并重命名 `experiment_*`」，
把 Activity / Scoreboard 提为真正的 P0，
把已经上线的诊断 / 提示 / 讲解从 P2 提到核心叙事。**

---
---

# 附录 A：v2 评审（2026-09-11）

## A.0 总判

**v2 是 v1 的正确修订版，采纳了 v1 全部 P0 结论**（现状事实、不建第二套 `oj_*`、
不新写 Judge0 adapter、不引 Celery/Redis、不换 Monaco、不把 intelligence 降级）。

技术主张层面 v2 质量明显高于 v1。但仍有 **4 条会导致返工或埋雷的新问题**、
**2 条用错门禁**、**1 条内部自相矛盾**，以及 **3 条它漏掉的既有事实**（其中两条能让它少干活）。

一句话：

> **v2 的路线对了，但「先做什么」的排序还有一处致命错位（Run 枚举与状态），
> 而且它在「表名不改」和「URL 要改」上用了两把尺子。**

---

## A.1 P0：仍会返工或埋雷

### A.1.1 v2 让「沿用现有 `RunOutcome`」——但 `RunOutcome` 正是 v1 明令禁止的单枚举反模式

**v2 原文（§19）**：

> `Verdict：ACCEPTED / WRONG_ANSWER / …`
> 沿用现有 `RunOutcome`，不要再发明第二套枚举。

**实测**（`backend/app/models/experiment_model.py:242-252`）：

```python
class RunOutcome(str, Enum):
    PENDING = "pending"                      # ← 这是「状态」
    ACCEPTED = "accepted"                    # ← 这是「判定」
    WRONG_ANSWER = "wrong_answer"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    RUNTIME_ERROR = "runtime_error"
    COMPILATION_ERROR = "compilation_error"
    INTERNAL_ERROR = "internal_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
```

`PENDING`（运行中）与 `ACCEPTED`（判定结果）在同一个枚举里。
**这正是 v1 §5.9 明确禁止的写法**（v1 原文：不要 `status = Accepted` / `status = Judging`，
因为这是两种概念）。v2 抄了「别发明第二套枚举」的结论，却没发现**现存的就是那个坏例子**。

**为什么必须在 Scoreboard 之前修**：Activity 一上来就会卡住——

```text
ICPC 需要：按 verdict 判罚时、按是否 AC 计 solved
Homework 需要：按 score 求和，与 state 无关
两者都需要：「这次 run 还在跑」不能等价于「这次 run 判成了某个结果」
```

单枚举一旦进了 `oj_activity_problems.max_score` 的算分链路，
**Scoreboard 就要跟着改两遍**。

**修法**：

```python
class RunState(str, Enum):     # 新增，列名 run_state
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    SYSTEM_ERROR = "system_error"

class RunVerdict(str, Enum):   # 由 RunOutcome 去掉 PENDING 后原样保留
    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    ...
```

`RunOutcome` 可保留为**聚合结果**（带 PENDING 的旧语义）或直接作为兼容别名，
但算分链路只读 `RunVerdict`。

### A.1.2 Run 没有状态字段，v2 §19 的那套状态机无处落地

**v2 原文（§19）**：

> `## Run  QUEUED / RUNNING / FINISHED / FAILED / CANCELLED`

**实测**：`ExperimentRun`（`experiment_model.py:255-312`）的实际列只有
`outcome`、`submitted_at`、`finished_at`、`cancel_requested_at`。
**没有 `state` / `status` 列。** 运行态实际挂在 `task_id` → `TaskRecord`（`platform/tasks/`）。

所以 v2 §19 结尾那句「如果现有状态定义不同，优先适配现有模型，不为了名字重写」
**在 Run 这一项上落不了地**——没有可适配的对象。

**必须显式二选一**（写进 ADR，不能含糊）：

1. 加 `run_state` 列（配合 A.1.1 一起做，Alembic 一次迁移搞定）；或
2. 定义 `Run 状态 := TaskRecord 状态的投影`，不落库，查询时 join `tasks`。

推荐 (1)：TaskRecord 是**基础设施层**概念，把它当业务状态会让
OJ 域无法脱离 task framework 独立演进，也拖慢 §12.3「我的提交」这类只读查询。

### A.1.3 三处 schema 变更被 §21 的表清单漏记

v2 §21 明确把「P0 不新增」写清楚了，但 **P0 要增的列没写**：

| v2 章节 | 隐含的 schema 变更 | 现状证据 |
|---|---|---|
| §13 | `ExperimentRun.run_type = TEST \| SUBMISSION \| REFERENCE_PREVIEW` | 模型无此列；`RunCreateRequest` 只有 `language` + `source_code`（`experiments.py:94-96`） |
| §19 | Run 状态字段 | 见 A.1.2 |
| §12.1 | 题库页要展示 **难度 / 标签** | `ExperimentDefinition`（`:46-95`）**无 `difficulty` 无 `tags`**；全仓唯一的 `difficulty` 在 `CodingChallengeOffer`（`:342`），是另一张表 |

`ExperimentDefinition` 实际字段只有：`title` / `description` / `statement_object_key` /
`language_whitelist` / `default_version_id` / `publish_status` / `knowledge_node_ids` /
`max_attempts` / `cooldown_minutes` / `origin` / `visibility` / `owner_student_id` / `expires_at`。

**后果**：v2 §28 给每个 PR 定的验收是「0 schema change / 0 API behavior change / tests green」，
而 PR-10「学生题目列表」照 §12.1 的画法**当场就会需要新列**。
按 v2 自己的 DoD，这个 PR 无法通过验收。

**修法**：§21 补一节「P0 新增/修改列」，把这 3 项列进去，并明确
`difficulty` / `tags` 是走 `ExperimentDefinition` 新增列（推荐，题目身份级）
还是走独立 `oj_tags` + 关联表（v1 的方案，更重）。

### A.1.4 `modules/` 会成为仓库里**第三套**目录约定——而 v2 §25 恰好要求先读 AGENTS.md

**实测**：`backend/app/modules/` **当前不存在**。
现有顶层：`api / audio_storage / collectors / common / core / domain / engine /
external_apis / models / platform / schemas / scripts / services / tools / utils`。

仓库已有**两套**约定：

| 约定 | 形态 | 权威出处 |
|---|---|---|
| 分层 | `api/` `services/` `models/` `domain/` `core/` `platform/` `schemas/` | `AGENTS.md` §2.1 |
| 垂直切片 | `platform/agents/{edu,prep,coding,research}/` + `{contracts,providers,runtime,tools,shared,policies,prompts,workflows}/` | `AGENTS.md` §2.3（含表格逐目录职责） |

**而 `domain/` 已经是领域逻辑的家**：`education_graph/` `knowledge_bundle/`
`learning/` `safety/` `student_memory/`。

v2 §25 说「实施前必须先读 `AGENTS.md` / `design.md` / 模块 DESIGN.md」——
**读了就会撞上这个冲突**：AGENTS.md 里 vertical slice 的先例是
`platform/agents/<agent>/`，不是新增顶层 `modules/`。

**落点建议（按契合度排序）**：

```text
1. backend/app/domain/oj/          ← 推荐。与 domain/ 既有五个领域模块并列，语义最贴
2. backend/app/platform/oj/        ← 次选。与 AGENTS.md 既有 vertical slice 先例一致
3. backend/app/modules/oj/         ← 需 ADR 显式说明为何引入第三套约定
```

**并且**：v2 §26 列的 ADR 九条里**没有「目录约定裁定」这一条**，必须补上——
否则第一批 PR 就会把第三套约定既成事实化。

---

## A.2 P1：门禁用错了

### A.2.1 §38 DoD 第一条「原 experiments contract tests 全绿」给不了它要的安全感

v2 §24 引用的是 `frontend/src/api/__tests__/apiContracts.test.cjs`。
这个文件的机制是**读源码 + 正则断言**（`read()` 后 `assert.match(...)`），
**不是 HTTP 级契约测试**。

后果：**拆 `experiment_service.py` 时它不会红。** 把 2261 行按 use case 拆成 7 个 service，
只要类名/字符串还在，正则全绿，而真实行为可能已经漂移。

v2 §23 的 characterization tests 才是正确的门禁——但 §38 的 DoD 引用错了对象。

**修法**：§38 重构 DoD 第一条改为

```text
- [ ] pytest characterization tests 全绿，且新增用例数 ≥ 被拆 public 方法数。
       （正则型 apiContracts 只作为附加检查，不作为行为回归门禁）
```

同理 §42 的 hard constraint #7「Preserve all existing API contract tests and behavior」
应拆成两句，明确**行为那半句靠 pytest**，别让执行者以为跑绿 `node --test` 就安全了。

### A.2.2 双路由（§14）缺「授权一致性」DoD

v2 §14：「两套 route → 调同一 Application Service → 同一数据库。这是双路由，不是双事实源。完全安全。」

**「同一 service」不自动等于「同一授权」。** 只要有一处权限/行为分支写在 router 层，
新路径就会各自演化。**而且仓库里已经有这样一个实例**：

`backend/app/api/v1/endpoints/experiments.py:319-327`（`list_definitions`）：

```python
summaries: dict = {}
if context.role is not None and context.role.value == "student":
    summaries = attempt_service.student_summaries(...)
items = [_serialize_definition(d, ..., student_summary=summaries.get(d.experiment_id)) ...]
```

**这是 endpoint 级的角色分支。** 新 `/oj/problems` 路径若照抄一遍，
学生/教师视图的差异逻辑就有两份，必然漂移。

**修法**：v2 §38 安全 DoD 加一条

```text
- [ ] 同一资源的两个路径必须调用同一个 policy/service 函数；
      不允许任何 router 级权限分支或角色分支。
```

并把「视图差异（学生/教师 DTO）」下沉到 service/serializer 层，作为前置重构项。

---

## A.3 我唯一实质性不同意 v2 的地方：前缀策略用了两把尺子

v2 在**表名**上选择了「不改」，在**URL** 上选择了「改」：

| | v2 的选择 | 成本 | 收益 |
|---|---|---|---|
| 物理表名 | **不改**，保留 `experiment_*`（§1） | 命名债 | 避免大面积 migration / rollback |
| API 路径 | **改**，`/api/v1/experiments` → `/api/v1/oj`（§35、§14） | 26 个端点 + 前端 49 个 API client + 108 条契约测试 + 长期双路由 | 命名清晰 |

**这两个决定的成本结构完全相同，收益也完全相同。** 但 v2 对它们用了相反的标准。

而且 **v2 实际上已经处于「半改」状态**：§21 把新增的三张表命名为
`oj_activities` / `oj_activity_problems` / `oj_activity_scopes`。
结果是同一个域里会出现：

```text
oj_activity_problems.problem_definition_id  →  experiment_definitions.id
oj_activity_problems.problem_version_id     →  experiment_versions.version_id
```

**前缀反而变成了「新旧分界」的永久标记**——正是 v2 全篇想避免的双系统观感。

**建议（二选一，不要含糊）**：

- **方案甲（推荐）**：**都不改**。新表沿用既有命名（`experiment_activities` 等），
  URL 不做 canonical 迁移。理由：`/experiments` 是前端与测试的既有资产，
  改名风险不低于收益；既然「前缀不重要」成立，对 URL 同样成立。
  把「experiment 是历史命名」记为**已接受的债**，而不是假装它中性。
- **方案乙**：**都改**。既然要引入 `/oj`，就顺手把表也 rename（v2 自己说
  「等稳定后再做」，但那时候成本更高、牵扯更多）。

**无论选哪个，v2 §1 的论证需要补一句**：不改表名的真实理由是
「migration 风险 > 命名收益」，而不是「前缀不重要」——否则无法解释 §21 为何引入新前缀。

---

## A.4 v2 漏掉的既有事实（两条能让它少干活）

### A.4.1 「Run 自定义输入」已经存在，不是缺口

**实测**：

- `SandboxClient.submit_code(self, source_code, language, stdin="", expected_output="", limits=None)`
  —— **已支持 stdin**（`backend/app/services/sandbox_client.py:163-168`）
- `POST /api/v1/sandbox/course/{course_id}/execute` 的请求体已有 `stdin` 字段
  （`sandbox.py:49`，`max_length=100_000`）并透传（`:170`）

所以 v1「学生 P0 清单」里的「Run 自定义输入」其实**已经有了**，
只是在 `/sandbox/course/{id}/execute` 而不是某道题下面。

v2 §12 列学生缺口时既没把它列为缺口，也没指出可复用——
**等于放着一个现成能力不用**。学生侧真正要做的只是：
把它接进题目上下文 + 加 `run_type` 区分（见 A.1.3）。

### A.4.2 「hidden testcase 不进学生 DTO」已经实现，应写成回归测试而非待建项

**实测**：`backend/app/api/v1/endpoints/experiments.py:572` 原文注释：

> 学生视图：返回隐藏测试条目但不暴露 stdin/expected_stdout；教师视图完整暴露

配套在 `:198-211`（`_serialize_test_case`：隐藏测试仅教师可见）。

v2 §38 把「学生拿不到 hidden testcase」列为安全 DoD 待办项——
**它已经满足**。应改写为「**回归**测试保持绿」，否则执行者会重复实现。

### A.4.3 学生题库 / 自练的设计挂点已经有了

**实测** `ExperimentDefinition`（`experiment_model.py:87-90`）：

```python
origin: str = Field(default="teacher", index=True, max_length=32)
visibility: str = Field(default="course_catalog", index=True, max_length=32)
owner_student_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
expires_at: Optional[datetime] = Field(default=None, index=True)
```

`visibility="course_catalog"` + `origin` + `owner_student_id` 说明
**「课程目录可见 / 学生自建 / 归属学生 / 过期」这套概念已经预留**。

v2 §12 的「题库页」很可能**不需要新表**，只需：查询 + 暴露 + 补 `difficulty`/`tags`（A.1.3）。
v2 漏了这个省事的既有钩子，把 §12 当成纯新增来写。

---

## A.5 v2 做对的（明确保留，别重写）

| v2 章节 | 判断 |
|---|---|
| §1 不改物理表名的论证（迁移风险 > 命名收益） | 正确（但论证需按 A.3 补一句） |
| §2 **两层版本冻结**（活动公平性 vs 单次尝试不漂移） | **v2 新增且正确**，比 v1 清楚。`attempt.version_id = activity_problem.version_id` 的规则成立 |
| §5 Judge0 单出口 + `JudgeResult` 归一化 | 精确命中 `experiment_service.py:1028` 的 `result.compile_output` 泄漏 |
| §6 / §6.1 不引入 Celery / Redis，并给出 Redis 唯一引入条件（多进程 + 低延迟 SSE） | 比 v1 严谨 |
| §7 继续 CodeMirror 6 | 正确 |
| §10 把 diagnosis / hint / explanation 提为 `intelligence/` 正式子域 | 修正了 v1 的优先级倒挂，这是最重要的一处修正 |
| §11 知识点 P0 继续 `knowledge_node_ids`，weight 延后并区分「关联 vs 强度」 | 正确，避免了双字段表达同一语义 |
| §13 「Submit 是产品行为，不一定建表」+ 用 `run_type` 而非新表 | **方向完全正确**（缺的只是承认它是 schema 变更，见 A.1.3） |
| §22 八步治理 + §23 characterization tests | v1 完全没有，这是「搬家不改行为」的唯一可行路径 |
| §37 「每阶段明确禁止事项」 | 防跑偏最有效的机制 |
| §42 可直接执行的 Goal 文本 | 实用 |
| §43 八个 Issue 切分 | 可执行 |

---

## A.6 落地前必须补齐的硬清单

| # | 动作 | 对应 |
|---|---|---|
| A | §21 补「P0 新增/修改列」一节：`run_type`、`run_state`、`difficulty`/`tags` | A.1.3 |
| B | §19 拆 `RunState` / `RunVerdict`，并**排到 Scoreboard 之前** | A.1.1 |
| C | Run 状态落地方式二选一（加列 / task 投影），写进 ADR | A.1.2 |
| D | §26 ADR 加一条：**目录约定裁定**（`domain/oj/` vs `platform/oj/` vs `modules/`） | A.1.4 |
| E | §38 DoD 第一条改为 pytest characterization 门禁；§42 constraint #7 拆成两句 | A.2.1 |
| F | §38 安全 DoD 加「双路径同 policy，禁 router 级权限分支」 | A.2.2 |
| G | §1 与 §21/§35 的前缀策略二选一（建议方案甲：都不改） | A.3 |
| H | §12/§38 写入三条既有事实：自定义输入已有、hidden testcase 已隔离、`visibility`/`origin`/`owner_student_id` 已预留 | A.4 |

**做完 A–H，v2 就可以直接开 PR-00 了。**

