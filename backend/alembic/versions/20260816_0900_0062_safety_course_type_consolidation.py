"""Consolidate course safety types: merge cyber/CTF, add ideological.

Revision ID: 0062
Revises: 0061

2026-08-16：课程安全类型从四种合并为三种：
- ``BASIC``（基础教学）合并进 ``PROFESSIONAL``（专业课程）；
- ``CTF`` 合并进 ``CYBERSECURITY``（网络安全课程，审查逻辑统一）；
- 新增 ``IDEOLOGICAL``（思政类课程）。

PostgreSQL 侧需要给原生 ``coursetype`` 枚举追加 ``IDEOLOGICAL`` label
（沿用 0051/0052 的 autocommit 模式）；随后把存量行归一化为新值。
SQLite 无原生枚举，直接归一化行值即可。
"""
from __future__ import annotations

from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # PostgreSQL 原生枚举：任何使用新 label 的语句必须在新 label 提交之后
        # 才能执行，因此用 autocommit block 先追加 IDEOLOGICAL。
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE coursetype ADD VALUE IF NOT EXISTS 'IDEOLOGICAL'"
            )

    # 存量数据归一化：旧值 -> 新值（PostgreSQL 按枚举 label，SQLite 按字符串）。
    op.execute(
        "UPDATE course_safety_policies SET course_type = 'PROFESSIONAL' "
        "WHERE course_type IN ('BASIC', 'basic')"
    )
    op.execute(
        "UPDATE course_safety_policies SET course_type = 'CYBERSECURITY' "
        "WHERE course_type IN ('CTF', 'ctf')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError(
            "0062 appends PostgreSQL enum values and normalizes rows; "
            "restore the prior database environment before resuming traffic instead"
        )
    # SQLite：数据归一化不可逆，仅提示不执行。
    raise RuntimeError("0062 row normalization cannot be safely downgraded")
