"""Add platform safety keyword configs table and seed defaults.

Revision ID: 0063
Revises: 0062

2026-08-16：新增平台级安全屏蔽词配置表 ``safety_keyword_configs``，
管理员可通过 ``/api/v1/admin/safety-keywords`` 增删改/启禁用。

seed 数据与 ``safety_policy_model.DEFAULT_KEYWORDS_BY_CATEGORY`` 保持一致
（cyber 10 个 / political_high_risk 21 个 / political_topic 5 个）；
表为空或不可用时，安全评估引擎会回退到同一默认列表，因此 seed 失败不阻塞。
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None

# 与 app/models/safety_policy_model.py 的 DEFAULT_KEYWORDS_BY_CATEGORY 同步。
# 注意：本项目 SQLModel 枚举统一按成员 name（大写）存储（PostgreSQL 原生枚举，
# 与 coursetype 同约定，见 0051 迁移注释），因此 seed 用大写 name。
_SEED_KEYWORDS = [
    ("ctf", "CYBER"),
    ("漏洞利用", "CYBER"),
    ("提权", "CYBER"),
    ("端口扫描", "CYBER"),
    ("恶意代码", "CYBER"),
    ("sql注入", "CYBER"),
    ("xss", "CYBER"),
    ("缓冲区溢出", "CYBER"),
    ("逆向工程", "CYBER"),
    ("密码破解", "CYBER"),
    ("分裂国家", "POLITICAL_HIGH_RISK"),
    ("颠覆国家政权", "POLITICAL_HIGH_RISK"),
    ("台独", "POLITICAL_HIGH_RISK"),
    ("藏独", "POLITICAL_HIGH_RISK"),
    ("疆独", "POLITICAL_HIGH_RISK"),
    ("港独", "POLITICAL_HIGH_RISK"),
    ("叛国", "POLITICAL_HIGH_RISK"),
    ("破坏国家统一", "POLITICAL_HIGH_RISK"),
    ("国家主权", "POLITICAL_HIGH_RISK"),
    ("领土完整", "POLITICAL_HIGH_RISK"),
    ("国家利益", "POLITICAL_HIGH_RISK"),
    ("危害国家安全", "POLITICAL_HIGH_RISK"),
    ("泄露国家秘密", "POLITICAL_HIGH_RISK"),
    ("非法政治思想", "POLITICAL_HIGH_RISK"),
    ("法轮功", "POLITICAL_HIGH_RISK"),
    ("邪教", "POLITICAL_HIGH_RISK"),
    ("邪教组织", "POLITICAL_HIGH_RISK"),
    ("恐怖主义", "POLITICAL_HIGH_RISK"),
    ("恐怖袭击", "POLITICAL_HIGH_RISK"),
    ("极端主义", "POLITICAL_HIGH_RISK"),
    ("民族分裂主义", "POLITICAL_HIGH_RISK"),
    ("政治人物", "POLITICAL_TOPIC"),
    ("政治事件", "POLITICAL_TOPIC"),
    ("政治运动", "POLITICAL_TOPIC"),
    ("政治谣言", "POLITICAL_TOPIC"),
    ("政治斗争", "POLITICAL_TOPIC"),
]


def _table_exists(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "safety_keyword_configs"):
        op.create_table(
            "safety_keyword_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("keyword", sa.String(length=100), nullable=False),
            # PostgreSQL 原生枚举 keywordcategory（成员名大写，与模型 create_all 一致）；
            # SQLite 自动退化为 VARCHAR + CHECK。
            sa.Column(
                "category",
                sa.Enum("CYBER", "POLITICAL_HIGH_RISK", "POLITICAL_TOPIC", name="keywordcategory"),
                nullable=False,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("keyword", "category", name="uq_safety_keyword_category"),
        )
        op.create_index(
            "ix_safety_keyword_configs_keyword", "safety_keyword_configs", ["keyword"]
        )
        op.create_index(
            "ix_safety_keyword_configs_category", "safety_keyword_configs", ["category"]
        )
    # seed 默认屏蔽词（幂等：已有同 key 不重复插入）
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT keyword || '|' || category FROM safety_keyword_configs")
        ).fetchall()
    }
    rows = [
        {
            "keyword": keyword,
            "category": category,
            "enabled": True,
            "description": "",
            "created_by": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        for keyword, category in _SEED_KEYWORDS
        if f"{keyword}|{category}" not in existing
    ]
    if rows:
        op.bulk_insert(
            sa.table(
                "safety_keyword_configs",
                sa.column("keyword", sa.String),
                sa.column("category", sa.String),
                sa.column("enabled", sa.Boolean),
                sa.column("description", sa.String),
                sa.column("created_by", sa.Integer),
                sa.column("created_at", sa.DateTime),
                sa.column("updated_at", sa.DateTime),
            ),
            rows,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "safety_keyword_configs"):
        op.drop_table("safety_keyword_configs")
