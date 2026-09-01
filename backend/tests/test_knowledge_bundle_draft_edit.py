"""Teacher manual draft-node edits: rename / delete before whole-graph approval."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.knowledge_bundle_model import GraphRagRun, GraphRagRunStatus
from app.services.knowledge_bundle_service import (
    KnowledgeBundleError,
    knowledge_bundle_service,
)


@pytest.fixture(name="session")
def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[GraphRagRun.__table__])
    with Session(engine) as session:
        yield session


_BASE_TIME = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_run(
    course_id: int,
    run_id: str,
    status: GraphRagRunStatus,
    *,
    offset_minutes: int = 0,
) -> GraphRagRun:
    return GraphRagRun(
        course_id=course_id,
        run_id=run_id,
        status=status,
        created_at=_BASE_TIME + timedelta(minutes=offset_minutes),
        draft_nodes=[
            {"id": "kn_a", "title": "最小生成树", "type": "concept", "description": "旧描述"},
            {"id": "kn_b", "title": "生成树", "type": "concept"},
            {"id": "kn_c", "title": "普里姆算法", "type": "algorithm"},
        ],
        draft_relations=[
            {"id": "rel_1", "source": "kn_a", "target": "kn_b", "type": "RELATED_TO"},
            {"id": "rel_2", "source": "kn_c", "target": "kn_a", "type": "APPLIES_TO"},
            {"id": "rel_3", "source": "kn_b", "target": "kn_c", "type": "PREREQUISITE_OF"},
        ],
        entity_count=3,
        relationship_count=3,
    )


def test_rename_draft_node(session) -> None:
    run = _make_run(1, "grr_edit_1", GraphRagRunStatus.AWAITING_REVIEW)
    session.add(run)
    session.commit()

    updated = knowledge_bundle_service.update_draft_node(
        session,
        course_id=1,
        run_id="grr_edit_1",
        node_id="kn_a",
        title="  最小生成树（MST）  ",
        description="带权连通图中权值总和最小的生成树",
        actor_user_id=42,
    )
    node = next(n for n in updated.draft_nodes if n["id"] == "kn_a")
    assert node["title"] == "最小生成树（MST）"
    assert node["description"] == "带权连通图中权值总和最小的生成树"
    audit = next(w for w in updated.warnings if w.get("code") == "TEACHER_MANUAL_EDIT")
    assert audit["action"] == "node.rename"
    assert audit["previous_title"] == "最小生成树"
    assert audit["actor_user_id"] == 42


def test_rename_rejects_duplicate_title(session) -> None:
    run = _make_run(1, "grr_edit_2", GraphRagRunStatus.AWAITING_REVIEW)
    session.add(run)
    session.commit()

    with pytest.raises(KnowledgeBundleError) as excinfo:
        knowledge_bundle_service.update_draft_node(
            session,
            course_id=1,
            run_id="grr_edit_2",
            node_id="kn_a",
            title="生成树",
            description=None,
            actor_user_id=42,
        )
    assert excinfo.value.code == "DUPLICATE_NODE_TITLE"


def test_delete_draft_node_cascades_relations(session) -> None:
    run = _make_run(1, "grr_edit_3", GraphRagRunStatus.AWAITING_REVIEW)
    session.add(run)
    session.commit()

    updated = knowledge_bundle_service.delete_draft_node(
        session,
        course_id=1,
        run_id="grr_edit_3",
        node_id="kn_a",
        actor_user_id=42,
    )
    assert [n["id"] for n in updated.draft_nodes] == ["kn_b", "kn_c"]
    # rel_1 与 rel_2 都以 kn_a 为端点，级联删除；rel_3 保留
    assert [r["id"] for r in updated.draft_relations] == ["rel_3"]
    assert updated.entity_count == 2
    assert updated.relationship_count == 1
    audit = next(w for w in updated.warnings if w.get("code") == "TEACHER_MANUAL_EDIT")
    assert audit["action"] == "node.delete"
    assert audit["removed_relation_count"] == 2


def test_edit_rejected_when_run_not_reviewable(session) -> None:
    run = _make_run(1, "grr_edit_4", GraphRagRunStatus.APPROVED)
    session.add(run)
    session.commit()

    with pytest.raises(KnowledgeBundleError) as excinfo:
        knowledge_bundle_service.delete_draft_node(
            session,
            course_id=1,
            run_id="grr_edit_4",
            node_id="kn_a",
            actor_user_id=42,
        )
    assert excinfo.value.code == "GRAPH_RUN_NOT_REVIEWABLE"


def test_edit_rejected_when_run_not_latest(session) -> None:
    session.add(_make_run(1, "grr_old", GraphRagRunStatus.SUPERSEDED, offset_minutes=0))
    session.add(_make_run(1, "grr_new", GraphRagRunStatus.AWAITING_REVIEW, offset_minutes=10))
    session.commit()

    with pytest.raises(KnowledgeBundleError) as excinfo:
        knowledge_bundle_service.update_draft_node(
            session,
            course_id=1,
            run_id="grr_old",
            node_id="kn_a",
            title="新标题",
            description=None,
            actor_user_id=42,
        )
    assert excinfo.value.code == "GRAPHRAG_RUN_NOT_FOUND"


def test_edit_rejected_when_node_missing(session) -> None:
    session.add(_make_run(2, "grr_edit_5", GraphRagRunStatus.AWAITING_REVIEW))
    session.commit()

    with pytest.raises(KnowledgeBundleError) as excinfo:
        knowledge_bundle_service.update_draft_node(
            session,
            course_id=2,
            run_id="grr_edit_5",
            node_id="kn_missing",
            title="新标题",
            description=None,
            actor_user_id=42,
        )
    assert excinfo.value.code == "GRAPH_NODE_NOT_FOUND"
