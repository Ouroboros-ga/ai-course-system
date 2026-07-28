"""outline_script_patch_v1

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-27 21:00:00

统一课程建设九步实施计划 Step 1：新建课程树、讲稿与备课 Agent 提案模型。

新增 6 张表：
- course_outline_versions / course_outline_nodes   课程目录有序树（真正 parent_node_id FK 自引用，
  区别于旧 ScriptNode.chapter_id 字符串）。node_type 冻结 5 种。
- teaching_script_versions / teaching_script_nodes  讲稿按课程树组织；与目录发布状态一致。
- patch_proposals / patch_proposal_operations       备课 Agent 只产 Proposal，不直写业务表；
  before/after 用于 Diff；evidence_refs 仅课程 Evidence，外网资料走 external_ref。

所有表按 course_id 严格隔离；草稿与发布版本分离；教师锁定后 AI 不可覆盖。
见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §5 Step 1。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table: str) -> bool:
    from sqlalchemy import inspect
    inspector = inspect(bind)
    return table in inspector.get_table_names()


def _create_table_if_missing(table_name: str, create_fn) -> None:
    """幂等建表：create_all 建出的库（如 legacy stamp 场景）可能已存在这些表。"""
    bind = op.get_bind()
    if _table_exists(bind, table_name):
        return
    create_fn()




def upgrade() -> None:
    # Step 1: 6 new course-tree/script/patch tables
    def _make_course_outline_nodes():
        op.create_table('course_outline_nodes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('outline_node_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('outline_version_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('parent_node_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('node_type', sa.Enum('CHAPTER', 'SECTION', 'KNOWLEDGE_POINT', 'EXAMPLE', 'PRACTICE_SUGGESTION', name='outlinenodetype'), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('knowledge_graph_node_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('source_block_refs', sa.JSON(), nullable=True),
        sa.Column('page_range', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column('generation_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('content_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('locked_by', sa.Integer(), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['locked_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('outline_version_id', 'order_index', 'parent_node_id', name='uq_outline_node_order_within_parent')
        )
        op.create_index(op.f('ix_course_outline_nodes_content_hash'), 'course_outline_nodes', ['content_hash'], unique=False)
        op.create_index(op.f('ix_course_outline_nodes_course_id'), 'course_outline_nodes', ['course_id'], unique=False)
        op.create_index(op.f('ix_course_outline_nodes_knowledge_graph_node_id'), 'course_outline_nodes', ['knowledge_graph_node_id'], unique=False)
        op.create_index(op.f('ix_course_outline_nodes_node_type'), 'course_outline_nodes', ['node_type'], unique=False)
        op.create_index(op.f('ix_course_outline_nodes_outline_node_id'), 'course_outline_nodes', ['outline_node_id'], unique=True)
        op.create_index(op.f('ix_course_outline_nodes_outline_version_id'), 'course_outline_nodes', ['outline_version_id'], unique=False)
        op.create_index(op.f('ix_course_outline_nodes_parent_node_id'), 'course_outline_nodes', ['parent_node_id'], unique=False)
    _create_table_if_missing('course_outline_nodes', _make_course_outline_nodes)
    def _make_course_outline_versions():
        op.create_table('course_outline_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('outline_version_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('lifecycle_status', sa.Enum('DRAFT', 'PUBLISHED', 'ARCHIVED', name='outlinelifecyclestatus'), nullable=False),
        sa.Column('source_parse_run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_course_outline_versions_course_id'), 'course_outline_versions', ['course_id'], unique=False)
        op.create_index(op.f('ix_course_outline_versions_created_at'), 'course_outline_versions', ['created_at'], unique=False)
        op.create_index(op.f('ix_course_outline_versions_lifecycle_status'), 'course_outline_versions', ['lifecycle_status'], unique=False)
        op.create_index(op.f('ix_course_outline_versions_outline_version_id'), 'course_outline_versions', ['outline_version_id'], unique=True)
        op.create_index(op.f('ix_course_outline_versions_source_parse_run_id'), 'course_outline_versions', ['source_parse_run_id'], unique=False)
    _create_table_if_missing('course_outline_versions', _make_course_outline_versions)
    def _make_patch_proposal_operations():
        op.create_table('patch_proposal_operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('op_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('proposal_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('operation', sa.Enum('ADD', 'REMOVE', 'REPLACE', 'MOVE', 'REORDER', name='patchoperation'), nullable=False),
        sa.Column('target', sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
        sa.Column('before', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('after', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('evidence_refs', sa.JSON(), nullable=True),
        sa.Column('external_ref', sqlmodel.sql.sqltypes.AutoString(length=300), nullable=True),
        sa.Column('policy_version', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('accepted', sa.Boolean(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_patch_proposal_operations_course_id'), 'patch_proposal_operations', ['course_id'], unique=False)
        op.create_index(op.f('ix_patch_proposal_operations_op_id'), 'patch_proposal_operations', ['op_id'], unique=True)
        op.create_index(op.f('ix_patch_proposal_operations_operation'), 'patch_proposal_operations', ['operation'], unique=False)
        op.create_index(op.f('ix_patch_proposal_operations_proposal_id'), 'patch_proposal_operations', ['proposal_id'], unique=False)
    _create_table_if_missing('patch_proposal_operations', _make_patch_proposal_operations)
    def _make_patch_proposals():
        op.create_table('patch_proposals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('tool_name', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('policy_version', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'PARTIALLY_ACCEPTED', 'EXPIRED', name='patchproposalstatus'), nullable=False),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_patch_proposals_course_id'), 'patch_proposals', ['course_id'], unique=False)
        op.create_index(op.f('ix_patch_proposals_created_at'), 'patch_proposals', ['created_at'], unique=False)
        op.create_index(op.f('ix_patch_proposals_proposal_id'), 'patch_proposals', ['proposal_id'], unique=True)
        op.create_index(op.f('ix_patch_proposals_status'), 'patch_proposals', ['status'], unique=False)
        op.create_index(op.f('ix_patch_proposals_tool_name'), 'patch_proposals', ['tool_name'], unique=False)
    _create_table_if_missing('patch_proposals', _make_patch_proposals)
    def _make_teaching_script_nodes():
        op.create_table('teaching_script_nodes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('script_node_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('script_version_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('outline_node_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('content', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('style', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('evidence_refs', sa.JSON(), nullable=True),
        sa.Column('source_block_refs', sa.JSON(), nullable=True),
        sa.Column('content_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('locked_by', sa.Integer(), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['locked_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_teaching_script_nodes_content_hash'), 'teaching_script_nodes', ['content_hash'], unique=False)
        op.create_index(op.f('ix_teaching_script_nodes_course_id'), 'teaching_script_nodes', ['course_id'], unique=False)
        op.create_index(op.f('ix_teaching_script_nodes_outline_node_id'), 'teaching_script_nodes', ['outline_node_id'], unique=False)
        op.create_index(op.f('ix_teaching_script_nodes_script_node_id'), 'teaching_script_nodes', ['script_node_id'], unique=True)
        op.create_index(op.f('ix_teaching_script_nodes_script_version_id'), 'teaching_script_nodes', ['script_version_id'], unique=False)
    _create_table_if_missing('teaching_script_nodes', _make_teaching_script_nodes)
    def _make_teaching_script_versions():
        op.create_table('teaching_script_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('script_version_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('outline_version_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('lifecycle_status', sa.Enum('DRAFT', 'PUBLISHED', 'ARCHIVED', name='outlinelifecyclestatus'), nullable=False),
        sa.Column('source_parse_run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_teaching_script_versions_course_id'), 'teaching_script_versions', ['course_id'], unique=False)
        op.create_index(op.f('ix_teaching_script_versions_created_at'), 'teaching_script_versions', ['created_at'], unique=False)
        op.create_index(op.f('ix_teaching_script_versions_lifecycle_status'), 'teaching_script_versions', ['lifecycle_status'], unique=False)
        op.create_index(op.f('ix_teaching_script_versions_outline_version_id'), 'teaching_script_versions', ['outline_version_id'], unique=False)
        op.create_index(op.f('ix_teaching_script_versions_script_version_id'), 'teaching_script_versions', ['script_version_id'], unique=True)
        op.create_index(op.f('ix_teaching_script_versions_source_parse_run_id'), 'teaching_script_versions', ['source_parse_run_id'], unique=False)
    _create_table_if_missing('teaching_script_versions', _make_teaching_script_versions)


def downgrade() -> None:
    # Step 1: drop 6 course-tree/script/patch tables (reverse order)
    op.drop_index(op.f('ix_teaching_script_versions_source_parse_run_id'), table_name='teaching_script_versions')
    op.drop_index(op.f('ix_teaching_script_versions_script_version_id'), table_name='teaching_script_versions')
    op.drop_index(op.f('ix_teaching_script_versions_outline_version_id'), table_name='teaching_script_versions')
    op.drop_index(op.f('ix_teaching_script_versions_lifecycle_status'), table_name='teaching_script_versions')
    op.drop_index(op.f('ix_teaching_script_versions_created_at'), table_name='teaching_script_versions')
    op.drop_index(op.f('ix_teaching_script_versions_course_id'), table_name='teaching_script_versions')
    op.drop_table('teaching_script_versions')
    op.drop_index(op.f('ix_teaching_script_nodes_script_version_id'), table_name='teaching_script_nodes')
    op.drop_index(op.f('ix_teaching_script_nodes_script_node_id'), table_name='teaching_script_nodes')
    op.drop_index(op.f('ix_teaching_script_nodes_outline_node_id'), table_name='teaching_script_nodes')
    op.drop_index(op.f('ix_teaching_script_nodes_course_id'), table_name='teaching_script_nodes')
    op.drop_index(op.f('ix_teaching_script_nodes_content_hash'), table_name='teaching_script_nodes')
    op.drop_table('teaching_script_nodes')
    op.drop_index(op.f('ix_patch_proposals_tool_name'), table_name='patch_proposals')
    op.drop_index(op.f('ix_patch_proposals_status'), table_name='patch_proposals')
    op.drop_index(op.f('ix_patch_proposals_proposal_id'), table_name='patch_proposals')
    op.drop_index(op.f('ix_patch_proposals_created_at'), table_name='patch_proposals')
    op.drop_index(op.f('ix_patch_proposals_course_id'), table_name='patch_proposals')
    op.drop_table('patch_proposals')
    op.drop_index(op.f('ix_patch_proposal_operations_proposal_id'), table_name='patch_proposal_operations')
    op.drop_index(op.f('ix_patch_proposal_operations_operation'), table_name='patch_proposal_operations')
    op.drop_index(op.f('ix_patch_proposal_operations_op_id'), table_name='patch_proposal_operations')
    op.drop_index(op.f('ix_patch_proposal_operations_course_id'), table_name='patch_proposal_operations')
    op.drop_table('patch_proposal_operations')
    op.drop_index(op.f('ix_course_outline_versions_source_parse_run_id'), table_name='course_outline_versions')
    op.drop_index(op.f('ix_course_outline_versions_outline_version_id'), table_name='course_outline_versions')
    op.drop_index(op.f('ix_course_outline_versions_lifecycle_status'), table_name='course_outline_versions')
    op.drop_index(op.f('ix_course_outline_versions_created_at'), table_name='course_outline_versions')
    op.drop_index(op.f('ix_course_outline_versions_course_id'), table_name='course_outline_versions')
    op.drop_table('course_outline_versions')
    op.drop_index(op.f('ix_course_outline_nodes_parent_node_id'), table_name='course_outline_nodes')
    op.drop_index(op.f('ix_course_outline_nodes_outline_version_id'), table_name='course_outline_nodes')
    op.drop_index(op.f('ix_course_outline_nodes_outline_node_id'), table_name='course_outline_nodes')
    op.drop_index(op.f('ix_course_outline_nodes_node_type'), table_name='course_outline_nodes')
    op.drop_index(op.f('ix_course_outline_nodes_knowledge_graph_node_id'), table_name='course_outline_nodes')
    op.drop_index(op.f('ix_course_outline_nodes_course_id'), table_name='course_outline_nodes')
    op.drop_index(op.f('ix_course_outline_nodes_content_hash'), table_name='course_outline_nodes')
    op.drop_table('course_outline_nodes')
