from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.course_model import Course
from app.models.question_bank_model import QuestionAttempt, QuestionBankItem
from app.models.access_control_model import CourseCapability
from app.models.graph_production_model import (
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
    GraphSnapshotRecord,
    SnapshotStatus,
)
from app.models.knowledge_bundle_model import (
    CourseKnowledgeActivation,
    CourseKnowledgeBundle,
    CourseKnowledgeHead,
    CourseVectorIndex,
    GraphRagEntityMapping,
    GraphRagRun,
    GraphRagRunStatus,
    LearningProjectionOutbox,
    KnowledgeBundleStatus,
    ProjectionOutboxStatus,
    VectorIndexStatus,
)
from app.platform.knowledge.embedding import (
    FixedEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from app.platform.knowledge.lancedb_provider import (
    LanceDbCourseVectorProvider,
    VectorIndexError,
)
from app.platform.knowledge.graphrag_runner import GraphRagRunner
from app.platform.knowledge.graphrag_runner import _normalize_relationship_endpoints
from app.platform.knowledge.relationship_classifier import (
    EducationalRelationshipClassifier,
)
from app.platform.knowledge.document_ir_exporter import (
    GraphRagInputDocument,
    GraphRagInputManifest,
)
from app.services.knowledge_bundle_service import (
    KnowledgeBundleError,
    knowledge_bundle_service,
)
from app.services.graphrag_identity_service import GraphRagIdentityService
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_access_service import activate_student_membership
from app.platform.agents.errors import ScopeRejectedError
from app.platform.agents.providers.retrieval.active_bundle import (
    ActiveBundleScopePort,
)
from app.services import learning_projection_outbox_service as projection_outbox


def _rows(course_label: str) -> tuple[list[dict], list[dict], list[dict]]:
    text_units = [{
        "id": f"tu_{course_label}",
        "text": f"{course_label} 二叉树遍历原理",
        "retrieval_chunk_id": f"rc_{course_label}",
        "text_unit_id": f"tu_{course_label}",
        "document_id": f"doc_{course_label}",
        "node_key": f"kn_{course_label}",
        "knowledge_node_id": 1,
        "evidence_ids": [f"ev_{course_label}"],
        "citation_ids": [f"cit_{course_label}"],
        "page_number": 3,
    }]
    entities = [{
        "id": f"entity_{course_label}",
        "text": f"{course_label} 二叉树是层次数据结构",
        "node_key": f"kn_{course_label}",
        "knowledge_node_id": 1,
        "document_id": f"doc_{course_label}",
        "evidence_ids": [f"ev_{course_label}"],
        "citation_ids": [f"cit_{course_label}"],
        "page_number": 3,
    }]
    evidence = [{
        "id": f"ev_{course_label}",
        "text": f"{course_label} 二叉树原文证据",
        "citation_id": f"cit_{course_label}",
        "citation_ids": [f"cit_{course_label}"],
        "document_id": f"doc_{course_label}",
        "retrieval_chunk_id": f"rc_{course_label}",
        "node_key": f"kn_{course_label}",
        "knowledge_node_id": 1,
        "evidence_ids": [f"ev_{course_label}"],
        "page_number": 3,
    }]
    return text_units, entities, evidence


def test_embedding_provider_batches_and_self_detects_dimension(monkeypatch):
    calls: list[list[str]] = []

    class Response:
        status_code = 200

        def __init__(self, texts):
            self._texts = texts

        def json(self):
            return {
                "data": [
                    {"index": index, "embedding": [float(index), 1.0, 2.0]}
                    for index, _ in enumerate(self._texts)
                ]
            }

    def fake_post(_url, *, headers, json, timeout):
        assert headers["Authorization"] == "Bearer test-key"
        assert timeout == 3
        calls.append(json["input"])
        return Response(json["input"])

    monkeypatch.setattr("app.platform.knowledge.embedding.httpx.post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        api_base="https://embedding.invalid/v1",
        api_key="test-key",
        model_name="embed-test",
        timeout_seconds=3,
        batch_size=2,
        max_retries=0,
    )
    vectors = provider.embed(["a", "b", "c", "d", "e"])

    assert [len(batch) for batch in calls] == [2, 2, 1]
    assert len(vectors) == 5
    assert provider.expected_dimension == 3


def test_graphrag_31_relationship_titles_are_normalized_to_run_ids():
    entities = [
        {"id": "entity-a", "title": "发动机排量"},
        {"id": "entity-b", "title": "多缸发动机"},
    ]
    relations = [{
        "id": "relation-a",
        "source": "发动机排量",
        "target": "多缸发动机",
    }]
    normalized = _normalize_relationship_endpoints(entities, relations)
    assert normalized[0]["source"] == "entity-a"
    assert normalized[0]["target"] == "entity-b"


def test_graphrag_reuses_complete_output_after_postprocessing_interruption(
    tmp_path,
):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pd = pytest.importorskip("pandas")
    pd.DataFrame([{"id": "rc_one", "title": "rc:one"}]).to_parquet(
        output_dir / "documents.parquet"
    )
    pd.DataFrame([{"id": "tu_one", "document_id": "rc_one"}]).to_parquet(
        output_dir / "text_units.parquet"
    )
    pd.DataFrame([{
        "id": "entity_one",
        "title": "Concept",
        "text_unit_ids": ["tu_one"],
    }]).to_parquet(output_dir / "entities.parquet")
    pd.DataFrame([{
        "id": "relation_one",
        "source": "Concept",
        "target": "Concept",
        "text_unit_ids": ["tu_one"],
    }]).to_parquet(output_dir / "relationships.parquet")
    manifest = GraphRagInputManifest(
        schema_version="course-graphrag-input/1.0",
        course_id=87,
        input_content_hash="hash",
        documents=(GraphRagInputDocument(
            source_key="rc_one",
            course_id=87,
            retrieval_chunk_id="one",
            document_id="doc_one",
            ir_version_id="ir_one",
            page_number=1,
            title="rc:one",
            text="Concept",
            content_hash="content",
            anchor_ids=(),
            evidence_span_ids=(),
            formal_evidence_ids=(),
            citation_ids=(),
            initial_status="candidate",
        ),),
    )

    outputs = GraphRagRunner()._load_complete_outputs(
        output_dir,
        manifest=manifest,
    )

    assert outputs is not None
    assert outputs["documents"][0]["id"] == "rc_one"


def test_relationship_classification_preserves_source_order_with_parallel_batches(
    monkeypatch,
):
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_API_BASE", "https://test.invalid/v1")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_MODEL", "test-model")
    classifier = EducationalRelationshipClassifier()
    classifier.batch_size = 2
    classifier.max_workers = 3
    entities = [
        {"id": "source", "title": "Source"},
        {"id": "target", "title": "Target"},
    ]
    relations = [
        {
            "id": f"relation_{index}",
            "source": "source",
            "target": "target",
            "description": str(index),
            "text_unit_ids": [f"tu_{index}"],
        }
        for index in range(7)
    ]

    def fake_call(rows, *, allowed_types):
        assert "RELATED_TO" in allowed_types
        return [
            {
                "id": row["id"],
                "type": "RELATED_TO",
                "confidence": 1,
                "reason": row["description"],
            }
            for row in reversed(rows)
        ]

    monkeypatch.setattr(classifier, "_call", fake_call)
    classified = classifier.classify(entities, relations)

    assert [row["id"] for row in classified] == [
        f"relation_{index}" for index in range(7)
    ]


def test_identity_matching_does_not_merge_different_titles_from_same_anchor():
    existing = SimpleNamespace(
        node_key="kn_existing",
        title="发动机排量",
        kind="concept",
        source_anchor_ids=["anchor_same_block"],
        extra_data={},
    )

    node, method, score = GraphRagIdentityService._match(
        [existing],
        title="热能",
        entity_type="concept",
        anchor_ids={"anchor_same_block"},
    )

    assert node is None
    assert method == "new_identity"
    assert score == 0.0


def test_refinement_reuses_artifacts_without_model_calls_and_reports_quality(
    session,
    teacher_user,
    tmp_path,
    monkeypatch,
):
    pd = pytest.importorskip("pandas")
    course = Course(
        fanya_course_id="refine-artifacts-course",
        fanya_course_name="Refine artifacts course",
        title="Refine artifacts course",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.flush()
    existing = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_displacement",
        title="ENGINE DISPLACEMENT",
        kind="concept",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
        source_anchor_ids=["anchor_same"],
        extra_data={"description": "Engine swept volume."},
    )
    session.add(existing)
    session.flush()
    parent = GraphRagRun(
        run_id="grr_parent_refine",
        course_id=course.id,
        status=GraphRagRunStatus.APPROVED,
        method="standard",
        input_content_hash="input-hash",
        created_by=teacher_user.id,
    )
    session.add(parent)
    session.commit()

    monkeypatch.setattr(settings, "GRAPHRAG_STORAGE_ROOT", str(tmp_path))
    root = tmp_path / "courses" / str(course.id) / "runs" / parent.run_id
    input_dir = root / "input"
    output_dir = root / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (input_dir / "input_manifest.json").write_text(json.dumps({
        "schema_version": "course-graphrag-input/1.0",
        "course_id": course.id,
        "input_content_hash": "input-hash",
        "chunk_count": 1,
        "documents": [{
            "source_key": "rc_chunk",
            "course_id": course.id,
            "retrieval_chunk_id": "chunk",
            "document_id": "document",
            "ir_version_id": "ir",
            "page_number": 1,
            "title": "rc:chunk",
            "text": "Engine displacement differs from thermal energy.",
            "content_hash": "content-hash",
            "anchor_ids": ["anchor_same"],
            "evidence_span_ids": [],
            "formal_evidence_ids": [],
            "citation_ids": [],
            "initial_status": "candidate",
        }],
    }), encoding="utf-8")
    pd.DataFrame([{"id": "rc_chunk", "title": "rc:chunk"}]).to_parquet(
        output_dir / "documents.parquet"
    )
    pd.DataFrame([{
        "id": "tu_chunk",
        "document_ids": ["rc_chunk"],
        "text": "Engine displacement differs from thermal energy.",
    }]).to_parquet(output_dir / "text_units.parquet")
    pd.DataFrame([
        {
            "id": "entity_displacement",
            "title": "ENGINE DISPLACEMENT",
            "type": "concept",
            "description": "The swept volume of engine cylinders.",
            "text_unit_ids": ["tu_chunk"],
        },
        {
            "id": "entity_thermal",
            "title": "THERMAL ENERGY",
            "type": "concept",
            "description": "Energy associated with temperature.",
            "text_unit_ids": ["tu_chunk"],
        },
        {
            "id": "entity_placeholder",
            "title": "IMAGE12.JPEG",
            "type": "concept",
            "description": "placeholder",
            "text_unit_ids": ["tu_chunk"],
        },
    ]).to_parquet(output_dir / "entities.parquet")
    source_relations = [
        {
            "id": "relation_valid",
            "source": "entity_displacement",
            "target": "entity_thermal",
            "description": "Different energy and volume concepts.",
            "text_unit_ids": ["tu_chunk"],
        },
        {
            "id": "relation_placeholder",
            "source": "entity_placeholder",
            "target": "entity_thermal",
            "description": "Invalid placeholder relation.",
            "text_unit_ids": ["tu_chunk"],
        },
    ]
    pd.DataFrame(source_relations).to_parquet(output_dir / "relationships.parquet")
    typed_relations = [
        {**row, "type": "RELATED_TO", "confidence": 0.8, "reason": row["description"]}
        for row in source_relations
    ]
    (output_dir / "typed_relationships.json").write_text(
        json.dumps(typed_relations), encoding="utf-8"
    )

    monkeypatch.setattr(
        "app.platform.knowledge.relationship_classifier."
        "EducationalRelationshipClassifier.classify",
        lambda *_args, **_kwargs: pytest.fail("refinement must not call a model classifier"),
    )
    refined = knowledge_bundle_service.refine_existing_run(
        session,
        course_id=course.id,
        parent_run_id=parent.run_id,
        actor_user_id=teacher_user.id,
        reason="Use strict identity mapping",
    )

    assert refined.status == GraphRagRunStatus.AWAITING_REVIEW
    assert refined.method == "quality-refinement"
    assert refined.token_usage["model_calls"] == 0
    assert refined.actual_cost == 0
    assert {node["title"] for node in refined.draft_nodes} == {
        "ENGINE DISPLACEMENT", "THERMAL ENERGY",
    }
    by_title = {node["title"]: node for node in refined.draft_nodes}
    assert by_title["ENGINE DISPLACEMENT"]["id"] == "kn_displacement"
    assert by_title["ENGINE DISPLACEMENT"]["description"].startswith("The swept")
    assert by_title["THERMAL ENERGY"]["id"] != "kn_displacement"
    assert len(refined.draft_relations) == 1
    report = refined.warnings[0]
    assert report["rejected_placeholder_count"] == 1
    assert report["removed_placeholder_relationship_count"] == 1
    assert report["mapping_method_counts"]["exact_title_anchor"] == 1
    assert report["mapping_method_counts"]["new_identity"] == 1
    mappings = session.exec(select(GraphRagEntityMapping).where(
        GraphRagEntityMapping.graphrag_run_id == refined.run_id,
    )).all()
    assert len(mappings) == 2

    duplicate = knowledge_bundle_service.refine_existing_run(
        session,
        course_id=course.id,
        parent_run_id=parent.run_id,
        actor_user_id=teacher_user.id,
        reason="Use strict identity mapping",
    )
    assert duplicate.run_id == refined.run_id


def test_learning_projection_outbox_retries_without_process_restart(
    session,
    teacher_user,
    student_user,
    monkeypatch,
):
    course = Course(
        fanya_course_id="outbox-retry-course",
        fanya_course_name="Outbox retry course",
        title="Outbox retry course",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.flush()
    question = QuestionBankItem(
        question_text="What is a prerequisite?",
        course_id=course.id,
        created_by=teacher_user.id,
    )
    session.add(question)
    session.flush()
    attempt = QuestionAttempt(
        question_id=question.id,
        course_id=course.id,
        student_id=student_user.id,
        student_answer="A required prior concept",
        is_correct=True,
        score=1.0,
    )
    session.add(attempt)
    session.flush()
    event = projection_outbox.enqueue_learning_projection(
        session,
        attempt_id=attempt.id,
        student_id=student_user.id,
        course_id=course.id,
        knowledge_node_id=123,
    )
    session.commit()

    calls = 0

    def flaky_refresh(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient projection failure")
        return (
            SimpleNamespace(id=101),
            SimpleNamespace(recommendation_id="rec_retry"),
        )

    monkeypatch.setattr(
        projection_outbox,
        "refresh_cognition_and_recommendation",
        flaky_refresh,
    )
    monkeypatch.setattr(projection_outbox, "RETRY_DELAYS_SECONDS", (0,))

    asyncio.run(projection_outbox._consume_with_retries(event.event_id))

    session.expire_all()
    persisted = session.exec(select(LearningProjectionOutbox).where(
        LearningProjectionOutbox.event_id == event.event_id,
    )).one()
    assert calls == 2
    assert persisted.retry_count == 2
    assert persisted.status == ProjectionOutboxStatus.SUCCEEDED
    assert persisted.last_error == ""

    duplicate = projection_outbox.enqueue_learning_projection(
        session,
        attempt_id=attempt.id,
        student_id=student_user.id,
        course_id=course.id,
        knowledge_node_id=123,
    )
    session.commit()
    assert duplicate.event_id == event.event_id
    assert duplicate.status == ProjectionOutboxStatus.SUCCEEDED
    assert duplicate.retry_count == 2


def test_real_lancedb_is_persistent_course_isolated_and_citation_closed(tmp_path):
    embedding = FixedEmbeddingProvider(dimension=8)
    provider = LanceDbCourseVectorProvider(
        root=tmp_path,
        embedding_provider=embedding,
    )
    rows_a = _rows("course_a")
    rows_b = _rows("course_b")

    built_a = provider.build(
        course_id=87,
        bundle_id="ckb_course_a",
        graph_snapshot_id="graph_a",
        text_units=rows_a[0],
        entities=rows_a[1],
        evidence=rows_a[2],
    )
    provider.build(
        course_id=88,
        bundle_id="ckb_course_b",
        graph_snapshot_id="graph_b",
        text_units=rows_b[0],
        entities=rows_b[1],
        evidence=rows_b[2],
    )

    assert built_a.text_unit_row_count == 1
    assert built_a.entity_row_count == 1
    assert built_a.evidence_row_count == 1
    assert built_a.vector_dimension == 8

    # A fresh provider simulates a process restart: validation needs no API key.
    restarted = LanceDbCourseVectorProvider(root=tmp_path)
    assert restarted.validate(
        course_id=87,
        bundle_id="ckb_course_a",
    ).manifest_hash == built_a.manifest_hash

    searcher = LanceDbCourseVectorProvider(
        root=tmp_path,
        embedding_provider=embedding,
    )
    results = searcher.search(
        course_id=87,
        bundle_id="ckb_course_a",
        query="二叉树遍历",
        top_k=6,
    )
    assert results
    assert all(row["course_id"] == 87 for row in results)
    assert all("course_b" not in row["text"] for row in results)
    assert all(row["citation_ids"] for row in results)

    with pytest.raises(VectorIndexError, match="INDEX_MANIFEST_MISMATCH"):
        restarted.validate(course_id=87, bundle_id="ckb_course_b")


def test_lancedb_learner_search_excludes_rows_without_citations(tmp_path):
    text_units, entities, evidence = _rows("closed")
    text_units[0]["citation_ids"] = []
    entities[0]["citation_ids"] = []
    evidence[0]["citation_id"] = ""
    evidence[0]["citation_ids"] = []
    provider = LanceDbCourseVectorProvider(
        root=tmp_path,
        embedding_provider=FixedEmbeddingProvider(),
    )

    with pytest.raises(VectorIndexError, match="VECTOR_ROW_INVALID:citation_id"):
        provider.build(
            course_id=87,
            bundle_id="ckb_no_citation",
            graph_snapshot_id="graph",
            text_units=text_units,
            entities=entities,
            evidence=evidence,
        )


def test_bundle_activation_is_atomic_and_rollback_only_switches_head(
    session,
    teacher_user,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "VECTOR_STORE_ROOT", str(tmp_path))
    course = Course(
        fanya_course_id="bundle-atomic-course",
        fanya_course_name="Bundle atomic course",
        title="Bundle atomic course",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_atomic",
        title="原子发布",
        status=CourseKnowledgeNodeStatus.ACCEPTED,
    )
    session.add(node)
    session.commit()
    session.refresh(node)

    def prepare(version: int):
        snapshot = GraphSnapshotRecord(
            snapshot_id=f"snapshot_atomic_{version}",
            course_id=course.id,
            version=version,
            nodes=[{
                "id": node.node_key,
                "identity_id": node.id,
                "title": node.title,
                "citation_ids": [f"cit_atomic_{version}"],
            }],
            relations=[],
            status=SnapshotStatus.DRAFT,
            is_active=False,
            node_count=1,
            relation_count=0,
            created_by=teacher_user.id,
        )
        session.add(snapshot)
        session.flush()
        bundle = CourseKnowledgeBundle(
            bundle_id=f"ckb_atomic_{version}",
            course_id=course.id,
            version=version,
            graph_snapshot_id=snapshot.snapshot_id,
            retrieval_snapshot_id=f"retrieval_atomic_{version}",
            status=KnowledgeBundleStatus.READY,
            created_by=teacher_user.id,
        )
        session.add(bundle)
        session.flush()
        rows = _rows(f"atomic_{version}")
        rows[0][0]["node_key"] = node.node_key
        rows[0][0]["knowledge_node_id"] = node.id
        rows[1][0]["node_key"] = node.node_key
        rows[1][0]["knowledge_node_id"] = node.id
        rows[2][0]["node_key"] = node.node_key
        rows[2][0]["knowledge_node_id"] = node.id
        built = LanceDbCourseVectorProvider(
            root=tmp_path,
            embedding_provider=FixedEmbeddingProvider(),
        ).build(
            course_id=course.id,
            bundle_id=bundle.bundle_id,
            graph_snapshot_id=snapshot.snapshot_id,
            text_units=rows[0],
            entities=rows[1],
            evidence=rows[2],
        )
        vector = CourseVectorIndex(
            vector_index_id=f"cvi_atomic_{version}",
            course_id=course.id,
            bundle_id=bundle.bundle_id,
            graph_snapshot_id=snapshot.snapshot_id,
            retrieval_snapshot_id=bundle.retrieval_snapshot_id,
            storage_uri=built.storage_uri,
            manifest_uri=built.manifest_uri,
            vector_dimension=built.vector_dimension,
            text_unit_row_count=built.text_unit_row_count,
            entity_row_count=built.entity_row_count,
            evidence_row_count=built.evidence_row_count,
            content_hash=built.manifest_hash,
            status=VectorIndexStatus.READY,
        )
        session.add(vector)
        session.flush()
        bundle.vector_index_id = vector.vector_index_id
        session.add(bundle)
        session.commit()
        return bundle, built

    first, first_index = prepare(1)
    second, _ = prepare(2)
    knowledge_bundle_service.activate_bundle(
        session,
        course_id=course.id,
        bundle_id=first.bundle_id,
        actor_user_id=teacher_user.id,
        action="publish",
    )
    knowledge_bundle_service.activate_bundle(
        session,
        course_id=course.id,
        bundle_id=second.bundle_id,
        actor_user_id=teacher_user.id,
        action="publish",
    )
    head = session.exec(select(CourseKnowledgeHead).where(
        CourseKnowledgeHead.course_id == course.id,
    )).one()
    assert head.active_bundle_id == second.bundle_id
    assert head.lock_version == 2

    complete = tmp_path / "courses" / str(course.id) / "bundles" / first.bundle_id / "COMPLETE"
    valid_marker = complete.read_text(encoding="ascii")
    complete.write_text("tampered", encoding="ascii")
    with pytest.raises(KnowledgeBundleError, match="INDEX_MANIFEST_MISMATCH"):
        knowledge_bundle_service.activate_bundle(
            session,
            course_id=course.id,
            bundle_id=first.bundle_id,
            actor_user_id=teacher_user.id,
            action="rollback",
        )
    session.expire_all()
    unchanged = session.exec(select(CourseKnowledgeHead).where(
        CourseKnowledgeHead.course_id == course.id,
    )).one()
    assert unchanged.active_bundle_id == second.bundle_id
    assert unchanged.lock_version == 2

    complete.write_text(valid_marker, encoding="ascii")
    knowledge_bundle_service.activate_bundle(
        session,
        course_id=course.id,
        bundle_id=first.bundle_id,
        actor_user_id=teacher_user.id,
        action="rollback",
    )
    session.expire_all()
    rolled_back = session.exec(select(CourseKnowledgeHead).where(
        CourseKnowledgeHead.course_id == course.id,
    )).one()
    assert rolled_back.active_bundle_id == first.bundle_id
    assert rolled_back.lock_version == 3
    activations = session.exec(select(CourseKnowledgeActivation).where(
        CourseKnowledgeActivation.course_id == course.id,
    )).all()
    assert [item.action for item in activations] == ["publish", "publish", "rollback"]
    assert (tmp_path / "courses" / str(course.id) / "bundles" / second.bundle_id).is_dir()
    assert first_index.manifest_hash == valid_marker


def test_bundle_api_uses_unified_envelope_and_course_access(
    client,
    session,
    teacher_user,
    teacher_token,
    student_token,
):
    course = Course(
        fanya_course_id="bundle-api-course",
        fanya_course_name="Bundle API course",
        title="Bundle API course",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.flush()
    establish_course_access_baseline(session, course.id, teacher_user.id)
    session.flush()
    capability = session.exec(select(CourseCapability).where(
        CourseCapability.course_id == course.id,
    )).one()
    capability.knowledge_graph = True
    capability.evidence = True
    session.add(capability)
    session.commit()

    response = client.get(
        f"/api/v1/graph/course/{course.id}/knowledge-bundle/active",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "获取当前知识包成功",
        "data": None,
    }

    denied = client.get(
        f"/api/v1/graph/course/{course.id}/knowledge-bundle/active",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == 403


def test_refinement_api_requires_course_review_permission(
    client,
    session,
    teacher_user,
    teacher_token,
    student_token,
):
    course = Course(
        fanya_course_id="bundle-refine-access",
        fanya_course_name="Bundle refine access",
        title="Bundle refine access",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.flush()
    establish_course_access_baseline(session, course.id, teacher_user.id)
    capability = session.exec(select(CourseCapability).where(
        CourseCapability.course_id == course.id,
    )).one()
    capability.knowledge_graph = True
    capability.evidence = True
    session.add(capability)
    parent = GraphRagRun(
        run_id="grr_refine_access_parent",
        course_id=course.id,
        status=GraphRagRunStatus.APPROVED,
        method="standard",
        created_by=teacher_user.id,
    )
    session.add(parent)
    session.commit()
    payload = {
        "parent_run_id": parent.run_id,
        "reason": "Verify Course Access before artifact loading",
    }

    denied = client.post(
        f"/api/v1/graph/course/{course.id}/knowledge-bundle/refine",
        headers={"Authorization": f"Bearer {student_token}"},
        json=payload,
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/v1/graph/course/{course.id}/knowledge-bundle/refine",
        headers={"Authorization": f"Bearer {teacher_token}"},
        json=payload,
    )
    assert allowed.status_code == 424
    assert allowed.json()["data"]["error_code"] == "GRAPH_ARTIFACTS_NOT_FOUND"


def test_approved_refinement_supersedes_sibling_review_drafts(session, teacher_user):
    course = Course(
        fanya_course_id="refine-supersede-course",
        fanya_course_name="Refine supersede course",
        title="Refine supersede course",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.flush()
    approved = GraphRagRun(
        run_id="grr_refine_approved",
        course_id=course.id,
        method="quality-refinement",
        status=GraphRagRunStatus.APPROVED,
        source_scope={"artifact_source_run_id": "grr_raw"},
        created_by=teacher_user.id,
    )
    sibling = GraphRagRun(
        run_id="grr_refine_sibling",
        course_id=course.id,
        method="quality-refinement",
        status=GraphRagRunStatus.AWAITING_REVIEW,
        source_scope={"artifact_source_run_id": "grr_raw"},
        created_by=teacher_user.id,
    )
    unrelated = GraphRagRun(
        run_id="grr_refine_unrelated",
        course_id=course.id,
        method="quality-refinement",
        status=GraphRagRunStatus.AWAITING_REVIEW,
        source_scope={"artifact_source_run_id": "grr_other"},
        created_by=teacher_user.id,
    )
    session.add_all([approved, sibling, unrelated])
    session.flush()

    changed = knowledge_bundle_service.supersede_sibling_refinement_drafts(
        session,
        approved_run=approved,
    )

    assert changed == 1
    assert sibling.status == GraphRagRunStatus.SUPERSEDED
    assert unrelated.status == GraphRagRunStatus.AWAITING_REVIEW


def test_teaching_agent_bundle_scope_uses_course_access_v1(
    session,
    teacher_user,
    student_user,
):
    course = Course(
        fanya_course_id="bundle-agent-scope",
        fanya_course_name="Bundle agent scope",
        title="Bundle agent scope",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.flush()
    establish_course_access_baseline(session, course.id, teacher_user.id)
    session.flush()
    capability = session.exec(select(CourseCapability).where(
        CourseCapability.course_id == course.id,
    )).one()
    capability.knowledge_graph = True
    capability.evidence = True
    session.add(capability)
    session.commit()

    scope = ActiveBundleScopePort()
    with pytest.raises(ScopeRejectedError):
        asyncio.run(scope.validate_scope(
            student_id=str(student_user.id),
            course_id=str(course.id),
            resource_id=None,
        ))

    activate_student_membership(session, course.id, student_user.id)
    session.commit()
    decision = asyncio.run(scope.validate_scope(
        student_id=str(student_user.id),
        course_id=str(course.id),
        resource_id=None,
    ))
    assert decision["allowed"] is True
    assert decision["source"] == "course_access_v1"


def test_graphrag_config_keeps_completion_and_embedding_separate(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_PROVIDER", "openai")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_MODEL", "completion-model")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_API_BASE", "https://completion.invalid/v1")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_API_KEY", "completion-test-key")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_API_BASE", "https://embedding.invalid/v1")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_API_KEY", "embedding-test-key")
    config = GraphRagRunner._make_config(
        artifact_root=tmp_path,
        output_dir=tmp_path / "output",
        reports_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        vector_dir=tmp_path / "vectors",
        policy_context={
            "reason": "关系方向错误",
            "instructions": "区分定义与应用，保留 {原文} 证据",
            "source_scope": {
                "required_concepts": ["二叉树"],
                "forbidden_concepts": ["广告"],
            },
        },
    )

    completion = config.completion_models["default_completion_model"]
    embedding = config.embedding_models["default_embedding_model"]
    assert completion.model == "completion-model"
    assert completion.api_base == "https://completion.invalid/v1"
    assert embedding.model == "embedding-model"
    assert embedding.api_base == "https://embedding.invalid/v1"
    assert config.embed_text.names == [
        "text_unit_text",
        "entity_description",
    ]
    prompt = Path(config.extract_graph.prompt).read_text(encoding="utf-8")
    assert "关系方向错误" in prompt
    assert "二叉树" in prompt
    assert "广告" in prompt
    assert "{{原文}}" in prompt


def test_graphrag_local_bge_skips_internal_embedding_workflow(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_PROVIDER", "openai")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_MODEL", "completion-model")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_API_BASE", "https://completion.invalid/v1")
    monkeypatch.setattr(settings, "GRAPHRAG_COMPLETION_API_KEY", "completion-test-key")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_PROVIDER", "local_bge")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_MODEL", "local-bge")
    monkeypatch.setattr(settings, "GRAPHRAG_EMBEDDING_LOCAL_PATH", str(tmp_path))
    config = GraphRagRunner._make_config(
        artifact_root=tmp_path,
        output_dir=tmp_path / "output",
        reports_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        vector_dir=tmp_path / "vectors",
    )

    assert "generate_text_embeddings" not in config.workflows
    assert config.workflows[-1] == "create_final_text_units"
