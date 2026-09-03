"""Add platform.nexus.use platform permission and default-grant it to all users.

Revision ID: 0068
Revises: 0067
Create Date: 2026-09-03

CodeNexus 转型决策（docs/phase1/2026-09-03_CodeNexus转型实施决策.md D10，
2026-09-03 修订）：

1. 新增平台权限 ``platform.nexus.use`` 作为 Nexus AI（课程外全局入口）的
   使用门槛——Course Access v1 是纯 course-scoped 设计，没有"全局能力"承载物，
   这是技术决策补丁 v1.1 核查结论 X1 的落地解法。

2. **默认授权所有用户**：回填为每个存量用户插入一条 NEXUS_USE 授权行；
   注册/登录/泛雅同步流程中的 ``ensure_default_nexus_grant`` 对新用户自动
   授予。管理员仍可经授权端点按用户撤销（软撤销），撤销行不会被流程复活，
   回填也跳过已有行（含已撤销）的用户。

``platform_permission_assignments.permission`` 在 PostgreSQL 上是 native
ENUM type ``platformpermission``（存成员名，如 ``NEXUS_USE``），必须
``ALTER TYPE ... ADD VALUE``。注意：PostgreSQL 12+ 虽允许在事务内执行
ADD VALUE，但**新值不能在同一事务中使用**，而本迁移的回填 INSERT 立即
使用该值；env.py 将整个 upgrade 包在一个事务里，因此 ALTER TYPE 必须走
独立 AUTOCOMMIT 连接先提交。SQLite（本地 Demo/测试）上枚举即 VARCHAR，
无 DDL 需求。

downgrade 删除本批次回填行；PostgreSQL 无法移除枚举值（如实保留，该值
不再被引用即无副作用）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

BATCH_ID = "0068_nexus_use_default_grant"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 独立 AUTOCOMMIT 连接执行 ADD VALUE 并立即提交，使主事务中的回填
        # INSERT 可以使用新值（否则报 "unsafe use of new value"）。
        with bind.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            conn.exec_driver_sql(
                "ALTER TYPE platformpermission ADD VALUE IF NOT EXISTS 'NEXUS_USE'"
            )
    # SQLite / 其他方言：枚举以 VARCHAR 存储，无 DDL。

    # 默认授权回填：仅为从未持有过该权限的用户插行；已有行（含软撤销）
    # 的用户跳过，保证管理员的显式撤销优先于默认授权。
    bind.execute(sa.text(
        """
        INSERT INTO platform_permission_assignments
            (user_id, permission, granted_at, migration_batch_id)
        SELECT u.id, 'NEXUS_USE', CURRENT_TIMESTAMP, :batch_id
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1 FROM platform_permission_assignments p
            WHERE p.user_id = u.id
              AND p.permission = 'NEXUS_USE'
        )
        """
    ), {"batch_id": BATCH_ID})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM platform_permission_assignments WHERE migration_batch_id = :batch_id"
    ), {"batch_id": BATCH_ID})
    # PostgreSQL 不支持从 ENUM 移除值；NEXUS_USE 保留但无默认授权行引用。
