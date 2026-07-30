"""Immutable course knowledge bundles and GraphRAG/vector build records.

The active learner view is one CourseKnowledgeHead pointer.  Graph, evidence,
citations and vectors are prepared off to the side and become visible only
after validation and a successful compare-and-swap activation.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


def _public_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class GraphRagRunStatus(str, Enum):
    QUEUED = "queued"
    EXPORTING = "exporting"
    EXTRACTING = "extracting"
    CLASSIFYING = "classifying"
    RECONCILING = "reconciling"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class VectorIndexStatus(str, Enum):
    QUEUED = "queued"
    BUILDING = "building"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class KnowledgeBundleStatus(str, Enum):
    DRAFT = "draft"
    APPROVED_PENDING_INDEX = "approved_pending_index"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class ProjectionOutboxStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GraphRagRun(SQLModel, table=True):
    __tablename__ = "graph_rag_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(default_factory=lambda: _public_id("grr"), unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    corpus_snapshot_id: Optional[str] = Field(default=None, index=True)
    parent_run_id: Optional[str] = Field(default=None, index=True)
    task_id: Optional[str] = Field(default=None, index=True)
    status: GraphRagRunStatus = Field(default=GraphRagRunStatus.QUEUED, index=True)
    method: str = Field(default="standard", max_length=32)
    prompt_policy_version: str = Field(default="edu-graph-graphrag/2.0-zh", index=True)
    completion_provider: str = Field(default="", max_length=80)
    completion_model: str = Field(default="", max_length=160)
    embedding_provider: str = Field(default="", max_length=80)
    embedding_model: str = Field(default="", max_length=160)
    effective_config_hash: str = Field(default="", index=True)
    input_content_hash: str = Field(default="", index=True)
    input_chunk_count: int = Field(default=0)
    entity_count: int = Field(default=0)
    relationship_count: int = Field(default=0)
    typed_relationship_count: int = Field(default=0)
    warning_count: int = Field(default=0)
    artifact_root_uri: str = Field(default="")
    input_manifest_uri: str = Field(default="")
    output_manifest_uri: str = Field(default="")
    report_uri: str = Field(default="")
    regeneration_reason: str = Field(default="")
    regeneration_instructions: str = Field(default="")
    source_scope: dict = Field(default_factory=dict, sa_column=Column(JSON))
    relation_profile: list = Field(default_factory=list, sa_column=Column(JSON))
    token_usage: dict = Field(default_factory=dict, sa_column=Column(JSON))
    estimated_cost: float = Field(default=0.0)
    actual_cost: float = Field(default=0.0)
    draft_nodes: list = Field(default_factory=list, sa_column=Column(JSON))
    draft_relations: list = Field(default_factory=list, sa_column=Column(JSON))
    warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    error_code: str = Field(default="", max_length=80)
    error_message: str = Field(default="")
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    finished_at: Optional[datetime] = Field(default=None)


class GraphRagEntityMapping(SQLModel, table=True):
    __tablename__ = "graph_rag_entity_mappings"
    __table_args__ = (
        UniqueConstraint(
            "graphrag_run_id", "graphrag_entity_id",
            name="uq_graphrag_run_entity",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    graphrag_run_id: str = Field(index=True)
    graphrag_entity_id: str = Field(index=True)
    entity_title: str = Field(default="", max_length=500)
    entity_type: str = Field(default="concept", max_length=80)
    entity_fingerprint: str = Field(default="", index=True)
    knowledge_node_id: int = Field(foreign_key="course_knowledge_nodes.id", index=True)
    node_key: str = Field(index=True)
    mapping_method: str = Field(default="new_identity", max_length=80)
    mapping_score: float = Field(default=0.0)
    source_text_unit_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    source_anchor_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseVectorIndex(SQLModel, table=True):
    __tablename__ = "course_vector_indexes"

    id: Optional[int] = Field(default=None, primary_key=True)
    vector_index_id: str = Field(default_factory=lambda: _public_id("cvi"), unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    bundle_id: Optional[str] = Field(default=None, index=True)
    graphrag_run_id: Optional[str] = Field(default=None, index=True)
    graph_snapshot_id: str = Field(index=True)
    retrieval_snapshot_id: str = Field(index=True)
    provider: str = Field(default="lancedb", max_length=40)
    storage_uri: str = Field(default="")
    manifest_uri: str = Field(default="")
    embedding_provider: str = Field(default="", max_length=80)
    embedding_model: str = Field(default="", max_length=160)
    embedding_revision: str = Field(default="", max_length=160)
    vector_dimension: int = Field(default=0)
    evidence_row_count: int = Field(default=0)
    text_unit_row_count: int = Field(default=0)
    entity_row_count: int = Field(default=0)
    content_hash: str = Field(default="", index=True)
    status: VectorIndexStatus = Field(default=VectorIndexStatus.QUEUED, index=True)
    task_id: Optional[str] = Field(default=None, index=True)
    error_code: str = Field(default="", max_length=80)
    error_message: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_aware)
    validated_at: Optional[datetime] = Field(default=None)


class CourseKnowledgeBundle(SQLModel, table=True):
    __tablename__ = "course_knowledge_bundles"
    __table_args__ = (
        UniqueConstraint("course_id", "version", name="uq_knowledge_bundle_course_version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    bundle_id: str = Field(default_factory=lambda: _public_id("ckb"), unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    version: int = Field(default=1)
    prev_bundle_id: Optional[str] = Field(default=None, index=True)
    graphrag_run_id: Optional[str] = Field(default=None, index=True)
    corpus_snapshot_id: Optional[str] = Field(default=None, index=True)
    graph_snapshot_id: str = Field(index=True)
    retrieval_snapshot_id: str = Field(index=True)
    vector_index_id: Optional[str] = Field(default=None, index=True)
    approval_manifest_hash: str = Field(default="", index=True)
    content_hash: str = Field(default="", index=True)
    status: KnowledgeBundleStatus = Field(default=KnowledgeBundleStatus.DRAFT, index=True)
    label: str = Field(default="", max_length=240)
    approved_by: Optional[int] = Field(default=None, foreign_key="users.id")
    approved_at: Optional[datetime] = Field(default=None)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseKnowledgeHead(SQLModel, table=True):
    __tablename__ = "course_knowledge_heads"

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", unique=True, index=True)
    active_bundle_id: Optional[str] = Field(default=None, index=True)
    lock_version: int = Field(default=0)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class CourseKnowledgeActivation(SQLModel, table=True):
    __tablename__ = "course_knowledge_activations"

    id: Optional[int] = Field(default=None, primary_key=True)
    activation_id: str = Field(default_factory=lambda: _public_id("cka"), unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    bundle_id: str = Field(index=True)
    previous_bundle_id: Optional[str] = Field(default=None, index=True)
    action: str = Field(default="publish", max_length=32)
    actor_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseKnowledgeBuildLease(SQLModel, table=True):
    __tablename__ = "course_knowledge_build_leases"
    __table_args__ = (
        UniqueConstraint("course_id", "lease_kind", name="uq_course_knowledge_build_lease"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    lease_kind: str = Field(default="graphrag", max_length=32, index=True)
    task_id: str = Field(index=True)
    lease_token: str = Field(default="", index=True)
    lease_expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)


class LearningProjectionOutbox(SQLModel, table=True):
    __tablename__ = "learning_projection_outbox"
    __table_args__ = (
        UniqueConstraint("attempt_id", "knowledge_node_id", name="uq_projection_attempt_node"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(default_factory=lambda: _public_id("lpo"), unique=True, index=True)
    attempt_id: int = Field(foreign_key="question_attempts.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    knowledge_node_id: int = Field(index=True)
    status: ProjectionOutboxStatus = Field(default=ProjectionOutboxStatus.PENDING, index=True)
    retry_count: int = Field(default=0)
    last_error: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_aware)
    processed_at: Optional[datetime] = Field(default=None)
