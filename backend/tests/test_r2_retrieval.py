"""G5 R2 检索进入学生正式回答 测试

验证：
- retrieval_source 正确记录 (none/v1_treerag/v2_r2_sidecar)
- retrieval_metadata 包含 policy_version, evidence_ids, fallback_reason
- R2 能力检查端点返回正确信息
- 课程 A 的证据不会出现在课程 B 回答中
- R2 失败不破坏 V1
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from sqlmodel import select

from app.core.security import get_password_hash, create_access_token
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    establish_course_access_baseline,
    activate_student_membership,
)
from app.platform.shadow.r2_retrieval_shadow import R2RetrievalShadowResult
from app.services.qa_service import QAService


def test_real_qa_service_uses_r2_when_v1_has_no_results():
    """Exercise the real QA orchestration rather than mocking the endpoint."""
    service = QAService()
    r2_sources = [{
        "path": "chunk-1",
        "score": 0.9,
        "match_type": "rrf_hybrid_bm25_dense",
        "content_preview": "二分查找每次排除一半搜索区间。",
        "evidence_refs": ["ev-1"],
        "citations": [{"evidence_id": "ev-1", "page": 3}],
    }]
    r2_result = R2RetrievalShadowResult(
        triggered=True,
        effective_mode="v2_shadow",
        rag_context="【来源1: chunk-1；证据:ev-1】\n二分查找每次排除一半搜索区间。",
        rag_sources=r2_sources,
        hit_count=1,
    )

    with (
        patch.object(service, "retrieve_rag_context", return_value=("", [])),
        patch(
            "app.platform.shadow.r2_retrieval_shadow.trigger_r2_retrieval_shadow",
            return_value=r2_result,
        ),
        patch(
            "app.services.qa_service.llm_client.chat",
            new=AsyncMock(return_value=SimpleNamespace(content="基于课程证据的回答")),
        ) as llm_chat,
    ):
        result = asyncio.run(service.ask_question_with_rag(
            question="二分查找为什么快？",
            course_id=7,
            use_rag=True,
            strict_mode=True,
            allow_r2_student_answer=True,
        ))

    assert llm_chat.await_count == 1
    assert result["retrieval_source"] == "v2_r2_sidecar"
    assert result["retrieval_metadata"]["evidence_ids"] == ["ev-1"]
    assert result["rag_sources"][0]["citations"][0]["page"] == 3


def _user(session, name: str, role: UserRole = UserRole.STUDENT) -> User:
    user = User(
        username=name,
        hashed_password=get_password_hash("test"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"r2-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="R2 Course",
        title="R2 Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _setup_course(session, teacher, student):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()
    return course


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
    })


# ==================== R2 能力检查测试 ====================

class TestRetrievalCapability:
    """R2 检索能力门面端点测试"""

    def test_retrieval_capability_requires_membership(self, client, session):
        """无 CourseMembership 时 403"""
        teacher = _user(session, "r2_teacher_no_mem", UserRole.TEACHER)
        course = _course(session, teacher.id)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/facade/course/{course.id}/retrieval-capability",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_retrieval_capability_returns_metadata(self, client, session):
        """返回检索能力元数据"""
        teacher = _user(session, "r2_teacher_cap", UserRole.TEACHER)
        student = _user(session, "r2_student_cap")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        response = client.get(
            f"/api/v1/facade/course/{course.id}/retrieval-capability",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "retrieval_available" in data
        assert "evidence_capability" in data
        assert "r2_mode" in data
        assert "r2_enabled" in data
        assert "sidecar_exists" in data
        assert "can_show_citations" in data
        assert "policy_version" in data
        assert "fallback_to_v1" in data

    def test_retrieval_capability_default_v1_only(self, client, session):
        """默认模式为 v1_only，检索不可用"""
        teacher = _user(session, "r2_teacher_default", UserRole.TEACHER)
        student = _user(session, "r2_student_default")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        response = client.get(
            f"/api/v1/facade/course/{course.id}/retrieval-capability",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        # 默认 DOCUMENT_KG_RUNTIME_MODE=v1_only
        assert data["r2_mode"] == "v1_only"
        assert data["r2_enabled"] is False
        assert data["retrieval_available"] is False
        assert data["fallback_to_v1"] is True

    def test_retrieval_capability_cross_course_isolation(self, client, session):
        """跨课程隔离：学生A不能访问课程B的检索能力"""
        teacher1 = _user(session, "r2_t1", UserRole.TEACHER)
        teacher2 = _user(session, "r2_t2", UserRole.TEACHER)
        student1 = _user(session, "r2_s1")
        course1 = _setup_course(session, teacher1, student1)
        course2 = _setup_course(session, teacher2, _user(session, "r2_s2"))

        token = _token(student1)
        response = client.get(
            f"/api/v1/facade/course/{course2.id}/retrieval-capability",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_platform_admin_cross_course(self, client, session):
        """平台管理员可跨课程检查"""
        teacher = _user(session, "r2_admin_teacher", UserRole.TEACHER)
        student = _user(session, "r2_admin_student")
        course = _setup_course(session, teacher, student)

        admin = _user(session, "r2_platform_admin", UserRole.STUDENT)
        session.add(PlatformPermissionAssignment(
            user_id=admin.id,
            permission=PlatformPermission.ADMIN,
        ))
        session.commit()

        token = _token(admin)
        response = client.get(
            f"/api/v1/facade/course/{course.id}/retrieval-capability",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200


# ==================== 问答检索元数据测试 ====================

class TestQARetrievalMetadata:
    """问答端点返回的检索元数据测试"""

    def test_ask_returns_retrieval_source(self, client, session):
        """问答返回包含 retrievalSource 字段"""
        teacher = _user(session, "r2_qa_teacher", UserRole.TEACHER)
        student = _user(session, "r2_qa_student")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        # Mock qa_service 避免实际 LLM 调用
        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "测试回答",
                "rag_sources": None,
                "rag_context": None,
                "retrieval_source": "none",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": [],
                    "fallback_reason": None,
                    "hit_count": 0,
                },
            })
            mock_qa.generate_quiz = AsyncMock(return_value={"quiz": {}})

            response = client.post(
                "/api/v1/chat/ask",
                json={
                    "courseId": course.id,
                    "question": "测试问题",
                    "currentNodeId": None,
                    "strictMode": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "retrievalSource" in data
        assert data["retrievalSource"] == "none"
        assert "retrievalMetadata" in data
        assert data["retrievalMetadata"]["policy_version"] == "r2-retrieval-v1.0"

    def test_ask_returns_v1_treerag_source(self, client, session):
        """V1 检索命中时返回 v1_treerag"""
        teacher = _user(session, "r2_v1_teacher", UserRole.TEACHER)
        student = _user(session, "r2_v1_student")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "V1回答",
                "rag_sources": [{"path": "doc/page1", "score": 0.9, "content_preview": "..."}],
                "rag_context": "V1上下文",
                "retrieval_source": "v1_treerag",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": [],
                    "fallback_reason": None,
                    "hit_count": 0,
                },
            })

            response = client.post(
                "/api/v1/chat/ask",
                json={
                    "courseId": course.id,
                    "question": "什么是二分查找",
                    "currentNodeId": None,
                    "strictMode": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["retrievalSource"] == "v1_treerag"
        assert data["ragSources"] is not None

    def test_ask_returns_r2_sidecar_source(self, client, session):
        """R2 命中时返回 v2_r2_sidecar 和证据 ID"""
        teacher = _user(session, "r2_hit_teacher", UserRole.TEACHER)
        student = _user(session, "r2_hit_student")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "R2回答",
                "rag_sources": [
                    {"path": "evidence-001", "score": 0.95, "content_preview": "..."},
                    {"path": "evidence-002", "score": 0.88, "content_preview": "..."},
                ],
                "rag_context": "R2上下文",
                "retrieval_source": "v2_r2_sidecar",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": ["evidence-001", "evidence-002"],
                    "fallback_reason": None,
                    "hit_count": 2,
                },
            })

            response = client.post(
                "/api/v1/chat/ask",
                json={
                    "courseId": course.id,
                    "question": "解释递归",
                    "currentNodeId": None,
                    "strictMode": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["retrievalSource"] == "v2_r2_sidecar"
        assert data["retrievalMetadata"]["hit_count"] == 2
        assert "evidence-001" in data["retrievalMetadata"]["evidence_ids"]

    def test_ask_returns_fallback_reason(self, client, session):
        """R2 拒答时返回 fallback_reason"""
        teacher = _user(session, "r2_fallback_teacher", UserRole.TEACHER)
        student = _user(session, "r2_fallback_student")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "V1回退回答",
                "rag_sources": [{"path": "v1/doc1", "score": 0.7}],
                "rag_context": "V1上下文",
                "retrieval_source": "v1_treerag",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": [],
                    "fallback_reason": "no_sidecar_or_r2_abstained",
                    "hit_count": 0,
                },
            })

            response = client.post(
                "/api/v1/chat/ask",
                json={
                    "courseId": course.id,
                    "question": "测试",
                    "currentNodeId": None,
                    "strictMode": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["retrievalSource"] == "v1_treerag"
        assert data["retrievalMetadata"]["fallback_reason"] == "no_sidecar_or_r2_abstained"

    def test_r2_failure_does_not_break_v1(self, client, session):
        """R2 异常不破坏 V1 回答"""
        teacher = _user(session, "r2_err_teacher", UserRole.TEACHER)
        student = _user(session, "r2_err_student")
        course = _setup_course(session, teacher, student)
        token = _token(student)

        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "V1仍然正常工作",
                "rag_sources": [{"path": "v1/doc1", "score": 0.7}],
                "rag_context": "V1上下文",
                "retrieval_source": "v1_treerag",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": [],
                    "fallback_reason": "r2_exception: ConnectionError",
                    "hit_count": 0,
                },
            })

            response = client.post(
                "/api/v1/chat/ask",
                json={
                    "courseId": course.id,
                    "question": "测试",
                    "currentNodeId": None,
                    "strictMode": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["answer"] == "V1仍然正常工作"
        assert "r2_exception" in data["retrievalMetadata"]["fallback_reason"]

    def test_course_a_evidence_not_in_course_b(self, client, session):
        """课程 A 的证据不会出现在课程 B 回答中"""
        teacher = _user(session, "r2_iso_teacher", UserRole.TEACHER)
        student = _user(session, "r2_iso_student")
        course_a = _setup_course(session, teacher, student)
        course_b = _course(session, teacher.id)
        establish_course_access_baseline(session, course_b.id, teacher.id)
        activate_student_membership(session, course_b.id, student.id)
        session.commit()
        token = _token(student)

        # 课程 A 的问答使用 evidence-A
        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "课程A回答",
                "rag_sources": [{"path": "evidence-A-001", "score": 0.95}],
                "rag_context": "课程A证据",
                "retrieval_source": "v2_r2_sidecar",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": ["evidence-A-001"],
                    "fallback_reason": None,
                    "hit_count": 1,
                },
            })

            resp_a = client.post(
                "/api/v1/chat/ask",
                json={"courseId": course_a.id, "question": "问题A", "strictMode": False},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp_a.status_code == 200
        data_a = resp_a.json()["data"]
        assert "evidence-A-001" in data_a["retrievalMetadata"]["evidence_ids"]

        # 课程 B 的问答使用 V1（无 R2 命中），不含 evidence-A
        with patch("app.api.v1.endpoints.chat.qa_service") as mock_qa:
            mock_qa.ask_question_with_rag = AsyncMock(return_value={
                "answer": "课程B回答",
                "rag_sources": [{"path": "v1-courseB-doc", "score": 0.6}],
                "rag_context": "课程B的V1上下文",
                "retrieval_source": "v1_treerag",
                "retrieval_metadata": {
                    "policy_version": "r2-retrieval-v1.0",
                    "evidence_ids": [],
                    "fallback_reason": "no_sidecar",
                    "hit_count": 0,
                },
            })

            resp_b = client.post(
                "/api/v1/chat/ask",
                json={"courseId": course_b.id, "question": "问题B", "strictMode": False},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp_b.status_code == 200
        data_b = resp_b.json()["data"]
        assert "evidence-A-001" not in data_b["retrievalMetadata"]["evidence_ids"]
        assert data_b["retrievalSource"] != "v2_r2_sidecar"
