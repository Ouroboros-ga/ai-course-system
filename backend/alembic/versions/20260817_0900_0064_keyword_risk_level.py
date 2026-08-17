"""Add risk_level to safety keyword configs and backfill default cyber risks.

Revision ID: 0064
Revises: 0063

2026-08-17：管理员新增/配置网安关键词时可设置风险等级（high/medium），
修复"新增词默认中风险 + 教学语境放行"导致拦截预期失效的问题。
``risk_level`` 默认 medium；回填默认 10 个 cyber 词的历史风险（与
``safety_guard_service.KEYWORD_RISK`` 一致）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

# 与 safety_guard_service.KEYWORD_RISK 同步的默认网安词风险回填
_DEFAULT_CYBER_RISKS = {
    "ctf": "medium",
    "漏洞利用": "high",
    "提权": "high",
    "端口扫描": "medium",
    "恶意代码": "high",
    "sql注入": "medium",
    "xss": "medium",
    "缓冲区溢出": "high",
    "逆向工程": "medium",
    "密码破解": "high",
}


def _column_exists(bind, table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "safety_keyword_configs", "risk_level"):
        op.add_column(
            "safety_keyword_configs",
            sa.Column("risk_level", sa.String(length=10), nullable=False, server_default="medium"),
        )
    # 回填默认 cyber 词风险（幂等：仅更新仍为 medium 的默认词）
    for keyword, risk in _DEFAULT_CYBER_RISKS.items():
        op.execute(
            sa.text(
                "UPDATE safety_keyword_configs SET risk_level = :risk "
                "WHERE keyword = :keyword AND category = 'CYBER'"
            ).bindparams(risk=risk, keyword=keyword)
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, "safety_keyword_configs", "risk_level"):
        op.drop_column("safety_keyword_configs", "risk_level")
