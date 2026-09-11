"""Conversation Domain：conversation_messages 增加 discipline_references（学科参考快照）。

Revision ID: conv20260911v1
Revises: oj20260911v2
Create Date: 2026-09-11
Batch: conversation_discipline_references_v1

背景
----
R14「学科参考」是随教学回答一起透出的补充参考（``is_supplementary=True``），
与 ``citations``（课程证据闭包）严格分离。此前它只存在于
``POST /teaching-agent/respond`` 的响应体里，既没有落库、回放接口也不返回，
于是刷新或重新进入课程后整块「学科参考」消失。线上实测已复现：同一次会话
12 条助手消息、依据区 12 块、学科参考 0 块；刷新前刚发出的回答则有学科参考。

本次把响应体里的这份展示快照原样存下来，使回放结果与实时回答一致。列名与
``ConversationMessage.discipline_references`` 保持一致。

取值口径
--------
按响应体原样存 ``sa.JSON()``，不做二次投影或裁剪：回放需要 ``reference_id`` /
``release_id`` / ``result_type`` / ``source_kind`` / ``source_url`` /
``matched_by`` / ``chunk_id`` / ``authority_label`` 等字段，少任何一个都会让
「查看原文」入口或来源标签在回放时失效。

它**不进入引用闭包**：``citations`` 仍由 ``validate_response`` 限定在
``retrieved_evidence`` 的 ``evidence_id`` 白名单内，本列不参与该判定，也不喂给
掌握度、图谱或任何 ``LearningEvidence`` 写入。它落在 Conversation Domain，
沿用 ``data_policy_version = "conversation-domain/1"`` 与 ``retention_until``
保留窗口（见 ``app/models/conversation_model.py`` 顶部说明）。

历史行
------
``nullable=True`` 且**不回填**。历史行当时确实没有这份快照，统一写 ``[]``
等同于伪造「有过零条参考」的事实；留 ``NULL`` 由读取侧 ``or []`` 兜底，
语义更诚实。加列后新行由模型 ``default_factory=list`` 写入。

幂等
----
加列带 ``_has_column`` 守卫，重复执行安全。

回退
----
``downgrade`` 删除该列。它是纯展示快照，删掉后回放退回「学科参考不显示」的
旧行为，不影响既有读写路径、掌握度或图谱数据，因此回退无损。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "conv20260911v1"
down_revision = "oj20260911v2"
branch_labels = None
depends_on = None

BATCH_ID = "conversation_discipline_references_v1"
BATCH_NAME = "Conversation Domain：conversation_messages 增加 discipline_references（学科参考快照）"
BATCH_ROLLBACK_NOTES = (
    "Drops conversation_messages.discipline_references. The column only holds a "
    "display snapshot of the R14 supplementary '学科参考' block that the "
    "teaching-agent response already carries; it never joins the citations "
    "evidence closure nor feeds mastery / graph writes, so the downgrade only "
    "restores the previous behaviour of an empty 学科参考 block after replay."
)

_TABLE = "conversation_messages"
_COLUMN = "discipline_references"


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


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
    # 纯加列，没有回填：历史行的 NULL 由读取侧 ``or []`` 兜底，故 applied_rows=0。
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.JSON(), nullable=True),
        )
    _record_batch("applied")


def downgrade() -> None:
    """删列。

    守卫而非 ``try/except pass``：盲吞异常会掩盖真正的方言/权限错误，而守卫能
    明确表达「本来就没有就跳过」。SQLite 不支持原生 DROP COLUMN，走 batch 模式；
    PG 同语法兼容。
    """
    if _has_column(_TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
    _record_batch("rolled_back")
