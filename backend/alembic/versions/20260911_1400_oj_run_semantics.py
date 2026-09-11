"""OJ PR-01：experiment_runs 增加 run_state / run_type（状态与判定分离）。

Revision ID: oj20260911v1
Revises: dk20260909v5
Create Date: 2026-09-11
Batch: oj_run_semantics_v1

背景
----
``RunOutcome`` 把两种概念塞进同一个枚举：``PENDING`` 是**运行状态**，
``ACCEPTED`` / ``WRONG_ANSWER`` / … 是**判定结果**。这在「一次 run 一个结论」时
能凑合，但 Activity / Scoreboard 一上来就会卡住 —— ICPC 要按判定算罚时、
Homework 要按分数求和，两者都需要表达「还在跑」**且**「已经跑出某个结论」。

本次迁移只做 schema 侧的两件事，**不改任何业务行为、不改任何 API 响应**
（``_serialize_run`` 逐字段显式拼装，未包含新列）：

- ``run_state``：运行状态，值域 ``queued/running/finished/cancelled/system_error``；
- ``run_type``：运行语义，值域 ``submission/test/reference_preview``。

``RunOutcome`` 成员一个不改，继续作为兼容的聚合结果枚举。

回填说明（关键）
----------------
``outcome`` 是 **PG 原生 enum**（类型名 ``runoutcome``），SQLAlchemy 默认存
**成员名**（大写），不是 ``.value``（小写）。因此回填必须比较大写：
写 ``outcome = 'pending'`` 会一行都匹配不上，**静默把全部历史 run 留成 queued**。
这里统一用 ``CAST(outcome AS TEXT)`` 规避方言与 enum 强制转换的差异。

- ``PENDING`` + 有 ``cancel_requested_at`` → ``cancelled``
- ``PENDING`` → ``queued``
- ``INTERNAL_ERROR`` / ``SANDBOX_UNAVAILABLE`` → ``system_error``
- 其余 → ``finished``

``run_type`` 全部回填 ``submission``：参考解预览**不创建 ExperimentRun 行**
（``experiment_service.py`` 只在 :840 创建 run），因此历史行全部是学生提交，
这是精确回填而非近似。

幂等
----
加列 / 建索引 / 回填均带守卫（``_has_column`` / ``_has_index`` / ``WHERE run_state =
'queued'``），重复执行安全。回填的 ``WHERE`` 同时保护编排层以后显式写入的
``running`` 不被覆盖。

回退
----
``downgrade`` 删两列与两个索引。删列即回到「只有 outcome」的旧语义；
本迁移没有回填任何不可重建的信息（``run_state`` 完全由 ``outcome`` +
``cancel_requested_at`` 推导，``run_type`` 是常量默认值），因此回退无损。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "oj20260911v1"
down_revision = "dk20260909v5"
branch_labels = None
depends_on = None

BATCH_ID = "oj_run_semantics_v1"
BATCH_NAME = "OJ：experiment_runs 状态与判定分离（run_state / run_type）"
BATCH_ROLLBACK_NOTES = (
    "Drops experiment_runs.run_state and experiment_runs.run_type. "
    "run_state is fully derivable from outcome + cancel_requested_at, and "
    "run_type defaults to 'submission' for every historical row, so the "
    "downgrade loses no information."
)

_TABLE = "experiment_runs"

#: 旧 RunOutcome 成员名 → 新 RunState 值。键是**大写成员名**（DB 实际存储形式）。
_BACKFILL_SQL = """
UPDATE experiment_runs
   SET run_state = CASE
         WHEN CAST(outcome AS TEXT) = 'PENDING' AND cancel_requested_at IS NOT NULL
              THEN 'cancelled'
         WHEN CAST(outcome AS TEXT) = 'PENDING'
              THEN 'queued'
         WHEN CAST(outcome AS TEXT) IN ('INTERNAL_ERROR', 'SANDBOX_UNAVAILABLE')
              THEN 'system_error'
         ELSE 'finished'
       END
 WHERE run_state = 'queued'
"""


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    return index in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _record_batch(status: str, applied_rows: int = 0) -> None:
    """Upsert the business migration ledger inside the Alembic transaction."""
    bind = op.get_bind()
    if "schema_migration_records" not in set(sa.inspect(bind).get_table_names()):
        return
    existing = bind.execute(
        sa.text("SELECT id FROM schema_migration_records WHERE batch_id = :batch_id"),
        {"batch_id": BATCH_ID},
    ).first()
    values = {
        "batch_id": BATCH_ID,
        "name": BATCH_NAME,
        "status": status,
        "rollback_notes": BATCH_ROLLBACK_NOTES,
        "preflight_ok": True,
        "applied_rows": applied_rows,
    }
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO schema_migration_records "
                "(batch_id, name, applied_at, status, rollback_notes, "
                "preflight_ok, applied_rows, created_at) "
                "VALUES (:batch_id, :name, CURRENT_TIMESTAMP, :status, "
                ":rollback_notes, :preflight_ok, :applied_rows, CURRENT_TIMESTAMP)"
            ),
            values,
        )
        return
    bind.execute(
        sa.text(
            "UPDATE schema_migration_records "
            "SET name = :name, applied_at = CURRENT_TIMESTAMP, status = :status, "
            "rollback_notes = :rollback_notes, preflight_ok = :preflight_ok, "
            "applied_rows = :applied_rows "
            "WHERE batch_id = :batch_id"
        ),
        values,
    )


def upgrade() -> None:
    if not _has_column(_TABLE, "run_state"):
        op.add_column(
            _TABLE,
            sa.Column(
                "run_state",
                sa.String(length=32),
                nullable=False,
                server_default="queued",
            ),
        )
    if not _has_column(_TABLE, "run_type"):
        op.add_column(
            _TABLE,
            sa.Column(
                "run_type",
                sa.String(length=32),
                nullable=False,
                server_default="submission",
            ),
        )

    if not _has_index(_TABLE, "ix_experiment_runs_run_state"):
        op.create_index(
            op.f("ix_experiment_runs_run_state"), _TABLE, ["run_state"], unique=False
        )
    if not _has_index(_TABLE, "ix_experiment_runs_run_type"):
        op.create_index(
            op.f("ix_experiment_runs_run_type"), _TABLE, ["run_type"], unique=False
        )

    result = op.get_bind().execute(sa.text(_BACKFILL_SQL))
    _record_batch("applied", applied_rows=int(result.rowcount or 0))


def downgrade() -> None:
    """删索引与两列。

    用 ``_has_index`` / ``_has_column`` 守卫而非 ``try/except pass``：
    盲吞异常会掩盖真正的方言/权限错误，而守卫能明确表达「本来就没有就跳过」。
    SQLite 不支持原生 DROP COLUMN，走 batch 模式；PG 同语法兼容。
    """
    for index in ("ix_experiment_runs_run_type", "ix_experiment_runs_run_state"):
        if _has_index(_TABLE, index):
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_index(index)
    for column in ("run_type", "run_state"):
        if _has_column(_TABLE, column):
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(column)
    _record_batch("rolled_back")
