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
    CourseEvidenceRecord, GraphSnapshotRecord, GraphNodeReview,
    EvidenceStatus, SnapshotStatus,
)
from app.services.course_access_service import (
    establish_course_access_baseline, activate_student_membership,
)
from app.services.graph_production_service import (
    create_evidence, publish_snapshot, get_active_snapshot,
    list_snapshots, rollback_snapshot, mark_evidence_stale,
    get_evidence_for_node, serialize_snapshot, serialize_evidence,
    graph_target_hash,
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
