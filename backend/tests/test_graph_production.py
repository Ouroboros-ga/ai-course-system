"""G9 Evidence 与课程知识图谱生产化测试

验证：
- 每个图谱关系可回溯 Evidence 或教师确认记录
- 图谱、Evidence、引用和推荐均按课程隔离
- 课件重新解析或删除时，历史引用不会静默指向错误内容
- 发布不可变 GraphSnapshot，支持版本差异与回滚
- 学生只读已发布快照
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import get_password_hash, create_access_token
from app.models.access_control_model import (
    CourseCapability, CourseMembership, CourseRole, MembershipStatus,
    PlatformPermission, PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.models.graph_production_model import (
    CourseEvidenceRecord, CourseKnowledgeNode, GraphSnapshotRecord, GraphNodeReview,
    EvidenceStatus, SnapshotStatus, CourseKnowledgeNodeStatus,
)
from app.models.document_parse_model import CandidateBatchStatus, GraphCandidateBatch
from app.models.document_artifact_model import DocumentArtifact
from app.services.course_access_service import (
    establish_course_access_baseline, activate_student_membership,
)
from app.services.graph_production_service import (
    create_evidence, publish_snapshot, publish_reviewed_snapshot, get_active_snapshot,
    list_snapshots, rollback_snapshot, mark_evidence_stale,
    get_evidence_for_node, serialize_snapshot, serialize_evidence,
    graph_target_hash,
    list_review_candidates, transition_review, diff_snapshots,
    get_prerequisite_nodes,
    bridge_candidate_batch, GraphAssemblyError,
)


def _user(session, name, role=UserRole.TEACHER):
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user); session.commit(); session.refresh(user)
    return user

def _course(session, teacher_id):
    course = Course(
        fanya_course_id=f"g9-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="G9", title="G9", teacher_id=teacher_id, status=CourseStatus.PUBLISHED,
    )
    session.add(course); session.commit(); session.refresh(course)
    return course

def _setup(session, teacher, student=None):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    if student:
        activate_student_membership(session, course.id, student.id)
    cap = session.exec(select(CourseCapability).where(CourseCapability.course_id == course.id)).first()
    if cap:
        cap.knowledge_graph = True
        cap.course_building = True
        session.add(cap)
    session.commit()
    return course

def _token(user):
    return create_access_token({"sub": str(user.id), "username": user.username, "role": user.role.value})


class TestGraphProductionService:
    """图谱生产化服务单元测试"""

    def test_publish_snapshot(self, session):
        """发布不可变快照"""
        teacher = _user(session, "g9_pub_t")
        course = _setup(session, teacher)
        evidence = create_evidence(
            session,
            course_id=course.id,
            page_number=1,
            text_snippet="二分查找以前置的有序序列为基础。",
        )
        nodes = [
            {"node_id": "n1", "label": "二分查找", "type": "knowledge_point"},
            {"node_id": "n2", "label": "有序序列", "type": "knowledge_point"},
        ]
        relations = [{
            "relation_id": "r1",
            "source": "n2",
            "target": "n1",
            "type": "prerequisite_of",
            "evidence_ids": [evidence.evidence_id],
        }]
        snapshot = publish_snapshot(session, course_id=course.id, nodes=nodes, relations=relations, user_id=teacher.id)
        assert snapshot.status == SnapshotStatus.PUBLISHED
        assert snapshot.is_active is True
        assert snapshot.node_count == 2
        assert snapshot.relation_count == 1

    def test_publish_second_supersedes_first(self, session):
        """发布新快照后旧快照变为 SUPERSEDED"""
        teacher = _user(session, "g9_sup_t")
        course = _setup(session, teacher)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}], relations=[], user_id=teacher.id)
        snapshot2 = publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}, {"node_id": "n2"}], relations=[], user_id=teacher.id)
        snapshots = list_snapshots(session, course.id)
        assert len(snapshots) == 2
        assert snapshots[0].is_active is True  # 最新
        assert snapshots[1].status == SnapshotStatus.SUPERSEDED

    def test_get_active_snapshot(self, session):
        """获取活跃快照"""
        teacher = _user(session, "g9_act_t")
        course = _setup(session, teacher)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}], relations=[], user_id=teacher.id)
        active = get_active_snapshot(session, course.id)
        assert active is not None
        assert active.is_active is True

    def test_rollback_snapshot(self, session):
        """回滚到指定快照"""
        teacher = _user(session, "g9_rb_t")
        course = _setup(session, teacher)
        s1 = publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}], relations=[], user_id=teacher.id)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n2"}], relations=[], user_id=teacher.id)
        # 回滚到 v1
        rolled = rollback_snapshot(session, course.id, s1.snapshot_id, teacher.id)
        assert rolled.snapshot_id == s1.snapshot_id
        assert rolled.is_active is True
        assert rolled.status == SnapshotStatus.PUBLISHED

    def test_mark_evidence_stale(self, session):
        """课件重新解析时标记 Evidence 为 stale"""
        teacher = _user(session, "g9_stale_t")
        course = _setup(session, teacher)
        ev = create_evidence(session, course_id=course.id, document_id="doc-uuid-1", page_number=1, text_snippet="原文内容")
        assert ev.status == EvidenceStatus.ACTIVE
        count = mark_evidence_stale(session, course.id, "doc-uuid-1")
        assert count == 1
        # 验证状态已变更
        refreshed = session.get(CourseEvidenceRecord, ev.id)
        assert refreshed.status == EvidenceStatus.STALE
        assert refreshed.stale_reason == "courseware_reparse"

    def test_mark_evidence_stale_can_join_caller_transaction(self, session):
        """A document lifecycle transaction controls its own commit boundary."""
        teacher = _user(session, "g9_stale_tx_t")
        course = _setup(session, teacher)
        evidence = create_evidence(
            session,
            course_id=course.id,
            document_id="doc-transaction",
            text_snippet="事务中的原文",
        )

        assert mark_evidence_stale(
            session,
            course.id,
            "doc-transaction",
            commit=False,
        ) == 1
        session.flush()
        session.refresh(evidence)
        assert evidence.status == EvidenceStatus.STALE
        assert evidence.stale_reason == "courseware_reparse"

    def test_evidence_with_page_and_text_position(self, session):
        """证据包含页码/文本定位"""
        teacher = _user(session, "g9_pos_t")
        course = _setup(session, teacher)
        ev = create_evidence(
            session, course_id=course.id, document_id="doc-1",
            page_number=5, char_start=100, char_end=200, text_snippet="二分查找的时间复杂度",
        )
        assert ev.page_number == 5
        assert ev.char_start == 100
        assert ev.char_end == 200
        assert ev.content_hash != ""

    def test_cross_course_isolation(self, session):
        """图谱按课程隔离"""
        t1 = _user(session, "g9_iso_t1")
        t2 = _user(session, "g9_iso_t2")
        c1 = _setup(session, t1)
        c2 = _setup(session, t2)
        publish_snapshot(session, course_id=c1.id, nodes=[{"node_id": "n1_c1"}], relations=[], user_id=t1.id)
        publish_snapshot(session, course_id=c2.id, nodes=[{"node_id": "n1_c2"}], relations=[], user_id=t2.id)
        # c1 的快照不包含 c2 的节点
        s1 = get_active_snapshot(session, c1.id)
        assert all(n["node_id"] == "n1_c1" for n in s1.nodes)

    def test_stale_evidence_not_silently_correct(self, session):
        """课件重新解析后历史引用不静默指向错误内容"""
        teacher = _user(session, "g9_silent_t")
        course = _setup(session, teacher)
        ev = create_evidence(session, course_id=course.id, document_id="doc-uuid", text_snippet="旧内容")
        mark_evidence_stale(session, course.id, "doc-uuid")
        # 重新查询证据，状态为 STALE 而非 ACTIVE
        stale_ev = session.get(CourseEvidenceRecord, ev.id)
        assert stale_ev.status == EvidenceStatus.STALE
        serialized = serialize_evidence(stale_ev)
        assert serialized["status"] == "stale"

    def test_relation_requires_current_evidence_or_exact_teacher_review(self, session):
        teacher = _user(session, "g9_relation_review_t")
        course = _setup(session, teacher)
        nodes = [{"node_id": "a"}, {"node_id": "b"}]
        relation = {
            "relation_id": "r-reviewed",
            "source": "a",
            "target": "b",
            "type": "prerequisite_of",
        }
        with pytest.raises(ValueError, match="Evidence"):
            publish_snapshot(
                session,
                course_id=course.id,
                nodes=nodes,
                relations=[relation],
                user_id=teacher.id,
            )

        session.add(GraphNodeReview(
            course_id=course.id,
            target_id="r-reviewed",
            target_type="relation",
            target_content_hash=graph_target_hash(relation),
            decision="accepted",
            reviewer=teacher.id,
        ))
        session.commit()
        publish_snapshot(
            session,
            course_id=course.id,
            nodes=nodes,
            relations=[relation],
            user_id=teacher.id,
        )

        changed = {**relation, "weight": 2}
        with pytest.raises(ValueError, match="Evidence"):
            publish_snapshot(
                session,
                course_id=course.id,
                nodes=nodes,
                relations=[changed],
                user_id=teacher.id,
            )

    def test_rollback_refuses_snapshot_whose_evidence_became_stale(self, session):
        teacher = _user(session, "g9_stale_rollback_t")
        course = _setup(session, teacher)
        evidence = create_evidence(
            session,
            course_id=course.id,
            document_id="doc-stale-rollback",
            text_snippet="A 是 B 的前置知识。",
        )
        nodes = [{"node_id": "a"}, {"node_id": "b"}]
        first = publish_snapshot(
            session,
            course_id=course.id,
            nodes=nodes,
            relations=[{
                "relation_id": "r-stale",
                "source": "a",
                "target": "b",
                "evidence_ids": [evidence.evidence_id],
            }],
            user_id=teacher.id,
        )
        publish_snapshot(
            session,
            course_id=course.id,
            nodes=nodes,
            relations=[],
            user_id=teacher.id,
        )
        mark_evidence_stale(session, course.id, "doc-stale-rollback")
        with pytest.raises(ValueError, match="Evidence"):
            rollback_snapshot(session, course.id, first.snapshot_id, teacher.id)

    def test_snapshot_rejects_non_array_evidence_ids(self, session):
        teacher = _user(session, "g9_evidence_shape_t")
        course = _setup(session, teacher)
        with pytest.raises(ValueError, match="evidence_ids 必须是数组"):
            publish_snapshot(
                session,
                course_id=course.id,
                nodes=[{"node_id": "a"}, {"node_id": "b"}],
                relations=[{
                    "relation_id": "bad-evidence-shape",
                    "source": "a",
                    "target": "b",
                    "evidence_ids": "ev-not-an-array",
                }],
                user_id=teacher.id,
            )


class TestGraphProductionAPI:
    """图谱生产化 API 集成测试"""

    def test_get_snapshot_requires_membership(self, client, session):
        """获取快照需要权限"""
        teacher = _user(session, "g9_api_nm")
        course = _course(session, teacher.id)
        token = _token(teacher)
        response = client.get(
            f"/api/v1/graph/course/{course.id}/snapshot",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_publish_and_get_snapshot(self, client, session):
        """发布并获取快照"""
        teacher = _user(session, "g9_api_pub")
        course = _setup(session, teacher)
        token = _token(teacher)
        # 发布
        response = client.post(
            f"/api/v1/graph/course/{course.id}/publish",
            json={"nodes": [{"node_id": "n1", "label": "test"}], "relations": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        # 获取
        response = client.get(
            f"/api/v1/graph/course/{course.id}/snapshot",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["is_active"] is True
        assert len(data["nodes"]) == 1

    def test_list_snapshots(self, client, session):
        """列出快照版本"""
        teacher = _user(session, "g9_api_list")
        course = _setup(session, teacher)
        token = _token(teacher)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}], relations=[], user_id=teacher.id)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}, {"node_id": "n2"}], relations=[], user_id=teacher.id)
        response = client.get(
            f"/api/v1/graph/course/{course.id}/snapshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 2

    def test_rollback_endpoint(self, client, session):
        """回滚端点"""
        teacher = _user(session, "g9_api_rb")
        course = _setup(session, teacher)
        token = _token(teacher)
        s1 = publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}], relations=[], user_id=teacher.id)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n2"}], relations=[], user_id=teacher.id)
        response = client.post(
            f"/api/v1/graph/course/{course.id}/rollback/{s1.snapshot_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["snapshot_id"] == s1.snapshot_id

    def test_mark_stale_endpoint(self, client, session):
        """标记 stale 端点"""
        teacher = _user(session, "g9_api_stale")
        course = _setup(session, teacher)
        create_evidence(session, course_id=course.id, document_id="doc-test", text_snippet="内容")
        token = _token(teacher)
        response = client.post(
            f"/api/v1/graph/course/{course.id}/mark-stale?document_id=doc-test",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["stale_count"] == 1

    def test_student_can_read_published_snapshot(self, client, session):
        """学生可读已发布快照"""
        teacher = _user(session, "g9_api_student_t")
        student = _user(session, "g9_api_student_s", UserRole.STUDENT)
        course = _setup(session, teacher, student)
        publish_snapshot(session, course_id=course.id, nodes=[{"node_id": "n1"}], relations=[], user_id=teacher.id)
        token = _token(student)
        response = client.get(
            f"/api/v1/graph/course/{course.id}/snapshot",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_student_cannot_publish(self, client, session):
        """学生不能发布快照"""
        teacher = _user(session, "g9_api_nostu_t")
        student = _user(session, "g9_api_nostu_s", UserRole.STUDENT)
        course = _setup(session, teacher, student)
        token = _token(student)
        response = client.post(
            f"/api/v1/graph/course/{course.id}/publish",
            json={"nodes": [], "relations": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_cross_course_api_isolation(self, client, session):
        """跨课程 API 隔离"""
        t1 = _user(session, "g9_api_iso_t1")
        t2 = _user(session, "g9_api_iso_t2")
        s1 = _user(session, "g9_api_iso_s1", UserRole.STUDENT)
        c1 = _setup(session, t1, s1)
        c2 = _setup(session, t2)
        token = _token(s1)
        response = client.get(
            f"/api/v1/graph/course/{c2.id}/snapshot",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403


class TestCandidateIdentityBridge:
    def test_successful_candidate_batch_bridges_to_stable_identities_and_reviews(self, session):
        teacher = _user(session, "identity_bridge_t")
        course = _setup(session, teacher)
        batch = GraphCandidateBatch(
            course_id=course.id,
            initiated_by=teacher.id,
            status=CandidateBatchStatus.SUCCEEDED,
            node_candidate_count=2,
            relation_candidate_count=1,
            node_candidates=[
                {
                    "candidate_id": "gcn-a",
                    "label": "变量",
                    "kind": "concept",
                    "confidence": 0.91,
                    "source_block_ids": ["blk-a"],
                    "anchor_ids": ["ea-a"],
                },
                {
                    "candidate_id": "gcn-b",
                    "label": "函数",
                    "kind": "concept",
                    "confidence": 0.87,
                    "source_block_ids": ["blk-b"],
                    "anchor_ids": ["ea-b"],
                },
            ],
            relation_candidates=[{
                "candidate_id": "gcr-a-b",
                "source_candidate_id": "gcn-a",
                "target_candidate_id": "gcn-b",
                "relation_type": "next_topic",
                "confidence": 0.8,
                "anchor_ids": ["ea-a", "ea-b"],
            }],
        )
        session.add(batch)
        session.commit()
        session.refresh(batch)

        result = bridge_candidate_batch(session, batch=batch)
        session.commit()
        assert result["nodes_created"] == 2
        assert result["reviews_created"] == 3

        nodes = session.exec(
            select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course.id)
        ).all()
        assert {node.source_candidate_id for node in nodes} == {"gcn-a", "gcn-b"}
        assert all(node.node_key.startswith("kn_") for node in nodes)

        reviews = list_review_candidates(session, course.id)
        assert {review.target_type for review in reviews} == {"node", "relation"}
        relation_review = next(review for review in reviews if review.target_type == "relation")
        assert relation_review.target_content["id"] == "gcr-a-b"
        assert relation_review.target_content["source"].startswith("kn_")
        assert relation_review.target_content["target"].startswith("kn_")

        # Re-running the bridge must not duplicate identities or review rows.
        bridge_candidate_batch(session, batch=batch)
        session.commit()
        assert len(session.exec(
            select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course.id)
        ).all()) == 2
        assert len(session.exec(
            select(GraphNodeReview).where(GraphNodeReview.candidate_batch_id == batch.batch_id)
        ).all()) == 3

        node_review = next(review for review in reviews if review.target_type == "node")
        transition_review(
            session, course.id, node_review.id,
            new_decision="accepted", reviewer_id=teacher.id,
        )
        node = session.exec(
            select(CourseKnowledgeNode).where(CourseKnowledgeNode.id == node_review.identity_node_id)
        ).one()
        assert node.status == CourseKnowledgeNodeStatus.ACCEPTED
        session.refresh(batch)
        assert batch.accepted_count == 1
        assert batch.needs_review_count == 2

    def test_candidates_endpoint_backfills_existing_successful_batch(self, client, session):
        teacher = _user(session, "identity_bridge_api_t")
        course = _setup(session, teacher)
        batch = GraphCandidateBatch(
            course_id=course.id,
            initiated_by=teacher.id,
            status=CandidateBatchStatus.SUCCEEDED,
            node_candidate_count=1,
            relation_candidate_count=0,
            node_candidates=[{
                "candidate_id": "gcn-api",
                "label": "接口候选",
                "kind": "concept",
                "confidence": 0.95,
                "anchor_ids": ["ea-api"],
            }],
            relation_candidates=[],
        )
        session.add(batch)
        session.commit()

        response = client.get(
            f"/api/v1/graph/course/{course.id}/candidates",
            headers={"Authorization": f"Bearer {_token(teacher)}"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["target_type"] == "node"
        assert data["items"][0]["target_content"]["id"].startswith("kn_")


class TestReviewedSnapshotAssembly:
    def _reviewed_batch(self, session, teacher):
        course = _setup(session, teacher)
        batch = GraphCandidateBatch(
            course_id=course.id,
            initiated_by=teacher.id,
            status=CandidateBatchStatus.SUCCEEDED,
            node_candidate_count=2,
            relation_candidate_count=1,
            node_candidates=[
                {"candidate_id": "gcn-assembly-a", "label": "变量", "kind": "concept", "anchor_ids": ["anchor-a"]},
                {"candidate_id": "gcn-assembly-b", "label": "函数", "kind": "concept", "anchor_ids": ["anchor-b"]},
            ],
            relation_candidates=[{
                "candidate_id": "gcr-assembly-a-b",
                "source_candidate_id": "gcn-assembly-a",
                "target_candidate_id": "gcn-assembly-b",
                "relation_type": "prerequisite_of",
                "anchor_ids": ["anchor-a", "anchor-b"],
            }],
        )
        session.add(batch)
        session.commit()
        session.refresh(batch)
        bridge_candidate_batch(session, batch=batch)
        session.commit()
        reviews = session.exec(
            select(GraphNodeReview).where(GraphNodeReview.candidate_batch_id == batch.batch_id)
        ).all()
        nodes = session.exec(
            select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course.id)
        ).all()
        evidence = []
        for node in nodes:
            item = create_evidence(
                session,
                course_id=course.id,
                page_number=1,
                text_snippet=f"正式证据 {node.title}",
            )
            item.node_id = node.id
            session.add(item)
            evidence.append(item)
        relation_evidence = create_evidence(
            session,
            course_id=course.id,
            page_number=2,
            text_snippet="关系正式证据",
        )
        session.commit()
        for review in reviews:
            if review.target_type == "node":
                node_evidence = next(item for item in evidence if item.node_id == review.identity_node_id)
                transition_review(
                    session, course.id, review.id,
                    new_decision="accepted", reviewer_id=teacher.id,
                    evidence_ids=[node_evidence.evidence_id],
                )
            else:
                transition_review(
                    session, course.id, review.id,
                    new_decision="accepted", reviewer_id=teacher.id,
                    evidence_ids=[relation_evidence.evidence_id],
                )
        return course, batch

    def test_assembles_accepted_reviews_into_stable_published_snapshot(self, session):
        teacher = _user(session, "reviewed_publish_t")
        course, batch = self._reviewed_batch(session, teacher)

        snapshot, assembly = publish_reviewed_snapshot(
            session, course_id=course.id, user_id=teacher.id,
        )

        assert snapshot.is_active is True
        assert snapshot.node_count == 2
        assert snapshot.relation_count == 1
        assert assembly["batch_id"] == batch.batch_id
        assert all(item["id"].startswith("kn_") for item in snapshot.nodes)
        assert all(item["evidence_ids"] for item in snapshot.nodes + snapshot.relations)
        assert all(review.snapshot_id == snapshot.snapshot_id for review in session.exec(
            select(GraphNodeReview).where(GraphNodeReview.course_id == course.id)
        ).all())
        assert all(node.status == CourseKnowledgeNodeStatus.PUBLISHED for node in session.exec(
            select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == course.id)
        ).all())
        same_snapshot, second_assembly = publish_reviewed_snapshot(
            session, course_id=course.id, user_id=teacher.id,
        )
        assert same_snapshot.snapshot_id == snapshot.snapshot_id
        assert second_assembly["idempotent"] is True
        assert len(list_snapshots(session, course.id)) == 1

    def test_publish_gate_rejects_pending_review_before_evidence_check(self, session):
        teacher = _user(session, "reviewed_publish_gate_t")
        course, _ = self._reviewed_batch(session, teacher)
        review = session.exec(select(GraphNodeReview).where(
            GraphNodeReview.course_id == course.id,
            GraphNodeReview.decision == "accepted",
        )).first()
        assert review is not None
        review.decision = "proposed"
        session.add(review)
        session.commit()
        with pytest.raises(GraphAssemblyError, match="未完成审核") as error:
            publish_reviewed_snapshot(session, course_id=course.id, user_id=teacher.id)
        assert error.value.code == "REVIEW_INCOMPLETE"

    def test_publish_gate_rejects_relation_without_active_evidence(self, session):
        teacher = _user(session, "reviewed_publish_evidence_t")
        course, _ = self._reviewed_batch(session, teacher)
        relation = session.exec(select(GraphNodeReview).where(
            GraphNodeReview.course_id == course.id,
            GraphNodeReview.target_type == "relation",
        )).first()
        assert relation is not None
        relation.evidence_ids = []
        session.add(relation)
        session.commit()
        with pytest.raises(GraphAssemblyError, match="缺少有效 Evidence") as error:
            publish_reviewed_snapshot(session, course_id=course.id, user_id=teacher.id)
        assert error.value.code == "EVIDENCE_REQUIRED"

    def test_publish_reviewed_endpoint_returns_assembly_metadata(self, client, session):
        teacher = _user(session, "reviewed_publish_api_t")
        course, batch = self._reviewed_batch(session, teacher)
        response = client.post(
            f"/api/v1/graph/course/{course.id}/publish-reviewed",
            json={"label": "教师审核版"},
            headers={"Authorization": f"Bearer {_token(teacher)}"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["assembly"]["source"] == "reviewed_candidates"
        assert data["assembly"]["batch_id"] == batch.batch_id
        assert data["node_count"] == 2


class TestBatch3ReviewStateMachine:
    """批次3：候选审核状态机、冲突列表、版本对比"""

    def test_list_review_candidates_returns_proposed_and_needs_review(self, session):
        """候选列表默认返回 proposed 与 needs_review"""
        teacher = _user(session, "b3_cand_t")
        course = _setup(session, teacher)
        r1 = GraphNodeReview(
            course_id=course.id, target_id="n1", target_type="node",
            decision="proposed", reviewer=teacher.id,
        )
        r2 = GraphNodeReview(
            course_id=course.id, target_id="n2", target_type="node",
            decision="needs_review", reviewer=teacher.id,
        )
        r3 = GraphNodeReview(
            course_id=course.id, target_id="n3", target_type="node",
            decision="accepted", reviewer=teacher.id,
        )
        session.add_all([r1, r2, r3]); session.commit()
        candidates = list_review_candidates(session, course.id)
        ids = {c.target_id for c in candidates}
        assert ids == {"n1", "n2"}  # accepted 不在默认候选列表

    def test_list_review_candidates_filter_by_decision(self, session):
        """按状态筛选候选"""
        teacher = _user(session, "b3_filt_t")
        course = _setup(session, teacher)
        r1 = GraphNodeReview(
            course_id=course.id, target_id="n1", target_type="node",
            decision="accepted", reviewer=teacher.id,
        )
        session.add(r1); session.commit()
        candidates = list_review_candidates(session, course.id, decision="accepted")
        assert len(candidates) == 1
        assert candidates[0].target_id == "n1"

    def test_transition_proposed_to_accepted(self, session):
        """proposed -> accepted 状态推进"""
        teacher = _user(session, "b3_trans_t")
        course = _setup(session, teacher)
        ev = create_evidence(session, course_id=course.id, text_snippet="证据内容")
        review = GraphNodeReview(
            course_id=course.id, target_id="n1", target_type="node",
            decision="proposed", reviewer=teacher.id,
        )
        session.add(review); session.commit(); session.refresh(review)
        updated = transition_review(
            session, course.id, review.id,
            new_decision="accepted", reviewer_id=teacher.id,
            evidence_ids=[ev.evidence_id],
        )
        assert updated.decision == "accepted"
        assert updated.evidence_ids == [ev.evidence_id]

    def test_transition_rejects_invalid_evidence(self, session):
        """推进到 accepted 时拒绝跨课程/无效 Evidence"""
        teacher = _user(session, "b3_invev_t")
        course = _setup(session, teacher)
        review = GraphNodeReview(
            course_id=course.id, target_id="n1", target_type="node",
            decision="proposed", reviewer=teacher.id,
        )
        session.add(review); session.commit(); session.refresh(review)
        with pytest.raises(ValueError, match="无效或跨课程"):
            transition_review(
                session, course.id, review.id,
                new_decision="accepted", reviewer_id=teacher.id,
                evidence_ids=["fake-evidence-id"],
            )

    def test_transition_terminal_state_cannot_revert(self, session):
        """终态不可回退（accepted 不能回到 proposed）"""
        teacher = _user(session, "b3_term_t")
        course = _setup(session, teacher)
        review = GraphNodeReview(
            course_id=course.id, target_id="n1", target_type="node",
            decision="accepted", reviewer=teacher.id,
        )
        session.add(review); session.commit(); session.refresh(review)
        with pytest.raises(ValueError, match="终态不可回退"):
            transition_review(
                session, course.id, review.id,
                new_decision="proposed", reviewer_id=teacher.id,
            )

    def test_transition_cross_course_review_rejected(self, session):
        """跨课程审核记录不可推进"""
        t1 = _user(session, "b3_xc_t1")
        t2 = _user(session, "b3_xc_t2")
        c1 = _setup(session, t1)
        c2 = _setup(session, t2)
        review = GraphNodeReview(
            course_id=c1.id, target_id="n1", target_type="node",
            decision="proposed", reviewer=t1.id,
        )
        session.add(review); session.commit(); session.refresh(review)
        with pytest.raises(ValueError, match="不存在或不属于本课程"):
            transition_review(
                session, c2.id, review.id,
                new_decision="accepted", reviewer_id=t2.id,
            )


class TestBatch3SnapshotDiff:
    """批次3：版本对比"""

    def test_diff_detects_added_and_removed_nodes(self, session):
        """版本对比检测新增/删除节点"""
        teacher = _user(session, "b3_diff_t")
        course = _setup(session, teacher)
        s1 = publish_snapshot(
            session, course_id=course.id,
            nodes=[{"node_id": "n1"}, {"node_id": "n2"}], relations=[],
            user_id=teacher.id,
        )
        s2 = publish_snapshot(
            session, course_id=course.id,
            nodes=[{"node_id": "n2"}, {"node_id": "n3"}], relations=[],
            user_id=teacher.id,
        )
        diff = diff_snapshots(session, course.id, s1.snapshot_id, s2.snapshot_id)
        added_ids = {n["node_id"] for n in diff["nodes"]["added"]}
        removed_ids = {n["node_id"] for n in diff["nodes"]["removed"]}
        assert added_ids == {"n3"}
        assert removed_ids == {"n1"}

    def test_diff_detects_modified_nodes(self, session):
        """版本对比检测节点内容变更"""
        teacher = _user(session, "b3_mod_t")
        course = _setup(session, teacher)
        s1 = publish_snapshot(
            session, course_id=course.id,
            nodes=[{"node_id": "n1", "label": "旧标签"}], relations=[],
            user_id=teacher.id,
        )
        s2 = publish_snapshot(
            session, course_id=course.id,
            nodes=[{"node_id": "n1", "label": "新标签"}], relations=[],
            user_id=teacher.id,
        )
        diff = diff_snapshots(session, course.id, s1.snapshot_id, s2.snapshot_id)
        assert len(diff["nodes"]["modified"]) == 1
        assert diff["nodes"]["modified"][0]["from"]["label"] == "旧标签"
        assert diff["nodes"]["modified"][0]["to"]["label"] == "新标签"

    def test_diff_cross_course_rejected(self, session):
        """跨课程快照对比被拒绝"""
        t1 = _user(session, "b3_diff_xc_t1")
        t2 = _user(session, "b3_diff_xc_t2")
        c1 = _setup(session, t1)
        c2 = _setup(session, t2)
        s1 = publish_snapshot(
            session, course_id=c1.id, nodes=[{"node_id": "n1"}], relations=[],
            user_id=t1.id,
        )
        s2 = publish_snapshot(
            session, course_id=c2.id, nodes=[{"node_id": "n1"}], relations=[],
            user_id=t2.id,
        )
        with pytest.raises(ValueError, match="不存在或不属于本课程"):
            diff_snapshots(session, c1.id, s1.snapshot_id, s2.snapshot_id)


class TestBatch3PrerequisiteNodes:
    """批次3：一跳先修/后继节点查询"""

    def test_get_prerequisite_nodes_incoming(self, session):
        """获取先修节点（incoming）"""
        teacher = _user(session, "b3_prereq_t")
        course = _setup(session, teacher)
        evidence = create_evidence(
            session, course_id=course.id, text_snippet="前置知识证据"
        )
        nodes = [
            {"node_id": "n1", "label": "当前知识点"},
            {"node_id": "n2", "label": "前置知识点"},
        ]
        relations = [{
            "relation_id": "r1", "source": "n2", "target": "n1",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }]
        publish_snapshot(
            session, course_id=course.id, nodes=nodes, relations=relations,
            user_id=teacher.id,
        )
        prereqs = get_prerequisite_nodes(session, course.id, "n1", direction="incoming")
        assert len(prereqs) == 1
        assert prereqs[0]["node_id"] == "n2"

    def test_get_prerequisite_nodes_outgoing(self, session):
        """获取后继节点（outgoing）"""
        teacher = _user(session, "b3_succ_t")
        course = _setup(session, teacher)
        evidence = create_evidence(
            session, course_id=course.id, text_snippet="后继关系证据"
        )
        nodes = [
            {"node_id": "n1", "label": "当前知识点"},
            {"node_id": "n2", "label": "后继知识点"},
        ]
        relations = [{
            "relation_id": "r1", "source": "n1", "target": "n2",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }]
        publish_snapshot(
            session, course_id=course.id, nodes=nodes, relations=relations,
            user_id=teacher.id,
        )
        successors = get_prerequisite_nodes(session, course.id, "n1", direction="outgoing")
        assert len(successors) == 1
        assert successors[0]["node_id"] == "n2"

    def test_get_prerequisite_nodes_no_snapshot(self, session):
        """无已发布快照时返回空列表"""
        teacher = _user(session, "b3_nosnap_t")
        course = _setup(session, teacher)
        assert get_prerequisite_nodes(session, course.id, "n1") == []
