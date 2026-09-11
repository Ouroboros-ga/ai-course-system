# CodeNexus OJ 整改 · 改动说明

- 日期：2026-09-11
- 输入：`CodeNexus_OJ_生产级整改方案_v2.md` + 评审 A–H 八条修正
- 产出：`docs/phase1/2026-09-11_CodeNexus_OJ整改落地方案_v3.md`（v3 方案）
- 状态：**PR-00 完成，PR-01 完成并验证**

---

## 1. 交付清单

### 1.1 文档（PR-00）

| 文件 | 用途 |
|---|---|
| `docs/phase1/2026-09-11_CodeNexus_OJ整改落地方案_v3.md` | 可执行方案：复用/原创/引用三分类 LOC 统计 + 17 个 PR 排序 + DoD |
| `docs/architecture/oj-current-state.md` | **实测**现状盘点（25 端点 / 13 表 / 服务 / 前端 / 测试基线 / 5 条 smell） |
| `docs/adr/ADR-0001-oj-domain-consolidation.md` | 12 条架构裁定，含目录落点与前缀策略 |
| 本文件 | 改动说明与实施记录 |

### 1.2 代码（PR-01）

| 文件 | 变更 | 行数 |
|---|---|---|
| `backend/app/domain/oj/__init__.py` | 新增（域入口与子域说明） | 25 |
| `backend/app/domain/oj/judging/__init__.py` | 新增 | 10 |
| `backend/app/domain/oj/judging/verdicts.py` | 新增（`RunState` / `RunVerdict` + 映射） | ~183 |
| `backend/app/domain/oj/submissions/__init__.py` | 新增 | 10 |
| `backend/app/domain/oj/submissions/run_types.py` | 新增（`RunType`） | ~78 |
| `backend/app/models/experiment_model.py` | 改：+2 列、+1 导入、+1 监听器 | +88 / −1 |
| `backend/alembic/versions/20260911_1400_oj_run_semantics.py` | 新增迁移 | ~170 |
| `backend/tests/test_oj_run_semantics.py` | 新增（46 用例，含 3 条迁移回填往返） | ~487 |

**净新增约 970 行，删除 1 行。**

> 迁移回填组的 3 个用例各要跑 3–5 次完整迁移链（`upgrade head` ↔ `downgrade`），
> 单组耗时约 **3 分 12 秒**。这也是 `tests/test_alembic_migration.py` 本身慢的原因。
> 若后续觉得拖慢 CI，可给该组加 `@pytest.mark.slow` 并默认排除。

---

## 2. v2 → v3 的八条修正

| # | v2 原状 | v3 修正 | 落点 |
|---|---|---|---|
| **A** | §21 只列了 P0 要新建的 3 张表，未列要新增的**列** | §3.2 补「P0 新增/修改列」：`run_state`、`run_type`、`difficulty`、`tags` | 方案 §3.2；PR-01 实施前两项 |
| **B** | §19「沿用现有 `RunOutcome`，不要再发明第二套枚举」 | **拆 `RunState` / `RunVerdict`**，且排在 Scoreboard 之前 | PR-01 |
| **C** | §19 列了 Run 状态机，但模型无状态列 | 裁定为**新增 `run_state` 列**（放弃「task 状态投影」方案） | ADR 决定 4 |
| **D** | §3 提议新建 `backend/app/modules/oj/` | 改为 **`backend/app/domain/oj/`**（不引入第三套目录约定） | ADR 决定 2 |
| **E** | §38 DoD 以「contract tests 全绿」作行为门禁 | 改为 **pytest characterization**；正则型 `apiContracts` 只作附加检查 | 方案 §7 |
| **F** | §38 安全 DoD 未覆盖双路径授权一致性 | 加「同一资源两路径必须调同一 policy；禁 router 级权限/角色分支」 | 方案 §7；S2 已登记 |
| **G** | §1 不改表名，§21 却引入 `oj_*` 新前缀 | **都不改**：新表沿用 `experiment_*`，URL 不引入 `/oj` | ADR 决定 6；方案 §9 |
| **H** | §12/§38 把已实现能力当待建 | 写入三条既有事实（自定义输入已有 / hidden testcase 已隔离 / 题库挂点已预留） | 方案 §2.2 |

### 2.1 修正 B 是本次最关键的改动

v2 §19 的原文是「沿用现有 `RunOutcome`，不要再发明第二套枚举」。
但实测 `experiment_model.py:242-252` 的 `RunOutcome` **正是 v1 明令禁止的单枚举反模式**：

```python
class RunOutcome(str, Enum):
    PENDING = "pending"                      # ← 运行状态
    ACCEPTED = "accepted"                    # ← 判定结果
    WRONG_ANSWER = "wrong_answer"
    ...
```

v2 抄了「别发明第二套枚举」的结论，却没发现**现存的就是那个坏例子**。
做 Activity / Scoreboard 时立刻卡住：ICPC 要按判定算罚时、Homework 要按分数求和，
两者都需要表达「还在跑」**且**「已经跑出某个结论」。

---

## 3. PR-01 实施记录

### 3.1 做了什么

**新增领域语义层（不依赖 models）**

```text
RunState    queued / running / finished / cancelled / system_error
RunVerdict  accepted / wrong_answer / time_limit_exceeded / memory_limit_exceeded
            runtime_error / compilation_error / internal_error / sandbox_unavailable
RunType     submission / test / reference_preview
```

配套：`state_for_outcome()`、`verdict_for_outcome()`、`is_terminal_state()`、
`is_system_verdict()`、`normalize_run_type()`、`is_scored_run_type()`。

**新增两列 + 一个监听器**

- `experiment_runs.run_state`（默认 `queued`，索引）
- `experiment_runs.run_type`（默认 `submission`，索引）
- `_sync_run_semantics` 监听器（`before_insert` / `before_update`）：
  **单点**保证 `run_state` 与 `outcome` / `cancel_requested_at` 不脱节

**迁移**：`oj20260911v1`，加列 + 建索引 + 回填 + 写 `schema_migration_records` 台账

### 3.2 三个关键设计决定

**① 用监听器而不是在业务代码里补写**

`outcome` 在 `experiment_service.py` 有 **11 处赋值点**（`:852` 创建、
`:965`/`:1015`/`:1070` 三条独立的 `sandbox_unavailable` 分支、`:1089-1103` 判定分支）。
逐处补写 `run_state` 必然漂移；监听器只有一处，且新增赋值点自动生效。

`RUNNING` 例外：`outcome` 无法表达「正在判题」，故编排层显式写 `RUNNING` 时监听器不覆盖。
这是 PR-04 的前置约定。

**② 领域层不 import models**

`verdicts.py` / `run_types.py` 只依赖标准库。映射函数按值归一化
（`getattr(value, "value", value)`），因此 `domain/oj` 不依赖 `app.models`，
不构成依赖环，也不会把 2261 行 service 的导入链拖进来。

**③ 新列不进 API 响应**

PR-01 的 DoD 要求「响应体逐字节不变」，因此**没有**改 `_serialize_run`。
并补了一条用例把「不泄漏」变成受保护的约束，而不只是当前事实。

### 3.3 施工中抓到的两个坑

**坑 1：`outcome` 是 PG 原生 enum，库里存的是大写成员名**

```text
基线迁移 20260726_1343_0001_legacy_schema_baseline.py:1256
  sa.Column('outcome', sa.Enum('PENDING', 'ACCEPTED', ..., name='runoutcome'))
```

没有 `values_callable`，所以 SQLAlchemy 存的是**成员名（大写）**，
而 API 暴露的是 `.value`（小写，`_serialize_run` 里 `r.outcome.value`）。

**回填 SQL 若按小写比较会一行都匹配不上，静默把全部历史 run 留成 `queued`。**
迁移里统一用 `CAST(outcome AS TEXT)` 并比较大写。

同一个坑在领域层也埋着：`verdict_for_outcome("ACCEPTED")` 若只走 `RunVerdict(raw)`
会返回 `None`，被读成「还没判完」，进而把已完成的 run 排进待判队列。
已让 `_coerce()` 同时接受 `.value`（小写）与成员名（大写），并各补了用例。

**坑 2：`ruff --unsafe-fixes` 越界重写了整个模型文件**

`--fix --unsafe-fixes` 把 `experiment_model.py` 里 **54 处 `Optional[X]`** 全改成
`X | None`，产生 193 行与本次改动无关的 churn。

**已 `git checkout` 回滚并逐块重新施加改动**，现在 diff 是 **+88 / −1**，
且 `Optional` 一处未动（本仓房风格统一使用 `Optional`，ruff 未配置、也非门禁，
既有 `experiment_service.py` 本身有 43 条告警）。

**教训**：`--unsafe-fixes` 不要跨文件批量跑；只在自己新写的文件上跑，
已存在的文件一律手工最小编辑。

### 3.4 验证

| 检查 | 结果 |
|---|---|
| `pytest tests/test_oj_run_semantics.py` | **46 passed**（4 分 21 秒；含 3 条迁移往返） |
| 迁移：空库 `upgrade head` | 通过，链尾 = `oj20260911v1` |
| 迁移：列 / 索引 / 台账 | `run_state`、`run_type` 均 NOT NULL 且带 server_default；两个索引存在；`schema_migration_records` 已写入 `applied` |
| 迁移：**带回填的往返**（独立 SQLite 直跑） | `upgrade → downgrade -1 → upgrade` 全通过；**6 个回填分支逐一比对正确**；`run_type` 全为 `submission`；`applied_rows=6` |
| 迁移：降级无损 | 删列后 6 行数据全部保留（SQLite batch 重建表不丢数据） |
| `ruff check`（新增文件） | All checks passed |

**回填逐分支实测结果**（这是 PR-01 唯一会改写既有数据的步骤）：

| 历史 `outcome`（库内形式） | `cancel_requested_at` | 期望 `run_state` | 实测 |
|---|---|---|---|
| `PENDING` | 无 | `queued` | ✅ |
| `PENDING` | 有 | `cancelled` | ✅ |
| `SANDBOX_UNAVAILABLE` | 无 | `system_error` | ✅ |
| `INTERNAL_ERROR` | 无 | `system_error` | ✅ |
| `ACCEPTED` | 无 | `finished` | ✅ |
| `WRONG_ANSWER` | 无 | `finished` | ✅ |

**为什么迁移算"真跑过"**：`conftest.py::test_engine` 用
`alembic upgrade head` 建测试库（而非 `create_all`），所以用例通过即意味着
本次迁移在真实迁移链上执行成功。此外又用独立 SQLite 手工跑了带数据的往返
（上表），**因为既有测试库里 `experiment_runs` 是空的，`applied_rows=0`，
回填路径在自动测试中并未被覆盖** —— 这部分已补成自动化用例（见 §3.6）。

### 3.5 回归范围与结果

```bash
pytest tests/test_oj_run_semantics.py \
       tests/test_experiments.py \
       tests/test_experiment_sandbox_contract.py \
       tests/test_p1_7_judge0_sandbox_port.py \
       tests/test_sandbox.py \
       tests/test_alembic_migration.py
# → 117 passed, 7 skipped, 19 errors
```

**19 个 error 与本改动无关**，全部是同一种环境问题：

```text
ERROR at setup of ...
E   PermissionError: [WinError 5] 拒绝访问。:
    'C:\Users\LIU\AppData\Local\Temp\pytest-of-LIU'
```

- 发生在 **setup 阶段**，早于任何被测代码或迁移代码执行；
- 路径是 pytest 的**默认 tmp 根**（`%TEMP%`），本机沙箱拒绝写入；
- 中招的正是所有使用 `tmp_path` 夹具的用例：`test_alembic_migration.py`（16 个）
  与 `test_p1_7_judge0_sandbox_port.py::TestBootstrapInjects*`（2 个，签名带 `tmp_path`）；
- **`tests/test_experiments.py` 全绿** —— 即本次改动的主回归面（1991 行）无影响。

**判定依据**：仓库自己的 `conftest.py` 刻意用 `Path.cwd() / ".pytest_tmp"` 而不是
`tmp_path`，说明这个环境限制是已知的。绕法：`pytest --basetemp=<工作区内目录>`。

**本文件新增的用例也遵循同一约定**（`TestMigrationBackfill._db_path()` 落在
`backend/.pytest_tmp/`），因此不需要额外参数即可运行。

### 3.6 补的自动化用例（防止回填退化的唯一手段）

| 用例 | 断什么 |
|---|---|
| `TestMigrationBackfill::test_backfill_maps_every_outcome_branch` | 6 个 `outcome` 分支 → 6 个正确 `run_state`（真实迁移往返 + 数据） |
| `...::test_backfill_sets_submission_for_every_historical_row` | 历史行 `run_type` 全为 `submission` |
| `...::test_downgrade_drops_columns_and_keeps_rows` | 降级删列且**不丢数据** |
| `TestResponseShapeUnchanged::test_serialize_run_does_not_expose_new_columns` | 新列不进 API 响应（DoD 锁） |
| `TestRunVerdictVocabulary::test_run_verdict_values_match_run_outcome_minus_pending` | 不得引入第二套判定词汇 |
| `TestRunStateIsKeptInSync::*`（6 条） | 监听器：默认值、随 outcome 重算、系统故障、取消、`RUNNING` 不被覆盖、终局归位 |

---

## 4. 本轮明确**未做**（边界）

| 项 | 原因 |
|---|---|
| `difficulty` / `tags` 列 | PR-09，只有学生题库页（PR-10）消费；提前加会在无消费者时改动序列化 |
| `_serialize_run` 暴露新列 | 违反 PR-01「响应体逐字节不变」的 DoD；留待有明确消费者的 PR |
| 拆分 `experiment_service.py` | PR-03 / PR-04；必须先补 characterization 测试 |
| Judge0 出口收拢 | PR-05；`experiment_service.py:1028` 的 `compile_output` 泄漏仍在 |
| `codebench.py` 死壳删除 | PR-17；留到旧路由迁移完成后再删 |
| Router 级角色分支下沉（smell S2） | 双路径出现前处理；已在 DoD 登记为约束 |
| 任何前端改动 | PR-12 起；本轮不动前端 |
| 任何 URL 变更 | ADR 决定 6：不引入 `/oj` 前缀 |

---

## 5. 下一步

```text
PR-02  backend/app/domain/oj/ 骨架 + 兼容 import shim（0 行为变化，0 schema 变化）
PR-03  拆 experiment_service → problems services
PR-04  拆 experiment_service → attempt / run services（此时 run 会先置 RUNNING）
PR-05  Judge0 单一出口 + JudgeResult 归一化
PR-06  intelligence 归位
──────── 以上为第一阶段：无新业务、行为不变 ────────
PR-07  Activity 域（+3 表）
PR-09  difficulty / tags（+2 列）
PR-10  学生题库 / 我的提交 / 提交详情 façade
PR-11  HomeworkScoreboard
PR-12  学生 Activity 页 + 教师 Activity 管理页
```

**开 PR-02 前的前置**（来自 v3 §7 与 ADR）：

- 先补 characterization 测试覆盖 `experiment_service.py` 的公开行为
  （既有 1177 行判题契约测试已覆盖 ACM 终局 / 配额 / 租约 / Port 降级，
  缺口比 v2 估计的小得多）
- 目录落点已裁定为 `domain/oj/`，`AGENTS.md` §2.3 未把 `modules/` 列入，
  因此 PR-02 不需要先改 `AGENTS.md`

---

# 6. PR-02：Judge0 出口单一化（已实施）

## 6.1 做了什么

| 动作 | 内容 |
|---|---|
| **搬家** | `app/services/sandbox_client.py`（332 行）→ `app/domain/oj/judging/providers/judge0.py` |
| **补 `__all__`** | provider 显式声明 8 个导出符号，导出面不再隐式 |
| **新增包** | `domain/oj/judging/providers/__init__.py`，写明「Judge0 传输细节只允许在本目录内」 |
| **切换调用点** | 4 个生产调用点 + 8 个测试文件的引用全部指向新路径（31 处） |
| **删除 shim** | 一度创建的 `services/sandbox_client.py` 兼容 shim **最终删除** |
| **新增契约测试** | `tests/test_oj_judging_provider_layout.py`（11 条） |

对应 ADR-0001 决定 3。**0 行为变化、0 schema 变化、0 API 变化。**

## 6.2 为什么最后**没有**保留兼容 shim（本轮最重要的教训）

第一版做的是「搬家 + 旧路径留纯再导出 shim」——这是教科书式做法。一跑测试就发现它不成立：

```text
tests/test_sandbox.py:
  @patch("app.services.sandbox_client.httpx.Client")
```

既有测试用**模块路径字符串**做 monkeypatch。shim 对这类 patch **无能为力**：

1. shim 只再导出公共 API，命名空间里没有 `httpx` / `time` / `settings`
   → `AttributeError: <module 'app.services.sandbox_client'> does not have the attribute 'httpx'`（12 条测试当场红）；
2. **更危险的是**：如果把 `httpx` 也塞进 shim，patch 只会改 **shim 命名空间里的名字**，
   而真实模块里 `submit_code` 用的仍是原对象 ——
   **测试照样全绿，但一个断言都没打到真实代码**，静默失去覆盖。

**结论：兼容 shim 能保住 `import`，保不住「按模块路径字符串定位的 patch」。**
遇到后者，只能彻底切换 + 删 shim，让「唯一出口」成为字面事实，而不是留两个可 patch 的位置。

这条对后续 PR 同样适用：**任何搬文件的 PR，都要先 grep 一遍
`patch("<旧模块路径>.` 和 `monkeypatch.setattr("<旧模块路径>.`。**

（本轮实测：`patch("app.services.sandbox_client.httpx.Client")` 14 处、
`time.sleep` 1 处、`sandbox_client` 单例 2 处、`from app.services import sandbox_client as sb_mod`
这种**不含子串**的写法 9 处 —— 最后这一类用 `app.services.sandbox_client` 做替换是抓不到的，
必须单独 grep `from app.services import sandbox_client`。）

## 6.3 新增的契约测试守四件事

| 断言 | 防的是什么 |
|---|---|
| 旧路径 `ModuleNotFoundError` + 磁盘无 shim 文件 | 有人把 shim 加回来，制造第二个可 patch 的位置 |
| 全仓无 `from app.services.sandbox_client import` | 半途而废的切换（**该断言会跳过本文件自身，否则自匹配恒红**） |
| `class SubmissionStatus` 全仓只有一处定义 | 判定枚举被重复定义 —— 对应 PR-01 的 `RunVerdict`，两套词汇并存会算错排名 |
| `X-Auth-Token` / `"base64_encoded"` 只出现在 `providers/` 内（`core/config.py` 豁免） | Judge0 传输细节再次泄漏进业务层（ADR-0001 决定 3） |

## 6.4 验证

| 检查 | 结果 |
|---|---|
| `ruff check`（本轮新增/改写文件） | All checks passed |
| `pytest tests/test_oj_judging_provider_layout.py tests/test_sandbox.py` | **31 passed** |
| 完整回归（9 个文件） | 见 §6.5 |
| 单例身份 | `experiment_service.sandbox_client is providers.judge0.sandbox_client` → `True` |

**搬进来的 `judge0.py` 有 10 条既有 ruff 告警**（BLE001 盲捕获 ×2、F401 ×1、I001 导入未排序 ×1、
PIE790 ×1 等）——**这些是搬家前就有的**，按「已有文件手工最小编辑」的规矩本轮不碰，
留 PR-05 一起清（该轮要改 `experiment_service.py:1028` 的 `compile_output` 泄漏，正好同批处理）。

## 6.5 回归结果

```bash
pytest tests/test_oj_judging_provider_layout.py tests/test_sandbox.py \
       tests/test_experiment_sandbox_contract.py tests/test_experiments.py \
       tests/test_oj_run_semantics.py tests/test_stabilization.py \
       tests/test_acceptance.py tests/test_coding_challenge_generation.py \
       tests/test_p1_7_judge0_sandbox_port.py
```

**结果：196 passed / 0 failed / 11 errors**（5 分 09 秒）。

11 个 error **全部是环境问题、与本改动无关**：均为 setup 阶段的
`PermissionError: [WinError 5] 拒绝访问 C://Users//LIU//AppData//Local//Temp//pytest-of-LIU`
（沙箱拒绝写 `%TEMP%`）。中招的是使用 `tmp_path` 的用例：
`test_stabilization.py` 的 ObjectStorage/Migration/BackupRestore（9 个）
与 `test_p1_7_judge0_sandbox_port.py::TestBootstrapInjects*`（2 个）。
全部 12 条曾经变红的沙箱用例已恢复绿色。

### 6.5.1 顺带修掉一个我自己的 flaky

`TestMigrationBackfill` 在与 `test_experiments.py` 同批运行时**偶发**一条失败，
单跑全绿。根因是 `run_alembic` 起的 alembic engine 在 Windows 上不立刻释放文件句柄，
固定名的临时 DB（`backfill_*.db`）被上一次运行或同批次里被 kill 的会话留下的
`.db` / `-journal` 锁住。
**修法**：`_db_path()` 每次加 8 位随机后缀，彻底避免复用同名文件。
**教训**：Windows 上「固定名的临时 SQLite + 不保证立刻 dispose 的 engine」是 flaky 温床，
临时库一律用唯一名。

## 7. PR-05 实施记录：判定词汇表归位

### 7.1 做了什么

`services/experiment_service.py` 里的私有方法 `_outcome_to_reason` 维护着一张
**10 条「sandbox 状态 → `test_summary[].reason`」映射表**。这张表是 OJ 判定语义的
一部分，却住在业务服务层。本轮把它搬到判题域，业务服务只留薄委托。

**新增（`domain/oj/judging/verdicts.py`）：**

```python
REASON_BY_STATUS: dict[str, str] = {
    "accepted": "passed",
    "wrong_answer": "wrong_answer",
    "time_limit_exceeded": "time_limit_exceeded",
    "memory_limit_exceeded": "memory_limit_exceeded",
    "runtime_error": "runtime_error",
    "compilation_error": "compilation_error",
    "internal_error": "internal_error",
    "in_queue": "pending",
    "processing": "pending",
    "sandbox_unavailable": "sandbox_unavailable",
}
UNKNOWN_REASON = "unknown"

def reason_for_status(status) -> str: ...   # 认不出的状态 → UNKNOWN_REASON，不抛
```

**改（`services/experiment_service.py`）：**

```python
def _outcome_to_reason(self, status: SubmissionStatus) -> str:
    return reason_for_status(status)
```

映射表**逐条等值搬迁**，未改任何一条的取值。行为不变是这一轮的硬要求。

### 7.2 为什么保留 `_outcome_to_reason` 这个方法壳而不删掉

该文件内有多处调用点。保留方法壳、内部改委托，满足两件事：

1. 本轮 diff 面收敛到「导入 + 一个方法体」，不动调用点，降低与他线在途改动的冲突概率；
2. 将来若收回这个壳（让调用点直连 `reason_for_status`），是一次独立的、可单独回滚的
   纯机械改动 —— 而不是混在语义搬迁里一起做。

### 7.3 更正一处我此前的过度定性

我在 PR-02 记录里写过 `experiment_service.py:1028` 的 `result.compile_output` 是
「Judge0 细节泄漏进业务层」。**这个说法不成立，已更正**：

- `SandboxResult` 本身是**归一化后的类型**，不是 Judge0 原始响应；
- `compile_output` 是编译器输出的中性字段，Judge0、本地 runner 都有这个概念；
- `JUDGE0_STATUS_MAP` 本来就只在 provider 内，没有外泄。

**真实存在的问题只有一个**：判定词汇表（状态→reason）手写在业务服务里，
应当归判题域 —— 也就是本轮做的这件事。定位错误→修法错误，所以先把定性改对再动手。

同一批更正的还有 4 个文件的相关表述（评审文档、落地方案 v3、ADR-0001、本文档 §6）。

### 7.4 新增的契约测试

`tests/test_oj_run_semantics.py` 新增 **组 5 `TestReasonVocabulary`**（6 条）：

| 断言 | 守的是什么 |
|---|---|
| `REASON_BY_STATUS` 恰有 10 个键 | 有人偷偷加/删映射能被拦住 |
| `accepted → passed`、`in_queue`/`processing → pending` | 三条语义最容易被「顺手改顺眼」的项 |
| 已认出的 status 一律返回非 `UNKNOWN_REASON` | 防映射表键名拼写漂移 |
| 未知 status 返回 `UNKNOWN_REASON` 而不抛 | 契约是「永不抛」，Judge0 新增状态不能打挂业务 |
| `experiment_service._outcome_to_reason` 与 `reason_for_status` 逐条等值 | **委托未断**：方法壳还在，结果必须等于域函数 |
| 映射表不在 `services/` 下定义 | 防下一个人再把它抄回业务层 |

最后一条是这轮最有价值的一条：**它拦的不是「现在错」，而是「以后又错」**。

### 7.5 验证

```bash
pytest tests/test_oj_run_semantics.py tests/test_experiments.py \
       tests/test_oj_judging_provider_layout.py tests/test_sandbox.py \
       tests/test_experiment_sandbox_contract.py -q -p no:cacheprovider
```

**结果：121 passed / 0 failed / 0 errors**（6 分 13 秒，exit 0）。
`ruff check` 在本轮新增/改动文件上全部 All checks passed。

> 统计说明：`-rN` 压制了通过用例的重复清单，121 为去重后的实际用例数。
> 数字取自 `pytest ... > 文件` 后读汇总行 —— 直接 `| tail` 会被 pytest 收尾的
> `[safe-delete]` 清理提示挤掉汇总行，取不到数（本轮踩过两次）。

### 7.6 边界

- 未碰 `experiment_service.py` 中他线（学生工作台）的在途代码；
- 未动 `judge0.py` 的 10 条搬家前既有 ruff 告警（BLE001×2、F401、I001、PIE790 等）。
  这批告警与 `reason` 语义无关，**等有理由改该文件时一起清**，不为凑 lint 分数批量动它。

## 8. PR-06 实施记录：intelligence 判定规则归位域层

### 8.1 方案里的一个空洞

落地方案 §6 的目录树只写了 `domain/oj/intelligence/`，**没定义它包含哪些文件、
搬什么、留什么**。所以本轮第一步不是写代码，是**把成员量出来**。

实测三块「intelligence」的真实位置：

| 概念 | 实际位置 | 规模 |
|---|---|---|
| **diagnosis** | `services/coding_eduagent_service.py`（`_classify` / `CodingEduAgent`）+ `experiment_service.py:788 _ensure_coding_diagnosis` | 159 行 |
| **hint** | `experiment_service.py:2153-2241 CodingHintService` | ~90 行 |
| **explanation** | `services/coding_eduagent_service.py:120 build_rule_explanation` + `endpoints/experiments.py:1108` | ~50 行 |

方案里 PR-06 的前置写的是 **PR-04**（拆 `experiment_service.py`）—— 而 PR-04 正卡在他线在途代码上。

### 8.2 为什么本轮能先做：找到了不被阻塞的切口

三块里**只有 `hint` 在 `experiment_service.py` 内**。`diagnosis` + `explanation`
都在 `coding_eduagent_service.py`，该文件：

- `git status` 干净（**无他线改动**）；
- 有 3 个测试文件覆盖（`test_coding_eduagent_integration` / `test_coding_challenges` /
  `test_p1_fix2_fix3_run_id_flow`）。

所以 **PR-06 拆成两半**：本轮做 `diagnosis` + `explanation`（不被阻塞），
`hint`（`CodingHintService`）留到 PR-04 之后。这比「等 PR-04」或「硬拆 `experiment_service.py`」都更稳。

### 8.3 关键设计决定：搬语义，不搬 CRUD

**发现**：`domain/` 下既有 5 个模块（`learning` / `safety` / `student_memory` /
`knowledge_bundle` / `education_graph`）**对本约束零违反** ——

```bash
grep -rn "^from app\.models\|^from app\.services" backend/app/domain --include=*.py
# → 零命中
```

即本仓域层的实际惯例是：**域层定义「规则是什么」，服务层决定「何时读写数据库」**。
`domain/learning` 装的是枚举、值对象、聚合规则、映射器，**没有一张 SQLModel 表**。

**但**：`AGENTS.md:65` 只写「`backend/app/domain/`:领域逻辑(...)」，**没有明文禁止**
域层 import models。所以那条「零命中」是**实际惯例**，不是**成文规则** ——
这个区分很重要，我据此做的判断是**遵循惯例**而不是「违反成文规定」。

**做法**：

- `domain/oj/intelligence/rules.py` —— 纯函数 + `DiagnosisInput` 数据类。
  输入是与 ORM 解耦的归一化结构（字段是 `str` / `tuple[str, ...]`），
  域层因此**不必知道 SQLModel 的存在**。
- `services/coding_eduagent_service.py` —— 保留查库、`_diagnosis_input()`
  （ORM → 域输入适配）、持久化。

**收益**（已被测试证实）：域规则可脱离 session 直接调用与测试。

### 8.4 一处我主动留在 service 的逻辑

`_artifact_texts()` 筛选 `stderr` / `compile` 两类 artifact —— 这**留在 service**，
没搬进域。

理由：「哪类 artifact 算判定证据」是**业务侧的决定**，会随产品策略变；
而「拿到文本后怎么归类错误」是**领域规则**，相对稳定。把易变的策略混进域层，
域就会跟着业务需求频繁改动，失去「可脱离数据库独立测试」的价值。

### 8.5 characterization 测试当场纠正了我的一个错误假设

写测试时我断言「`_debug_steps` 所有分支都返回 3 条」。**跑出来是红的** ——

```
syntax       len=3
...
none         len=2   ← 只有 2 条
```

`none`（accepted）分支**只有 2 条**：通过时不需要修错指引。这是**有意的不对称**。

我改成显式断言 `test_none_branch_has_only_two_steps`，并写下：

> 这条断言的存在就是为了拦住后来者对称化这个不对称。

**这正是 characterization 测试的价值**：它把「我以为的行为」和「实际的行为」
当场分开。如果我直接搬迁、不写基线，这个 2 条会被我在「整理代码」时顺手补成 3 条，
而且没有任何测试能发现。

### 8.6 顺带修掉 5 个文件的 UTF-8 BOM

写域边界门禁时 `ast.parse` 直接抛错：

```
SyntaxError: invalid non-printable character U+FEFF
```

排查发现 `domain/oj/` 下 **5 个文件带 BOM**（`__init__.py`×2、`judging/verdicts.py`、
`submissions/__init__.py`、`submissions/run_types.py`）—— **都是我在 PR-01/02 建的**。

**危害**：Python 解释器**容忍** BOM，所以 import 正常、测试能过；但 `ast.parse`
**不容忍**。任何依赖 AST 的工具（静态分析、代码生成、本门禁）都会踩。
这是**工具链地雷**，不是风格问题 —— 平时完全静默，踩到才炸。

修法：`read_bytes()[:3] == b"\xef\xbb\xbf"` 判断后剥掉。核验结果是每个文件
**正好少 3 字节**，内容零改动。

同时新增 `test_no_utf8_bom_in_domain_modules` 防回归。

### 8.7 新增的域边界门禁（`test_oj_domain_boundaries.py`）

这是本轮最有长期价值的一条。`domain/oj/` 是新建目录且正在快速长大
（PR-07/11/14/15 还要往里加 Activity / Scoreboard / Analytics），
没有门禁时「顺手在域里查一下库」是最容易被接受的坏改动。

守四件事：

| 断言 | 拦住什么 |
|---|---|
| 整域禁 `app.models` / `app.services`（含 `providers/`） | 域层反向依赖业务层 |
| ORM / 传输库仅限 `providers/` 内 | 把 SQL 或 HTTP 散进域层 |
| `test_the_guard_actually_scans_something` | **门禁自己静默失效**（路径写错 → 永远绿） |
| 不引入 `backend/app/modules/` | ADR-0001 决定 2 放弃的第三套目录约定 |

第二条特意为 `providers/` 开了豁免：ADR-0001 决定 3 说 Judge0 HTTP 出口收拢于此，
它需要 `httpx`，但**仍不许** import `app.models` / `app.services` —— 两条禁令范围不同。

### 8.8 验证

```bash
pytest tests/test_oj_domain_boundaries.py tests/test_oj_intelligence_characterization.py \
       tests/test_oj_run_semantics.py tests/test_oj_judging_provider_layout.py \
       -q -p no:cacheprovider
```

**结果：125 passed / 0 failed / 0 errors**（5 分 20 秒）。

| 检查 | 结果 |
|---|---|
| 相关回归（4 文件，含既有集成测试） | 85 passed（1 个 `tmp_path` 环境 error，`--basetemp` 复跑 3 passed） |
| `ruff check`（本轮新增/改动文件） | All checks passed |
| BOM 移除核验 | 5 文件各少 3 字节，内容零改动 |
| 域规则脱离 session 可调用 | 已断言（`test_classify_runs_without_any_session`） |

### 8.9 边界与下一步

- **未碰** `experiment_service.py`（他线 212 行在途代码仍在）；
- `CodingHintService`（`experiment_service.py:2153-2241`）**留待 PR-04 之后** ——
  它是 PR-06 剩下的一半；
- `coding_eduagent_service.py` 的 `I001`（`experiment_model` 两行同名 import）
  是**改动前既有**问题，按「既有文件最小编辑」未在本轮触碰。

---

## 9. PR-09 实施记录：题目元数据（`difficulty` / `tags`）

### 9.1 为什么这个 PR 能先做

PR-03/04/06b 全部卡在同一条他线（学生工作台 F3-B）未提交的 212 行上，
而 **PR-09 的前置只有 PR-02**（已提交）。它新增的是两列 + 一个域模块，
**与 `experiment_service.py` 那批冲突代码没有交集需求**，因此可以在他线在途时推进。

具体做法：**服务层只做「最小追加」**，不重排既有代码 —— 这样提交时
`git apply --cached --recount` 能按 `@@` 边界精确切出我的 hunk，
不需要理解他线的 212 行在改什么。

### 9.2 方案里漏掉的一个决定：难度到底有几档

方案原文只说「补 `difficulty` 列」，**没定义取值域**。而仓库里现存的先例是**互相打架**的：

| 出处 | 取值 |
|---|---|
| `models/question_bank_model.py:35 QuestionDifficulty` | `easy` / `medium` / `hard` |
| `api/v1/endpoints/knowledge.py` | 整数 `1`–`5` |
| `services/question_generation_llm.py:258` | 三档，且**硬编码兜底 `"medium"`** |

选了**三档字符串**，理由是 `QuestionDifficulty` 是**全仓唯一被持久化的**难度枚举，
且出题流水线已经在用同一套值。若这里另立 1–5，将来「练习问答」与「OJ 编程题」
在同一页按难度混排或统一筛选时，立刻要写一层转换表 —— 那是纯负债。

**代价**：与 `knowledge.py` 的 1–5 口径不一致。这条不一致**不隐藏**，
在 `metadata.py` 的 docstring 里写明了两者的冲突与取舍，
并留了 `test_numeric_1_to_5_is_rejected` 把「本域不接受 1–5」钉住。

### 9.3 一处刻意的不对称：非法值抛错，不兜底

`question_generation_llm.py:258` 的策略是 `result.get("difficulty") or "medium"`
—— **非法值静默兜底**。本域**故意反向**：

| | 输入方 | 策略 | 理由 |
|---|---|---|---|
| `question_generation_llm` | **LLM 输出解析** | 非法 → `medium` | 模型偶尔给脏值是**预期内**的，兜底才保得住流水线 |
| `domain/oj/problems` | **教师显式填写** | 非法 → **抛 `ValueError`** | 填错必须让他知道。静默兜底会产生「我明明写了 hard，怎么存成了 medium」这类**无法排查**的问题 |

`None` 与空串**归默认值**（「没填」是合法输入），只有**填错**才抛。
这条不对称在 `metadata.py` 的 docstring 与服务层 `_validated_difficulty` 的注释里各写了一遍，
并留 `test_invalid_values_raise_not_fallback` 防「顺手改成兜底」。

### 9.4 服务层适配：两件域层不该管的事

规则在域层，但有两件事**必须留在 service**：

1. **异常翻译**：域层不 import `app.core.exceptions`（与 `domain/oj` 其余部分的边界一致），
   所以「抛什么异常」是调用方的责任。`_validated_difficulty` / `_validated_tags`
   把 `ValueError` 翻成 `reject_validation_failed`（→ 422）。翻译**放在单点**，
   避免每个调用处各写一份 `try`。
2. **「什么时候校验」**：create 恒校验；update 是 **PATCH 语义** ——
   `None` = 「别动这一列」，`[]` = 「清空标签」。这个区分是**业务策略**，域层看不到。

第 2 条是本 PR 最容易写错的地方：若把 `None` 当成「设成默认值」，
**教师改个标题就会把难度重置回 medium、标签被清空**。
`test_omitted_fields_are_untouched` 专门守它，`test_empty_tags_clears_them` 守反面。

### 9.5 为什么不用 PG 原生 enum

`experiment_runs.outcome` 那个原生 enum 已经在 PR-01 制造过一次静默回填坑
（见 PR-01 迁移的说明）。难度取值将来若要扩档（如加 `challenge`），
原生 enum 需要 `ALTER TYPE` 且**不能在事务里回滚**。
本题这种**描述性、非判定性**字段用「`String(16)` + 域层校验」更划算 ——
与 PR-01 给 `run_state` / `run_type` 选 `String(32)` 是同一取向。

`tags` 则与既有的 `knowledge_node_ids` 同构（`sa.JSON(), nullable=True`）。
写成 `String` 会在 PG 上退化成「逗号拼接字符串」，届时筛标签只能 `LIKE '%x%'`，
既无索引又会把 `db` 误匹配到 `dbms`。`test_uses_json_column_not_text_for_tags` 守住这条。

### 9.6 回填：一个刻意的「不聪明」

`difficulty` 带 `server_default='medium'`，**全部历史行一次性落到 medium**。
这是**保守默认而非推导值**：仓库里没有任何信号能推断既有题目的难度
（没有 pass 率统计、没有用时分布、没有人工标注）。
按标题长度之类的代理指标猜一个「看起来更聪明」的值，一旦猜错会**污染题库筛选**，
且事后**无法回溯哪些是猜的**。

`tags` 回填为空。**迁移前插入的历史行**其 JSON 列是 SQL `NULL`（不是 `[]`），
所以序列化层用 `list(d.tags or [])` 兜住 —— 前端不该为此多写一处判空。
`test_historic_null_tags_serialize_as_empty_list` 直接构造该形态验证兜底生效。

台账口径：`applied_rows` 记的是**加列前该表已有行数**，在 `add_column` **之前**取。
放在之后数 `difficulty='medium'` 会把加列后新插入的行也算进来，数字随执行时机漂移。

### 9.7 迁移 ↔ 域层的字面量重复，及其守卫

迁移文件**刻意不 import 应用代码**（alembic 版本可能与应用版本错开部署），
于是 `'medium'` 这个默认值在两边各写了一份。这属于必要的重复，
但**必须有人看着** —— `TestMigrationContract::test_default_difficulty_literal_matches_domain`
用 AST 读迁移里的 `_DEFAULT_DIFFICULTY` 与域层比对，只改一边时这里会红，
而不是等线上题库筛选出现一批「难度对不上」的题才发现。

同组还守 `down_revision` 指向（防开出第二个 head）与 BOM。

### 9.8 原方案里的一处更正

我此前在实施台账里把 PR-09 描述成「`difficulty` + `tags` + 迁移」，
**漏了「选几档」本身就是个需要拍板的设计决定**，把它当成了纯粹的机械补列。
实际上它是本 PR 最需要论证的部分（见 §9.2 / §9.3）。
