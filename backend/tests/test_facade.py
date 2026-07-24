"""Phase A 门面层 ViewModel 契约、ID 一致性与权限隔离测试。

测试要点：
1. ID 一致性：citation/locate、facade citation、facade overview 返回的 document_id
   均为 DocumentArtifact.document_id (UUID)，而非 DoclingDocument.id (整数)，
   且三者返回值相同。
2. 权限隔离：无 membership 时 403、学生可访问 overview、学生仅看 published quiz、
   教师跨课程隔离、平台管理员跨课程。
3. ViewModel 结构：overview 包含 capabilities/access/structure，
   citation 包含 return_anchor，quiz 每题包含 return_anchor。

使用 conftest.py 的 session / client fixture 和统一权限解析器，
不依赖旧 teacher_id 或 StudentEnrollment。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import (
    Course,
    CourseScript,
    CourseStatus,
    DoclingDocument,
    DoclingText,
    ScriptNode,
    ScriptNodeType,
)
from app.models.document_artifact_model import DocumentArtifact
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
    resolve_course_access,
)


# ==================== 常量与辅助函数 ====================

FACADE = "/api/v1/facade"
CITATIONS = "/api/v1/citations"

# UUID v4 格式正则（忽略大小写）
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _user(session, name, role=UserRole.STUDENT):
    """创建测试用户并提交。"""
    user = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id):
    """创建测试课程并提交。"""
    course = Course(
        fanya_course_id=f"fac-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="Facade Course",
        title="Facade Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _token(user):
    """为用户生成 JWT 访问令牌。"""
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token):
    """构造 Bearer 认证头。"""
    return {"Authorization": f"Bearer {token}"}


def _artifact(session, course_id, document_id=None, file_name="lecture.pdf"):
    """创建文档产物（DocumentArtifact），document_id 为 UUID 字符串。"""
    if document_id is None:
        document_id = str(uuid.uuid4())
    artifact = DocumentArtifact(
        document_id=document_id,
        course_id=course_id,
        file_name=file_name,
        mime_type="application/pdf",
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    return artifact


def _docling_doc(session, course_id, doc_name="test.pdf"):
    """创建 DoclingDocument（整数主键，不应作为 document_id 暴露）。"""
    doc = DoclingDocument(
        course_id=course_id,
        doc_name=doc_name,
        origin_filename=doc_name,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _docling_text(session, doc_id, page_no=1, text="测试原文片段内容", sort_order=0):
    """创建 DoclingText 文本片段。"""
    t = DoclingText(
        doc_id=doc_id,
        self_ref=f"#/texts/{sort_order}",
        text=text,
        page_no=page_no,
        sort_order=sort_order,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def _script(session, course_id, user_id):
    """创建 CourseScript（激活版本）。"""
    script = CourseScript(
        course_id=course_id,
        version=1,
        script_content={"nodes": []},
        is_active=True,
        created_by=user_id,
    )
    session.add(script)
    session.commit()
    session.refresh(script)
    return script


def _node(session, script_id, node_index=0, title="测试节点",
          page_start=1, page_end=1, chapter_id=None):
    """创建 ScriptNode。"""
    node = ScriptNode(
        script_id=script_id,
        node_index=node_index,
        node_type=ScriptNodeType.LECTURE,
        title=title,
        content="节点讲解内容",
        page_start=page_start,
        page_end=page_end,
        chapter_id=chapter_id,
    )
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def _question(session, *, question_text="测试题目", answer="测试答案",
              course_id=None, status=QuestionStatus.UNASSIGNED,
              category="测试分类", generated_by="excel_import",
              knowledge_node_ids=None, created_by=None):
    """创建测试题目并提交。"""
    item = QuestionBankItem(
        question_text=question_text,
        answer=answer,
        options={},
        similar_questions=[],
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM,
        category=category,
        course_id=course_id,
        knowledge_node_ids=knowledge_node_ids or [],
        prerequisite_node_ids=[],
        status=status,
        version=1,
        prev_version_id=None,
        is_latest=True,
        generated_by=generated_by,
        created_by=created_by,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _setup_course_with_doc(session, teacher):
    """创建完整课程（含 DocumentArtifact/DoclingDocument/CourseScript/ScriptNode）。

    返回 (course, artifact, docling, script, node)。
    """
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    artifact = _artifact(session, course.id, document_id=str(uuid.uuid4()))
    docling = _docling_doc(session, course.id)
    _docling_text(session, docling.id, page_no=1, text="第一页原文片段")
    script = _script(session, course.id, teacher.id)
    node = _node(session, script.id, page_start=1, page_end=1)
    session.commit()
    return course, artifact, docling, script, node


# ==================== ID 一致性测试（核心验收） ====================

def test_citation_locate_returns_uuid_document_id(client, session):
    """citation/locate 端点返回的 document_id 应为 DocumentArtifact.document_id (UUID)，
    而非 DoclingDocument.id (整数)。"""
    teacher = _user(session, "fac_locate_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(
        f"{CITATIONS}/locate",
        params={"course_id": course.id, "node_id": node.id},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]

    # document_id 等于 DocumentArtifact.document_id（UUID 字符串）
    assert data["document_id"] == artifact.document_id
    assert UUID_RE.match(str(data["document_id"]))

    # 不等于 DoclingDocument.id（整数主键）
    assert str(data["document_id"]) != str(docling.id)


def test_facade_citation_returns_uuid_document_id(client, session):
    """facade citation 端点返回的 document_id 也是 UUID。"""
    teacher = _user(session, "fac_fcite_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(
        f"{FACADE}/course/{course.id}/citation/{node.id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["document_id"] == artifact.document_id
    assert UUID_RE.match(str(data["document_id"]))


def test_facade_overview_returns_uuid_document_id(client, session):
    """facade overview 端点返回的 document_id 也是 UUID。"""
    teacher = _user(session, "fac_fover_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(
        f"{FACADE}/course/{course.id}/overview",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["document_id"] == artifact.document_id
    assert UUID_RE.match(str(data["document_id"]))


def test_document_id_consistent_across_endpoints(client, session):
    """facade overview, facade citation, citation/locate 三者返回的 document_id 相同。"""
    teacher = _user(session, "fac_consist_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)

    resp_overview = client.get(
        f"{FACADE}/course/{course.id}/overview",
        headers=_auth(token),
    )
    resp_citation = client.get(
        f"{FACADE}/course/{course.id}/citation/{node.id}",
        headers=_auth(token),
    )
    resp_locate = client.get(
        f"{CITATIONS}/locate",
        params={"course_id": course.id, "node_id": node.id},
        headers=_auth(token),
    )

    assert resp_overview.status_code == 200
    assert resp_citation.status_code == 200
    assert resp_locate.status_code == 200

    overview_id = resp_overview.json()["data"]["document_id"]
    citation_id = resp_citation.json()["data"]["document_id"]
    locate_id = resp_locate.json()["data"]["document_id"]

    # 三者一致，且均为 DocumentArtifact.document_id (UUID)
    assert overview_id == citation_id == locate_id == artifact.document_id
    assert UUID_RE.match(str(overview_id))


# ==================== 门面层权限测试 ====================

def test_facade_endpoints_require_membership(client, session):
    """无 CourseMembership 时所有 facade 端点返回 403。

    仅在 Course.teacher_id 上设置了教师 ID，但不创建 CourseMembership 和
    CourseCapability，则权限解析返回无权限，所有门面端点返回 403。
    """
    teacher = _user(session, "fac_nomem_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    # 故意不调用 establish_course_access_baseline
    session.commit()

    token = _token(teacher)

    # facade overview -> 403（需要 course.view）
    resp = client.get(f"{FACADE}/course/{course.id}/overview", headers=_auth(token))
    assert resp.status_code == 403

    # facade citation -> 403（需要 course.citation.read，权限先于节点查找）
    resp = client.get(f"{FACADE}/course/{course.id}/citation/1", headers=_auth(token))
    assert resp.status_code == 403

    # facade quiz -> 403（需要 question_bank.read）
    resp = client.get(f"{FACADE}/course/{course.id}/quiz", headers=_auth(token))
    assert resp.status_code == 403

    # citation/locate -> 403（需要 course.citation.read）
    resp = client.get(
        f"{CITATIONS}/locate",
        params={"course_id": course.id},
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_student_can_access_overview(client, session):
    """学生有 course.view 权限，可访问 overview。"""
    teacher = _user(session, "fac_stuover_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)
    student = _user(session, "fac_stuover_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    token = _token(student)
    resp = client.get(f"{FACADE}/course/{course.id}/overview", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["role"] == "student"


def test_student_only_sees_published_quiz(client, session):
    """facade quiz 端点对学生只返回 published 题目。"""
    teacher = _user(session, "fac_stuquiz_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "fac_stuquiz_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    q_pub = _question(
        session, question_text="已发布题目", course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )
    _question(
        session, question_text="自动接受题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )
    _question(
        session, question_text="已拒绝题目", course_id=course.id,
        status=QuestionStatus.REJECTED,
    )

    token = _token(student)
    resp = client.get(f"{FACADE}/course/{course.id}/quiz", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 学生只看到 published
    assert data["total"] == 1
    assert data["items"][0]["question_id"] == q_pub.id
    assert data["items"][0]["status"] == "published"


def test_teacher_can_see_all_quiz(client, session):
    """教师有 question_bank.manage 权限，可看到所有状态的题目。"""
    teacher = _user(session, "fac_teachquiz_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    _question(
        session, question_text="已发布题目", course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )
    _question(
        session, question_text="自动接受题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )
    _question(
        session, question_text="已拒绝题目", course_id=course.id,
        status=QuestionStatus.REJECTED,
    )

    token = _token(teacher)
    resp = client.get(f"{FACADE}/course/{course.id}/quiz", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 教师可看到所有状态
    assert data["total"] == 3
    statuses = {item["status"] for item in data["items"]}
    assert "published" in statuses
    assert "auto_accepted" in statuses
    assert "rejected" in statuses


def test_teacher_cannot_access_other_teacher_facade(client, session):
    """教师 A 不能访问教师 B 课程的 facade 端点（跨课程隔离）。"""
    teacher_a = _user(session, "fac_iso_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "fac_iso_teacher_b", UserRole.TEACHER)

    course_a = _course(session, teacher_a.id)
    course_b = _course(session, teacher_b.id)
    establish_course_access_baseline(session, course_a.id, teacher_a.id)
    establish_course_access_baseline(session, course_b.id, teacher_b.id)

    # 课程 B 创建完整文档与脚本
    _artifact(session, course_b.id, document_id=str(uuid.uuid4()))
    docling_b = _docling_doc(session, course_b.id)
    _docling_text(session, docling_b.id, page_no=1, text="课程B原文")
    script_b = _script(session, course_b.id, teacher_b.id)
    node_b = _node(session, script_b.id, page_start=1, page_end=1)
    session.commit()

    token_a = _token(teacher_a)

    # 教师A访问课程B overview -> 403
    resp = client.get(
        f"{FACADE}/course/{course_b.id}/overview", headers=_auth(token_a)
    )
    assert resp.status_code == 403

    # 教师A访问课程B citation -> 403
    resp = client.get(
        f"{FACADE}/course/{course_b.id}/citation/{node_b.id}",
        headers=_auth(token_a),
    )
    assert resp.status_code == 403

    # 教师A访问课程B quiz -> 403
    resp = client.get(
        f"{FACADE}/course/{course_b.id}/quiz", headers=_auth(token_a)
    )
    assert resp.status_code == 403

    # 教师A访问课程B citation/locate -> 403
    resp = client.get(
        f"{CITATIONS}/locate",
        params={"course_id": course_b.id, "node_id": node_b.id},
        headers=_auth(token_a),
    )
    assert resp.status_code == 403


def test_platform_admin_can_access_cross_course(client, session):
    """持有 platform.admin 的用户可跨课程访问 facade 端点。"""
    teacher = _user(session, "fac_admin_course_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    # 平台管理员（无课程成员关系，全局角色为 STUDENT）
    admin = _user(session, "fac_admin_user", UserRole.STUDENT)
    session.add(PlatformPermissionAssignment(
        user_id=admin.id, permission=PlatformPermission.ADMIN,
    ))
    session.commit()

    token = _token(admin)

    # overview -> 200
    resp = client.get(f"{FACADE}/course/{course.id}/overview", headers=_auth(token))
    assert resp.status_code == 200

    # citation -> 200
    resp = client.get(
        f"{FACADE}/course/{course.id}/citation/{node.id}", headers=_auth(token)
    )
    assert resp.status_code == 200

    # quiz -> 200
    resp = client.get(f"{FACADE}/course/{course.id}/quiz", headers=_auth(token))
    assert resp.status_code == 200

    # citation/locate -> 200
    resp = client.get(
        f"{CITATIONS}/locate",
        params={"course_id": course.id, "node_id": node.id},
        headers=_auth(token),
    )
    assert resp.status_code == 200


# ==================== ViewModel 结构测试 ====================

def test_overview_contains_capabilities(client, session):
    """overview 返回中有 capabilities 字段。"""
    teacher = _user(session, "fac_cap_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(f"{FACADE}/course/{course.id}/overview", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "capabilities" in data
    assert isinstance(data["capabilities"], dict)
    assert "learning" in data["capabilities"]
    assert "course_building" in data["capabilities"]


def test_overview_contains_access(client, session):
    """overview 返回中有 access 字段（权限视图）。"""
    teacher = _user(session, "fac_access_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(f"{FACADE}/course/{course.id}/overview", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access" in data
    access = data["access"]
    assert "allowed" in access
    assert "course_role" in access
    assert "permissions" in access


def test_overview_contains_structure(client, session):
    """overview 返回中有 structure 字段（节点/章节数）。"""
    teacher = _user(session, "fac_struct_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(f"{FACADE}/course/{course.id}/overview", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "structure" in data
    structure = data["structure"]
    # 创建了一个脚本节点
    assert structure["node_count"] == 1
    assert "chapter_count" in structure
    assert "total_pages" in structure
    assert "total_duration" in structure


def test_citation_contains_return_anchor(client, session):
    """citation 返回中有 return_anchor 字段。"""
    teacher = _user(session, "fac_anchor_teacher", UserRole.TEACHER)
    course, artifact, docling, script, node = _setup_course_with_doc(session, teacher)

    token = _token(teacher)
    resp = client.get(
        f"{FACADE}/course/{course.id}/citation/{node.id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "return_anchor" in data
    assert data["return_anchor"]["node_id"] == node.id
    assert "label" in data["return_anchor"]


def test_quiz_contains_return_anchor(client, session):
    """每个题目有 return_anchor 字段。"""
    teacher = _user(session, "fac_quizanchor_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    _question(
        session, question_text="带知识点题目", course_id=course.id,
        status=QuestionStatus.PUBLISHED, knowledge_node_ids=[42],
    )

    token = _token(teacher)
    resp = client.get(f"{FACADE}/course/{course.id}/quiz", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert "return_anchor" in items[0]
    assert items[0]["return_anchor"]["node_id"] == 42
    assert "label" in items[0]["return_anchor"]
