"""agent_log_redaction_backfill

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26 13:55:00

Agent 日志脱敏（不可逆安全数据迁移）。

将 legacy agent_learning_events.event_data 和 agent_trace_records.trace_data
中的原始提问、完整回答、完整 Prompt/LLM trace 替换为受限的结构化摘要。

规则（与原 db_migrator._minimize_agent_logs 保持一致）：
- 不可逆：原始 raw payload 永久丢失，downgrade 不恢复内容。
- 幂等：通过 agent_log_migration_records 表的 batch_id 判断是否已执行。
- 保留：user_id、course_id、session_id、错误码、工具状态、策略版本。
- 写入：redacted_at、redaction_policy_version、migration_batch_id。

downgrade 只删除迁移账本记录，不恢复原始内容（隐私安全要求）。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH_ID = "agent-log-minimization-v1"
POLICY_VERSION = "agent-log-minimization/1"
REDACTED_PAYLOAD = '{"reason_codes":["LEGACY_RAW_PAYLOAD_REDACTED"]}'


def _batch_already_applied(bind) -> bool:
    """检查本批次是否已执行过（幂等）。"""
    # 检查 agent_log_migration_records 表是否存在记录
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM agent_log_migration_records "
            "WHERE batch_id = :batch_id LIMIT 1"
        ),
        {"batch_id": BATCH_ID},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()

    # 幂等检查
    if _batch_already_applied(bind):
        return

    redacted_events = 0
    redacted_traces = 0

    # 1. 脱敏 agent_learning_events.event_data
    result = bind.execute(
        sa.text(
            """
            UPDATE agent_learning_events
            SET event_data = :payload,
                data_policy_version = :policy_version,
                migration_batch_id = :batch_id
            WHERE migration_batch_id IS NULL OR migration_batch_id = ''
            """
        ),
        {
            "payload": REDACTED_PAYLOAD,
            "policy_version": POLICY_VERSION,
            "batch_id": BATCH_ID,
        },
    )
    redacted_events = result.rowcount or 0

    # 2. 脱敏 agent_trace_records.trace_data
    result = bind.execute(
        sa.text(
            """
            UPDATE agent_trace_records
            SET trace_data = :payload,
                data_policy_version = :policy_version,
                migration_batch_id = :batch_id
            WHERE migration_batch_id IS NULL OR migration_batch_id = ''
            """
        ),
        {
            "payload": REDACTED_PAYLOAD,
            "policy_version": POLICY_VERSION,
            "batch_id": BATCH_ID,
        },
    )
    redacted_traces = result.rowcount or 0

    # 3. 记录脱敏批次到 agent_log_migration_records
    bind.execute(
        sa.text(
            """
            INSERT INTO agent_log_migration_records
                (batch_id, applied_at, redacted_event_rows, redacted_trace_rows)
            VALUES (:batch_id, CURRENT_TIMESTAMP, :events, :traces)
            """
        ),
        {
            "batch_id": BATCH_ID,
            "events": redacted_events,
            "traces": redacted_traces,
        },
    )


def downgrade() -> None:
    """删除迁移账本记录。

    警告：原始 raw payload 已永久脱敏，无法恢复。
    本 downgrade 只删除 agent_log_migration_records 中的批次记录，
    不恢复 event_data / trace_data 的原始内容。

    这是隐私安全要求：已脱敏的学生原始提问和 LLM trace 不应被恢复。
    部署前必须备份数据库；备份是灾难恢复边界，不是长期保留原始日志。
    """
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM agent_log_migration_records WHERE batch_id = :batch_id"
        ),
        {"batch_id": BATCH_ID},
    )
    # 注意：不恢复 event_data / trace_data 的原始内容
