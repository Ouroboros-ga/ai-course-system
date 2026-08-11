"""access_control_v1_backfill

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26 13:50:00

将 legacy 权限来源（users.role / courses.teacher_id / student_enrollments）
转换为 Course Access v1 的显式记录（course_memberships / course_capabilities /
platform_permission_assignments）。

规则（与原 db_migrator._backfill_access_control 保持一致）：
- 幂等：每条由迁移创建的记录都标记 migration_batch_id = 'access-control-v1'，
  重复执行不会产生重复记录（通过查询 batch_id 判断是否已执行）。
- 不覆盖人工创建的记录：只插入 batch 标记为空的记录。
- 阻断条件：preflight 发现孤儿课程/成员关系时，迁移应被阻止（由部署层
  调用 migration_preflight.access_control_preflight 检查）。

downgrade 只删除本批次创建的记录，不恢复已被覆盖的 legacy 字段。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH_ID = "access-control-v1"


def upgrade() -> None:
    bind = op.get_bind()

    # Each target row is checked independently. A partially applied batch must
    # continue filling missing grants without overwriting explicit records.
    # 1. 为每个课程创建默认 capability（learning + course_building + cognitive_analysis）
    bind.execute(
        sa.text(
            """
            INSERT INTO course_capabilities
                (course_id, learning, course_building, knowledge_graph, evidence,
                 experiment, coding_sandbox, cognitive_analysis, safety_policy,
                 updated_at, migration_batch_id)
            SELECT id, TRUE, TRUE, FALSE, FALSE, FALSE, FALSE, TRUE, FALSE,
                   CURRENT_TIMESTAMP, :batch_id
            FROM courses
            WHERE NOT EXISTS (
                SELECT 1 FROM course_capabilities c
                WHERE c.course_id = courses.id
            )
            """
        ),
        {"batch_id": BATCH_ID},
    )

    # 2. 教师 -> owner 成员关系
    bind.execute(
        sa.text(
            """
            INSERT INTO course_memberships
                (user_id, course_id, role, status, permission_overrides,
                 analytics_excluded, joined_at, updated_at, migration_batch_id)
            SELECT teacher_id, id, 'OWNER', 'ACTIVE', '{}', TRUE,
                   COALESCE(created_at, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, :batch_id
            FROM courses
            WHERE teacher_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM course_memberships m
                  WHERE m.user_id = courses.teacher_id
                    AND m.course_id = courses.id
              )
            """
        ),
        {"batch_id": BATCH_ID},
    )

    # 3. 活跃学生 -> student 成员关系
    bind.execute(
        sa.text(
            """
            INSERT INTO course_memberships
                (user_id, course_id, role, status, permission_overrides,
                 analytics_excluded, joined_at, updated_at, migration_batch_id)
            SELECT student_id, course_id, 'STUDENT', 'ACTIVE', '{}', FALSE,
                   COALESCE(enrolled_at, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, :batch_id
            FROM student_enrollments
            WHERE is_active = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM course_memberships m
                  WHERE m.user_id = student_enrollments.student_id
                    AND m.course_id = student_enrollments.course_id
              )
            """
        ),
        {"batch_id": BATCH_ID},
    )

    # 4. admin 角色 -> platform.admin 权限
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_permission_assignments
                (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
            SELECT id, 'ADMIN', id, CURRENT_TIMESTAMP, :batch_id
            FROM users
            WHERE UPPER(CAST(role AS TEXT)) = 'ADMIN'
              AND NOT EXISTS (
                  SELECT 1 FROM platform_permission_assignments p
                  WHERE p.user_id = users.id
                    AND p.permission = 'ADMIN'
              )
            """
        ),
        {"batch_id": BATCH_ID},
    )

    # 5. teacher 角色 -> platform.course.create 权限
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_permission_assignments
                (user_id, permission, granted_by_user_id, granted_at, migration_batch_id)
            SELECT id, 'COURSE_CREATE', id, CURRENT_TIMESTAMP, :batch_id
            FROM users
            WHERE UPPER(CAST(role AS TEXT)) = 'TEACHER'
              AND NOT EXISTS (
                  SELECT 1 FROM platform_permission_assignments p
                  WHERE p.user_id = users.id
                    AND p.permission = 'COURSE_CREATE'
              )
            """
        ),
        {"batch_id": BATCH_ID},
    )


def downgrade() -> None:
    """删除本批次创建的记录。

    注意：这只删除迁移批次创建的记录，不删除人工后续修改的记录。
    应用代码必须回退到理解 legacy role/teacher_id/enrollment 的版本。
    """
    bind = op.get_bind()
    for table in (
        "platform_permission_assignments",
        "course_memberships",
        "course_capabilities",
    ):
        bind.execute(
            sa.text(
                f"DELETE FROM {table} WHERE migration_batch_id = :batch_id"
            ),
            {"batch_id": BATCH_ID},
        )
