"""OJ PR-07：Activity 域 —— experiment_activities / _problems / _scopes 三表
+ experiment_attempts.run 的 activity_id 归属列。

Revision ID: oj20260911v3
Revises: oj20260911v2
Create Date: 2026-09-11
Batch: oj_activity_domain_v1

背景
----
题库 / 判题 / 诊断链路已在跑，缺的是「把若干题组织成一次作业 / 比赛」的层。
真缺口实测：`homework` / `contest` / `scoreboard` 在 `backend/app` 零命中
（`docs/architecture/oj-current-state.md`）。

本迁移只建结构，**不带行为**：admin API 是 PR-08，学生页是 PR-12，
scoreboard 是 PR-11/15。行为分批落地是刻意的 —— 表结构与行为解耦后，
后续 PR 不需要再动 schema。

为什么是三张表而不是 v2 方案的四张
----------------------------------
v2 画了 `oj_activities` / `oj_activity_problems` / `oj_activity_scopes` /
`oj_activity_members` 四张。`members`（报名制花名册）只有 contest 报名制需要，
而本期**只实现 homework**（经拍板），不建没有写入者的表 —— 空表比缺表更糟：
它会让人以为报名制已经能用。contest 落地时再加，届时是纯新增迁移。

activity_id 为什么不加 FK 约束
------------------------------
`experiment_attempts.activity_id` / `experiment_runs.activity_id` 用
**字符串业务键**（`act_<hex>`），与同表 `experiment_id`（字符串、无 FK）的
既有约定一致。加硬 FK 会把 Activity 的删除语义绑成 RESTRICT/ CASCADE
二选一，而「活动归档后 attempt 仍在」的语义更接近**弱引用 + 应用层校验**。
代价是没有 DB 级完整性兜底 —— 由 service 的写入点校验补上，
并由 `TestActivityForeignKeySemantics` 钉住。

冗余存储 `experiment_runs.activity_id`
--------------------------------------
attempt 上已有 activity_id，run 上再存一份看似违反 DRY。但「按活动拉全部
run」是 scoreboard / 报表的高频路径，join attempt 会让每张榜单多一次
全表关联；而 run 的 activity_id 在创建时从 attempt 拷贝、attempt 的
activity_id **创建后不可变**（活动归属不随时间漂移），冗余是安全的。
不一致的可能性由 service 单点写入排除。

枚举列不用 PG 原生 enum
-----------------------
type / status / scoring_mode / ranking_mode / scope_type 全部 `String` +
域层值域约束（`domain/oj/activity/policies.py`）。理由与 PR-01 给
`run_state`/`run_type`、PR-09 给 `difficulty` 选字符串相同：
`outcome` 的原生 enum 已制造过一次静默回填坑，且扩值需 `ALTER TYPE`
不可在事务里回滚。

回填说明
--------
全部是**新增结构**，无历史行需要回填：`activity_id` 可空（NULL = 自由练习），
三张新表从空开始。`applied_rows` 因此恒为 0，记入台账仅为保持批次记录完整。

幂等
----
建表 / 加列 / 建索引均带守卫。SQLite 走 batch 模式，PG 同语法兼容。

回退
----
删两列、删三表。新表只被本域读写（本 PR 无任何既有逻辑引用它们），
attempt/run 的 `activity_id` 全为 NULL，回退无损。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "oj20260911v3"
down_revision = "conv20260911v1"
branch_labels = None
depends_on = None

BATCH_ID = "oj_activity_domain_v1"
BATCH_NAME = "OJ PR-07：Activity 域三表 + attempt/run 归属列"
BATCH_ROLLBACK_NOTES = (
    "Drops experiment_activities / experiment_activity_problems / "
    "experiment_activity_scopes and the nullable activity_id columns on "
    "experiment_attempts / experiment_runs. Every added column is nullable "
    "with no backfill (NULL = free practice), and the three tables are "
    "written only by this domain, so the downgrade loses no information."
)

_TABLES = ("experiment_activity_problems", "experiment_activity_scopes", "experiment_activities")
_ACTIVITIES = "experiment_activities"
_PROBLEMS = "experiment_activity_problems"
_SCOPES = "experiment_activity_scopes"
_ATTEMPTS = "experiment_attempts"
_RUNS = "experiment_runs"


def _has_table(table: str) -> bool:
    return table in set(sa.inspect(op.get_bind()).get_table_names())


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


def _create_activities() -> None:
    if _has_table(_ACTIVITIES):
        return
    op.create_table(
        _ACTIVITIES,
        sa.Column("id", sa.Integer(), primary_key=True),
        # 业务键，attempt/run 经它引用（与其余 *_id 字符串键同约定）
        sa.Column("activity_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False, server_default="homework"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description_md", sa.String(length=20000), nullable=True),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("allow_late_submit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("freeze_at", sa.DateTime(), nullable=True),
        sa.Column("scoring_mode", sa.String(length=32), nullable=False, server_default="sum"),
        sa.Column("ranking_mode", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("max_submissions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.UniqueConstraint("activity_id", name="uq_experiment_activities_activity_id"),
    )
    if not _has_index(_ACTIVITIES, "ix_experiment_activities_course_id"):
        op.create_index("ix_experiment_activities_course_id", _ACTIVITIES, ["course_id"])
    if not _has_index(_ACTIVITIES, "ix_experiment_activities_type"):
        op.create_index("ix_experiment_activities_type", _ACTIVITIES, ["type"])
    if not _has_index(_ACTIVITIES, "ix_experiment_activities_status"):
        op.create_index("ix_experiment_activities_status", _ACTIVITIES, ["status"])


def _create_problems() -> None:
    if _has_table(_PROBLEMS):
        return
    op.create_table(
        _PROBLEMS,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activity_id", sa.String(length=64), nullable=False),
        sa.Column("problem_definition_id", sa.String(length=64), nullable=False),
        sa.Column("problem_version_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 同一活动内 (definition, ordinal) 唯一：防同一题被挂两次、
        # 防两题抢同一位次（位次决定算分顺序，冲突会破坏 deterministic）。
        sa.UniqueConstraint(
            "activity_id", "problem_definition_id",
            name="uq_experiment_activity_problems_def",
        ),
        sa.UniqueConstraint(
            "activity_id", "ordinal",
            name="uq_experiment_activity_problems_ordinal",
        ),
    )
    if not _has_index(_PROBLEMS, "ix_experiment_activity_problems_activity_id"):
        op.create_index(
            "ix_experiment_activity_problems_activity_id", _PROBLEMS, ["activity_id"]
        )
    if not _has_index(_PROBLEMS, "ix_experiment_activity_problems_version_id"):
        op.create_index(
            "ix_experiment_activity_problems_version_id",
            _PROBLEMS, ["problem_version_id"],
        )


def _create_scopes() -> None:
    if _has_table(_SCOPES):
        return
    op.create_table(
        _SCOPES,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activity_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "activity_id", "scope_type", "scope_id",
            name="uq_experiment_activity_scope",
        ),
    )
    if not _has_index(_SCOPES, "ix_experiment_activity_scopes_activity_id"):
        op.create_index("ix_experiment_activity_scopes_activity_id", _SCOPES, ["activity_id"])


def _add_activity_columns() -> None:
    for table in (_ATTEMPTS, _RUNS):
        if not _has_column(table, "activity_id"):
            op.add_column(
                table,
                sa.Column("activity_id", sa.String(length=64), nullable=True),
            )
        index = f"ix_{table}_activity_id"
        if not _has_index(table, index):
            op.create_index(index, table, ["activity_id"])


def upgrade() -> None:
    # 先建父表（activities），problems/scopes 的语义才成立。
    _create_activities()
    _create_problems()
    _create_scopes()
    _add_activity_columns()
    _record_batch("applied", applied_rows=0)


def downgrade() -> None:
    """删归属列与三表。

    守卫而非 ``try/except pass``：与 PR-01/PR-09 迁移同一取向 ——
    盲吞异常会掩盖真正的方言/权限错误，守卫能明确表达「本来就没有就跳过」。
    删表顺序与建表相反（先子后父），SQLite 走 batch 模式。
    """
    for table in (_RUNS, _ATTEMPTS):
        index = f"ix_{table}_activity_id"
        if _has_index(table, index):
            with op.batch_alter_table(table) as batch:
                batch.drop_index(index)
        if _has_column(table, "activity_id"):
            with op.batch_alter_table(table) as batch:
                batch.drop_column("activity_id")

    for table in (_SCOPES, _PROBLEMS, _ACTIVITIES):
        if _has_table(table):
            op.drop_table(table)

    _record_batch("rolled_back")
