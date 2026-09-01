"""Add conversational coding challenge offers and evidence episodes.

Revision ID: 0067
Revises: 0066
Create Date: 2026-09-01 09:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("experiment_definitions") as batch:
        batch.add_column(sa.Column("origin", sa.String(32), nullable=False, server_default="teacher"))
        batch.add_column(sa.Column("visibility", sa.String(32), nullable=False, server_default="course_catalog"))
        batch.add_column(sa.Column("owner_student_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_experiment_definitions_owner_student", "users", ["owner_student_id"], ["id"])
        batch.create_index("ix_experiment_definitions_origin", ["origin"])
        batch.create_index("ix_experiment_definitions_visibility", ["visibility"])
        batch.create_index("ix_experiment_definitions_owner_student_id", ["owner_student_id"])
        batch.create_index("ix_experiment_definitions_expires_at", ["expires_at"])

    with op.batch_alter_table("experiment_versions") as batch:
        batch.add_column(sa.Column("starter_code", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("generation_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    with op.batch_alter_table("experiment_attempts") as batch:
        batch.add_column(sa.Column("interaction_mode", sa.String(32), nullable=False, server_default="assessment"))
        batch.add_column(sa.Column("source_release_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("outline_node_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("last_activity_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()))
        batch.create_index("ix_experiment_attempts_interaction_mode", ["interaction_mode"])
        batch.create_index("ix_experiment_attempts_source_release_id", ["source_release_id"])
        batch.create_index("ix_experiment_attempts_outline_node_id", ["outline_node_id"])
        batch.create_index("ix_experiment_attempts_last_activity_at", ["last_activity_at"])

    with op.batch_alter_table("experiment_runs") as batch:
        batch.add_column(sa.Column("normalized_source_hash", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("evidence_quality", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.create_index("ix_experiment_runs_normalized_source_hash", ["normalized_source_hash"])

    with op.batch_alter_table("conversation_messages") as batch:
        batch.add_column(sa.Column("message_kind", sa.String(32), nullable=False, server_default="qa"))
        batch.create_index("ix_conversation_messages_message_kind", ["message_kind"])

    op.create_table(
        "coding_challenge_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_session_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("concept_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="preparing"),
        sa.Column("source", sa.String(32), nullable=False, server_default="ai"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("why_now", sa.String(500), nullable=False, server_default=""),
        sa.Column("difficulty", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("languages", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("reason_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("experiment_id", sa.String(64), nullable=True),
        sa.Column("version_id", sa.String(64), nullable=True),
        sa.Column("attempt_id", sa.String(64), nullable=True),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("source_release_id", sa.String(100), nullable=True),
        sa.Column("outline_node_id", sa.String(100), nullable=True),
        sa.Column("replacement_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("offer_id", name="uq_coding_challenge_offer_id"),
    )
    for name, columns in {
        "ix_coding_challenge_offers_offer_id": ["offer_id"],
        "ix_coding_challenge_offers_course_id": ["course_id"],
        "ix_coding_challenge_offers_student_id": ["student_id"],
        "ix_coding_challenge_offers_conversation_session_id": ["conversation_session_id"],
        "ix_coding_challenge_offers_trace_id": ["trace_id"],
        "ix_coding_challenge_offers_concept_id": ["concept_id"],
        "ix_coding_challenge_offers_status": ["status"],
        "ix_coding_challenge_offers_source": ["source"],
        "ix_coding_challenge_offers_experiment_id": ["experiment_id"],
        "ix_coding_challenge_offers_version_id": ["version_id"],
        "ix_coding_challenge_offers_attempt_id": ["attempt_id"],
        "ix_coding_challenge_offers_task_id": ["task_id"],
        "ix_coding_challenge_offers_source_release_id": ["source_release_id"],
        "ix_coding_challenge_offers_outline_node_id": ["outline_node_id"],
        "ix_coding_challenge_offers_expires_at": ["expires_at"],
        "ix_coding_challenge_offers_created_at": ["created_at"],
    }.items():
        op.create_index(name, "coding_challenge_offers", columns)

    op.create_table(
        "coding_evidence_episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("episode_id", sa.String(72), nullable=False),
        sa.Column("attempt_id", sa.String(64), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("close_reason", sa.String(32), nullable=False, server_default=""),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("evidence_id", sa.String(150), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("episode_id", name="uq_coding_evidence_episode_id"),
        sa.UniqueConstraint("attempt_id", name="uq_coding_evidence_episode_attempt"),
    )
    for name, columns in {
        "ix_coding_evidence_episodes_episode_id": ["episode_id"],
        "ix_coding_evidence_episodes_attempt_id": ["attempt_id"],
        "ix_coding_evidence_episodes_course_id": ["course_id"],
        "ix_coding_evidence_episodes_student_id": ["student_id"],
        "ix_coding_evidence_episodes_status": ["status"],
        "ix_coding_evidence_episodes_evidence_id": ["evidence_id"],
        "ix_coding_evidence_episodes_created_at": ["created_at"],
        "ix_coding_evidence_episodes_closed_at": ["closed_at"],
    }.items():
        op.create_index(name, "coding_evidence_episodes", columns)


def downgrade() -> None:
    op.drop_table("coding_evidence_episodes")
    op.drop_table("coding_challenge_offers")

    with op.batch_alter_table("conversation_messages") as batch:
        batch.drop_index("ix_conversation_messages_message_kind")
        batch.drop_column("message_kind")
    with op.batch_alter_table("experiment_runs") as batch:
        batch.drop_index("ix_experiment_runs_normalized_source_hash")
        batch.drop_column("evidence_quality")
        batch.drop_column("normalized_source_hash")
    with op.batch_alter_table("experiment_attempts") as batch:
        batch.drop_index("ix_experiment_attempts_last_activity_at")
        batch.drop_index("ix_experiment_attempts_outline_node_id")
        batch.drop_index("ix_experiment_attempts_source_release_id")
        batch.drop_index("ix_experiment_attempts_interaction_mode")
        batch.drop_column("last_activity_at")
        batch.drop_column("outline_node_id")
        batch.drop_column("source_release_id")
        batch.drop_column("interaction_mode")
    with op.batch_alter_table("experiment_versions") as batch:
        batch.drop_column("generation_metadata")
        batch.drop_column("starter_code")
    with op.batch_alter_table("experiment_definitions") as batch:
        batch.drop_index("ix_experiment_definitions_expires_at")
        batch.drop_index("ix_experiment_definitions_owner_student_id")
        batch.drop_index("ix_experiment_definitions_visibility")
        batch.drop_index("ix_experiment_definitions_origin")
        batch.drop_constraint("fk_experiment_definitions_owner_student", type_="foreignkey")
        batch.drop_column("expires_at")
        batch.drop_column("owner_student_id")
        batch.drop_column("visibility")
        batch.drop_column("origin")
