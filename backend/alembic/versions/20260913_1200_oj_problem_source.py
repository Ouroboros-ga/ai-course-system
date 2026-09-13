"""OJ B1：experiment_definitions 增加 source / year（题目来源与年份）。

Revision ID: oj20260913v4
Revises: oj20260911v3
Create Date: 2026-09-13
Batch: oj_problem_source_v1

背景
----
题库列表需要按「所属题库（来源）」筛选、并在标签列上按年份着色
（`docs/phase1/2026-09-13_OJ题目列表与详情页界面复刻_接口规范与前端改动.md` 的 B1）。
PR-09 已经给了 `difficulty` / `tags` 两个**描述性**字段，但 `tags` 是自由文本，
「来源」与「年份」被教师随手混在里面，既不能按来源聚合，也不能按年份排序。

为什么不新增 `algorithm_tags` 列
--------------------------------
B1 的初稿把「算法标签」与 `tags` 拆成两列。落地时**否掉了**：
`tags` 本身就是教师填的算法标签（`贪心` / `动态规划` / `最短路`），
再加一列等于给同一个概念造两处真相 —— 教师会不知道填哪个，前端也会不知道该读哪个。
真正缺失的是「来源」与「年份」这两个**有结构的**字段，只补它们。

取值口径
--------
- `source`：``String(64)``，可空，**不做大小写归并** —— `ICPC` / `Codeforces`
  是专名，强行转小写会破坏展示；筛选比较由域层按 ``casefold`` 处理。
- `year`：``Integer``，可空，域层限定 1970–2100，越界抛错不兜底。

为什么都用可空列而不是给默认值
------------------------------
「自编题」本来就没有来源与年份。若像 `difficulty` 那样给 server_default，
就必须凭空选一个默认来源（`self`？`custom`？），而那个值会成为**无法与
真实填写区分**的数据 —— 教师没填和教师填了 `custom` 在库里长得一样。
可空 + 前端不显示空值，是这类「本来就可能没有」的字段的正确形态。

幂等
----
加列 / 建索引均带 `_has_column` / `_has_index` 守卫。重复执行安全。

回退
----
`downgrade` 删索引与两列。两列都是**新增的描述性元数据**；回退前若已有教师
填写的来源/年份，会随列一起丢失 —— 这一点写进 `BATCH_ROLLBACK_NOTES`，
因为它是本迁移与 PR-09 那条「回退无损」的**唯一区别**。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "oj20260913v4"
down_revision = "oj20260911v3"
branch_labels = None
depends_on = None

BATCH_ID = "oj_problem_source_v1"
BATCH_NAME = "OJ B1：experiment_definitions 增加来源与年份（source / year）"
BATCH_ROLLBACK_NOTES = (
    "Drops experiment_definitions.source and experiment_definitions.year. "
    "Unlike the PR-09 metadata migration, this one is NOT loss-free once teachers "
    "have filled the fields: any authored source/year values are discarded. "
    "There is no derived fallback because both columns are nullable by design "
    "(self-authored problems legitimately have neither)."
)

_TABLE = "experiment_definitions"
_INDEX_SOURCE = "ix_experiment_definitions_source"
_INDEX_YEAR = "ix_experiment_definitions_year"


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
    # applied_rows 记「加列前已有多少行」—— 两列都可空且不回填，
    # 这个数字表达的是「有多少行需要教师后续补来源/年份」，放在加列后数会失真。
    pre_existing = 0
    if not _has_column(_TABLE, "source"):
        pre_existing = int(
            op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar() or 0
        )

    if not _has_column(_TABLE, "source"):
        op.add_column(
            _TABLE,
            sa.Column("source", sa.String(length=64), nullable=True),
        )
    if not _has_column(_TABLE, "year"):
        op.add_column(
            _TABLE,
            sa.Column("year", sa.Integer(), nullable=True),
        )

    if not _has_index(_TABLE, _INDEX_SOURCE):
        op.create_index(op.f(_INDEX_SOURCE), _TABLE, ["source"], unique=False)
    if not _has_index(_TABLE, _INDEX_YEAR):
        op.create_index(op.f(_INDEX_YEAR), _TABLE, ["year"], unique=False)

    _record_batch("applied", applied_rows=pre_existing)


def downgrade() -> None:
    """删索引与两列。

    守卫而非 ``try/except pass``：与 PR-01 / PR-09 迁移同一取向 —— 盲吞异常会掩盖
    真正的方言/权限错误，而守卫能明确表达「本来就没有就跳过」。
    SQLite 不支持原生 DROP COLUMN，走 batch 模式；PG 同语法兼容。
    """
    for index in (_INDEX_YEAR, _INDEX_SOURCE):
        if _has_index(_TABLE, index):
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_index(index)
    for column in ("year", "source"):
        if _has_column(_TABLE, column):
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(column)
    _record_batch("rolled_back")
