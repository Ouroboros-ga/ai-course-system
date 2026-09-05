"""M2-B1：Nexus 内部检索端点契约（fail-closed 令牌 + Course Access 门控）。

用 MockTransport 级别的替身隔离外部依赖：课程证据检索 monkeypatch
``SqlLanceCourseKnowledgeProvider.search_evidence``（不触 lance/PG 真数据），
CS 检索 monkeypatch ``search_nodes``（不触知识库文件）。
"""

import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import nexus_internal
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
)
from app.models.course_model import Course
from app.core.config import settings

AUTH = {"Authorization": "Bearer internal-token-1"}
USER = {"X-Nexus-User-Id": ""}


@pytest.fixture
def internal_configured(monkeypatch):
    monkeypatch.setattr(nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")


@pytest.fixture
def enrolled_course(session, student_user):
    """学生已入课且具备知识读取能力的课程。"""
    course = Course(
        fanya_course_id=f"nexus-internal-{uuid.uuid4().hex[:6]}",
        fanya_course_name="Nexus Internal",
        title="Nexus Internal",
        teacher_id=student_user.id,
    )
    session.add(course)
    session.flush()
    session.add(CourseMembership(
        course_id=course.id,
        user_id=student_user.id,
        role=CourseRole.STUDENT,
    ))
    session.add(CourseCapability(
        course_id=course.id,
        knowledge_graph=True,
    ))
    session.commit()
    session.refresh(course)
    return course


def _fake_evidence_result():
    item = SimpleNamespace(
        evidence_ids=["ev-1"],
        document_id="doc-9",
        page_number=3,
        content="快速排序平均 O(n log n)。",
        node_key="kn_1",
        knowledge_node_id=11,
        citation_ids=["c1", "c2"],
        retrieval_sources=[],
    )
    bundle = SimpleNamespace(bundle_id="b1", graph_snapshot_id="g1", vector_index_id="v1")
    return SimpleNamespace(items=[item], bundle=bundle)


def test_course_evidence_fails_closed_without_token(client):
    response = client.get(
        "/api/v1/nexus-internal/course-evidence",
        params={"course_id": 1, "q": "排序"},
        headers={"X-Nexus-User-Id": "1"},
    )
    assert response.status_code == 503
    assert response.json()["message"] == "NEXUS_INTERNAL_NOT_CONFIGURED"


def test_course_evidence_rejects_wrong_token(client, internal_configured):
    response = client.get(
        "/api/v1/nexus-internal/course-evidence",
        params={"course_id": 1, "q": "排序"},
        headers={"Authorization": "Bearer wrong", "X-Nexus-User-Id": "1"},
    )
    assert response.status_code == 401
    assert response.json()["message"] == "NEXUS_INTERNAL_UNAUTHORIZED"


def test_course_evidence_requires_user_identity(client, internal_configured):
    response = client.get(
        "/api/v1/nexus-internal/course-evidence",
        params={"course_id": 1, "q": "排序"},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_course_evidence_forbids_user_without_access(
    client, session, internal_configured, student_user, teacher_user
):
    """未入课的学生检索他人在课程 → 403（Course Access v1 门控生效）。"""
    course = Course(
        fanya_course_id=f"locked-{uuid.uuid4().hex[:6]}",
        fanya_course_name="Locked",
        title="Locked",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    response = client.get(
        "/api/v1/nexus-internal/course-evidence",
        params={"course_id": course.id, "q": "排序"},
        headers={**AUTH, "X-Nexus-User-Id": str(student_user.id)},
    )
    assert response.status_code == 403
    assert response.json()["message"] == "NEXUS_INTERNAL_FORBIDDEN"


def test_course_evidence_returns_structured_items(
    client, internal_configured, enrolled_course, student_user, monkeypatch
):
    def fake_search(self, course_id, q, *, top_k=5, node_keys=()):
        return _fake_evidence_result()

    monkeypatch.setattr(
        nexus_internal.SqlLanceCourseKnowledgeProvider, "search_evidence", fake_search
    )
    response = client.get(
        "/api/v1/nexus-internal/course-evidence",
        params={"course_id": enrolled_course.id, "q": "快速排序"},
        headers={**AUTH, "X-Nexus-User-Id": str(student_user.id)},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["authority"] == "course"
    assert body["items"][0]["evidence_id"] == "ev-1"
    assert body["items"][0]["citation_ids"] == ["c1", "c2"]
    assert body["items"][0]["text"].startswith("快速排序")


def test_cs_knowledge_returns_authority_items(
    client, internal_configured, student_user, monkeypatch
):
    monkeypatch.setattr(
        nexus_internal,
        "search_nodes",
        lambda q, top_k=5: [
            {
                "id": "kb-hash-1",
                "name": "哈希表",
                "node_type": "concept",
                "definition": "平均 O(1) 查找的键值映射结构。",
                "source": "教材第 6 章",
                "course": "数据结构与算法",
            }
        ],
    )
    response = client.get(
        "/api/v1/nexus-internal/cs-knowledge",
        params={"q": "哈希表"},
        headers={**AUTH, "X-Nexus-User-Id": str(student_user.id)},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["authority"] == "cs_kb"
    assert body["items"][0]["name"] == "哈希表"
    assert body["items"][0]["source"] == "教材第 6 章"


def test_cs_knowledge_rejects_without_user(client, internal_configured):
    response = client.get(
        "/api/v1/nexus-internal/cs-knowledge",
        params={"q": "哈希表"},
        headers=AUTH,
    )
    assert response.status_code == 400
