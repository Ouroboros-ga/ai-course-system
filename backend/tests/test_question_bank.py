"""Phase B 题库权限隔离、状态流转与题源映射单元测试。

测试要点：
1. 权限隔离：unassigned 不可被学生检索、学生仅 published、教师跨课程隔离、
   需 CourseMembership + CourseCapability（非旧 teacher_id）、平台管理员跨课程。
2. 状态流转：Excel 导入 unassigned -> assign auto_accepted -> edit 新版本 ->
   publish 学生可见 -> unpublish 学生不可见。
3. 题源映射：生成默认 auto_accepted、locked 不可覆盖、编辑变 teacher_edited、
   拒绝映射、版本追溯。

使用 conftest.py 的 session / client fixture 和统一权限解析器，
不依赖旧 teacher_id 或 StudentEnrollment。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import (
    Course,
    CourseStatus,
    DoclingDocument,
    DoclingText,
    ParseStatus,
)
from app.models.document_artifact_model import DocumentArtifact
from app.models.question_bank_model import (
    MappingStatus,
    QuestionBankItem,
    QuestionAttempt,
    QuestionDifficulty,
    QuestionSourceMapping,
    QuestionStatus,
    QuestionType,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
    resolve_course_access,
)
from app.tools.import_question_bank import _map_row_to_item


# ==================== 辅助函数 ====================

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
        fanya_course_id=f"qb-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="QB Course",
        title="QB Course",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
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


def _principal(user):
    """构造 resolve_course_access 所需的 principal 字典。"""
    return {"user_id": str(user.id), "role": user.role.value, "username": user.username}


def _question(session, *, question_text="测试题目", answer="测试答案",
              course_id=None, status=QuestionStatus.UNASSIGNED,
              category="测试分类", generated_by="excel_import",
              version=1, prev_version_id=None, is_latest=True,
              created_by=None, import_batch_id=None):
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
        knowledge_node_ids=[],
        prerequisite_node_ids=[],
        status=status,
        version=version,
        prev_version_id=prev_version_id,
        is_latest=is_latest,
        generated_by=generated_by,
        created_by=created_by,
        import_batch_id=import_batch_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _doc(session, course_id, document_id=None, file_name=None):
    """创建显式选择的文档产物及其真实解析文本。"""
    if document_id is None:
        document_id = f"doc-{course_id}-{datetime.utcnow().timestamp()}"
    if file_name is None:
        file_name = f"{document_id}.pdf"
    doc = DocumentArtifact(
        document_id=document_id,
        course_id=course_id,
        file_name=file_name,
        mime_type="application/pdf",
    )
    session.add(doc)
    parsed = DoclingDocument(
        course_id=course_id,
        doc_name=file_name,
        origin_filename=file_name,
        origin_binary_hash=f"hash-{document_id}",
        status=ParseStatus.COMPLETED,
        version="test-parser/1.0",
    )
    session.add(parsed)
    session.flush()
    session.add(DoclingText(
        doc_id=parsed.id,
        self_ref=f"#/texts/{document_id}",
        text=(
            "映射测试题目 映射答案 锁定测试题目 编辑映射题目 "
            "拒绝映射题目 版本追溯题目 待发布题目 测试答案"
        ),
        page_no=1,
        sort_order=0,
    ))
    session.commit()
    session.refresh(doc)
    return doc


def _accepted_mapping(session, question, course_id):
    mapping = QuestionSourceMapping(
        question_id=question.id,
        course_id=course_id,
        document_id=f"test-doc-{course_id}",
        evidence_refs=[f"test-evidence-{question.id}"],
        ocr_evidence=[{"page": 1, "text": question.question_text}],
        status=MappingStatus.AUTO_ACCEPTED,
        content_hash=f"hash-{question.id}",
    )
    session.add(mapping)
    session.commit()
    return mapping


def _auth(token):
    """构造 Bearer 认证头。"""
    return {"Authorization": f"Bearer {token}"}


QB = "/api/v1/question-bank"
QM = "/api/v1/question-mapping"


# ==================== 权限隔离测试 ====================

def test_unassigned_questions_invisible_to_students(client, session):
    """未归属(unassigned)题目不能被学生检索。

    - unassigned 题目 course_id=None，不出现在任何课程检索中
    - 学生不能访问待归属题源池(/unassigned 端点返回 403)
    - 普通课程教师不能查看平台级待归属题源池
    """
    teacher = _user(session, "qb_unassigned_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "qb_unassigned_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    # 创建未归属题目(course_id=None, status=unassigned)
    _question(
        session,
        question_text="未归属的测试题目",
        course_id=None,
        status=QuestionStatus.UNASSIGNED,
        import_batch_id="batch-001",
    )

    student_token = _token(student)
    teacher_token = _token(teacher)

    # 学生检索课程题库 -> 未归属题目不在任何课程中，检索不到
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"keyword": "未归属", "limit": 50},
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    # 学生不能访问待归属题源池
    resp = client.get(f"{QB}/unassigned", headers=_auth(student_token))
    assert resp.status_code == 403

    # 普通课程教师不能查看平台级待归属题源池
    resp = client.get(f"{QB}/unassigned", headers=_auth(teacher_token))
    assert resp.status_code == 403

    # 显式平台管理员权限才可查看
    session.add(PlatformPermissionAssignment(
        user_id=teacher.id,
        permission=PlatformPermission.ADMIN,
    ))
    session.commit()
    resp = client.get(f"{QB}/unassigned", headers=_auth(teacher_token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "unassigned"
    assert items[0]["course_id"] is None


def test_student_only_retrieves_published_questions(client, session):
    """学生只能检索 published 状态的题目。

    课程中同时存在 auto_accepted、published、rejected 题目，
    学生列表和检索仅返回 published。
    """
    teacher = _user(session, "qb_pubonly_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "qb_pubonly_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    q_auto = _question(
        session, question_text="自动接受题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )
    q_pub = _question(
        session, question_text="已发布题目", course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )
    _question(
        session, question_text="已拒绝题目", course_id=course.id,
        status=QuestionStatus.REJECTED,
    )

    token = _token(student)

    # 学生列出课程题目 -> 只看到 published
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == q_pub.id
    assert items[0]["status"] == "published"

    # 学生检索 -> 只匹配 published
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"keyword": "题目", "limit": 50},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == q_pub.id

    # 教师列出课程题目 -> 可看到所有状态
    teacher_token = _token(teacher)
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(teacher_token))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 3


def test_teacher_cannot_manage_other_teacher_course_questions(client, session):
    """教师A不能管理教师B课程的题目（使用统一权限解析器，不是旧的 teacher_id 判断）。"""
    teacher_a = _user(session, "qb_iso_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "qb_iso_teacher_b", UserRole.TEACHER)

    course_a = _course(session, teacher_a.id)
    course_b = _course(session, teacher_b.id)
    establish_course_access_baseline(session, course_a.id, teacher_a.id)
    establish_course_access_baseline(session, course_b.id, teacher_b.id)
    session.commit()

    # 在课程B中创建题目
    q_b = _question(
        session, question_text="课程B题目", course_id=course_b.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )

    # 创建一道未归属题目
    unassigned = _question(
        session, question_text="待分配题目", course_id=None,
        status=QuestionStatus.UNASSIGNED,
    )

    token_a = _token(teacher_a)

    # 教师A列出课程B题目 -> 403
    resp = client.get(f"{QB}/course/{course_b.id}", headers=_auth(token_a))
    assert resp.status_code == 403

    # 教师A编辑课程B题目 -> 403
    resp = client.put(
        f"{QB}/course/{course_b.id}/{q_b.id}",
        json={"question_text": "篡改内容"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 403

    # 教师A发布课程B题目 -> 403
    resp = client.post(
        f"{QB}/course/{course_b.id}/publish",
        json={"question_ids": [q_b.id], "publish": True},
        headers=_auth(token_a),
    )
    assert resp.status_code == 403

    # 教师A分配题目到课程B -> 403
    resp = client.post(
        f"{QB}/assign",
        json={"question_ids": [unassigned.id], "course_id": course_b.id,
              "knowledge_node_ids": []},
        headers=_auth(token_a),
    )
    assert resp.status_code == 403

    # 教师B可以管理自己的课程 -> 200
    token_b = _token(teacher_b)
    resp = client.get(f"{QB}/course/{course_b.id}", headers=_auth(token_b))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1


def test_question_bank_requires_membership_not_teacher_id(client, session):
    """需要创建 CourseMembership + CourseCapability 才能获得权限（不是旧的 teacher_id）。

    仅在 Course.teacher_id 上设置教师ID，但不创建 CourseMembership 和
    CourseCapability，则 resolve_course_access 返回无权限，API 也返回 403。
    建立基线后权限恢复。
    """
    teacher = _user(session, "qb_membership_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    # 故意不调用 establish_course_access_baseline
    session.commit()

    # 服务层：无成员关系 -> 无权限
    principal = _principal(teacher)
    context = resolve_course_access(session, principal, course.id)
    assert context.role is None
    assert not context.allows("question_bank.read")
    assert not context.allows("question_bank.manage")
    assert not context.allows("question_bank.publish")

    # API层：教师列出课程题目 -> 403
    token = _token(teacher)
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(token))
    assert resp.status_code == 403

    # 建立基线（创建 CourseMembership + CourseCapability）后 -> 有权限
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    context = resolve_course_access(session, principal, course.id)
    assert context.role is not None
    assert context.allows("question_bank.read")
    assert context.allows("question_bank.manage")
    assert context.allows("question_bank.publish")

    # API层：教师列出课程题目 -> 200
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(token))
    assert resp.status_code == 200


def test_platform_admin_cross_course_question_access(client, session):
    """平台管理员(platform.admin)可跨课程访问题库。

    管理员无 CourseMembership，但有 PlatformPermissionAssignment(ADMIN)，
    可以访问任何课程的题库，且不限于 published 状态。
    """
    teacher = _user(session, "qb_admin_course_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    # 创建不同状态的题目
    _question(
        session, question_text="自动题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )
    _question(
        session, question_text="发布题目", course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )

    # 平台管理员（无课程成员关系，全局角色为 STUDENT）
    admin = _user(session, "qb_admin_user", UserRole.STUDENT)
    session.add(PlatformPermissionAssignment(
        user_id=admin.id, permission=PlatformPermission.ADMIN,
    ))
    session.commit()

    token = _token(admin)

    # 管理员列出课程题目 -> 200，可看到所有状态（不限于 published）
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 2
    statuses = {item["status"] for item in items}
    assert "auto_accepted" in statuses
    assert "published" in statuses

    # 管理员检索课程题库 -> 也可看到所有状态
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"keyword": "题目", "limit": 50},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 2


# ==================== 状态流转测试 ====================

def test_excel_import_defaults_to_unassigned_null_course():
    """Excel导入后默认 unassigned，course_id=None。

    直接测试 _map_row_to_item 映射函数，验证导入产出的题目默认值。
    """
    row = {
        "规则分类": "机器学习基础",
        "标准问题": "什么是机器学习？",
        "答案": "机器学习是人工智能的一个分支",
        "规则状态": "启用",
        "匹配模式": "精确匹配",
        "相似问法1": "机器学习是什么",
        "相似问法2": "解释机器学习",
    }
    item = _map_row_to_item(row, row_index=2, batch_id="test-batch-001")

    assert item.status == QuestionStatus.UNASSIGNED
    assert item.course_id is None
    assert item.question_text == "什么是机器学习？"
    assert item.answer == "机器学习是人工智能的一个分支"
    assert item.category == "机器学习基础"
    assert item.rule_status == "启用"
    assert item.match_mode == "精确匹配"
    assert item.generated_by == "excel_import"
    assert item.version == 1
    assert item.is_latest is True
    assert item.prev_version_id is None
    assert item.import_batch_id == "test-batch-001"
    assert item.source_row_index == 2
    assert len(item.similar_questions) == 2
    assert "机器学习是什么" in item.similar_questions


def test_assign_to_course_transitions_to_auto_accepted(client, session):
    """分配到课程后变为 auto_accepted。"""
    teacher = _user(session, "qb_assign_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    # 创建未归属题目
    q = _question(
        session, question_text="待分配题目", course_id=None,
        status=QuestionStatus.UNASSIGNED,
    )

    token = _token(teacher)

    # 教师分配到课程
    resp = client.post(
        f"{QB}/assign",
        json={"question_ids": [q.id], "course_id": course.id,
              "knowledge_node_ids": [10, 20]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated"] == 1

    # 验证状态变为 auto_accepted
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "auto_accepted"
    assert items[0]["course_id"] == course.id
    assert items[0]["knowledge_node_ids"] == [10, 20]


def test_teacher_edit_creates_version_chain(client, session):
    """教师编辑后生成新版本，旧版本保留(prev_version_id链可追溯)。"""
    teacher = _user(session, "qb_version_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    q = _question(
        session, question_text="原始题目", answer="原始答案",
        course_id=course.id, status=QuestionStatus.AUTO_ACCEPTED,
    )
    question_id = q.id

    token = _token(teacher)

    # 教师编辑题目
    resp = client.put(
        f"{QB}/course/{course.id}/{question_id}",
        json={"question_text": "修改后题目", "answer": "修改后答案"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["version"] == 2
    assert data["prev_version_id"] is not None
    prev_version_id = data["prev_version_id"]

    # 验证版本历史(prev_version_id 链可追溯)
    resp = client.get(
        f"{QB}/course/{course.id}/{question_id}/versions",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    versions = resp.json()["data"]["versions"]
    assert len(versions) == 2

    # 最新版本在前
    assert versions[0]["version"] == 2
    assert versions[0]["is_latest"] is True
    assert versions[0]["status"] == "teacher_edited"

    # 旧版本
    assert versions[1]["version"] == 1
    assert versions[1]["is_latest"] is False
    assert versions[1]["id"] == prev_version_id

    # 验证最新版本内容已更新
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(token))
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["question_text"] == "修改后题目"
    assert items[0]["answer"] == "修改后答案"
    assert items[0]["status"] == "teacher_edited"
    assert items[0]["version"] == 2


def test_publish_makes_question_student_retrievable(client, session):
    """发布后学生可检索。"""
    teacher = _user(session, "qb_pubflow_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "qb_pubflow_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    q = _question(
        session, question_text="待发布题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )
    _accepted_mapping(session, q, course.id)

    student_token = _token(student)
    teacher_token = _token(teacher)

    # 发布前：学生检索不到
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"keyword": "待发布", "limit": 50},
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    # 教师发布
    resp = client.post(
        f"{QB}/course/{course.id}/publish",
        json={"question_ids": [q.id], "publish": True},
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated"] == 1

    # 发布后：学生可检索
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"keyword": "待发布", "limit": 50},
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == q.id
    assert items[0]["status"] == "published"


def test_unpublish_makes_question_student_invisible(client, session):
    """下架后学生不可检索。"""
    teacher = _user(session, "qb_unpubflow_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "qb_unpubflow_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    q = _question(
        session, question_text="已发布题目", course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )

    student_token = _token(student)
    teacher_token = _token(teacher)

    # 下架前：学生可检索
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"limit": 50},
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1

    # 教师下架
    resp = client.post(
        f"{QB}/course/{course.id}/publish",
        json={"question_ids": [q.id], "publish": False},
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated"] == 1

    # 下架后：学生不可检索
    resp = client.post(
        f"{QB}/course/{course.id}/search",
        json={"limit": 50},
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    # 教师仍可看到(状态变为 teacher_edited)
    resp = client.get(f"{QB}/course/{course.id}", headers=_auth(teacher_token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "teacher_edited"


# ==================== 题源映射测试 ====================

def test_generate_mapping_defaults_to_pending_review(client, session):
    """生成映射默认 pending_review（P1-4 后新契约）。

    P1-4 之前默认 auto_accepted；P1-4 后所有新生成的映射默认 pending_review，
    教师必须审核后才能升级为 auto_accepted 或 teacher_edited。
    """
    teacher = _user(session, "qb_genmap_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    q = _question(
        session, question_text="映射测试题目", answer="映射答案",
        course_id=course.id, status=QuestionStatus.AUTO_ACCEPTED,
    )
    doc = _doc(session, course.id, document_id="qb-gen-doc-001",
               file_name="lecture1.pdf")

    token = _token(teacher)

    # 生成映射
    resp = client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [doc.document_id],
              "regenerate": False},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["generated"] == 1
    assert resp.json()["data"]["skipped_locked"] == 0

    # 列出映射，验证状态（P1-4 后默认 pending_review）
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "pending_review"
    assert items[0]["version"] == 1
    assert items[0]["is_latest"] is True
    assert items[0]["document_id"] == "qb-gen-doc-001"
    assert items[0]["slide_file_name"] == "lecture1.pdf"
    assert items[0]["question_id"] == q.id


def test_locked_mapping_survives_regenerate(client, session):
    """locked 映射不可被 EduAgent 重跑覆盖（教师安全阀门）。

    - 生成映射后锁定
    - regenerate=False 时跳过 locked
    - regenerate=True 时仍然跳过 locked（安全阀门）
    """
    teacher = _user(session, "qb_lockmap_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    q = _question(
        session, question_text="锁定测试题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )

    token = _token(teacher)

    # 生成映射
    resp = client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [_doc(session, course.id).document_id],
              "regenerate": False},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["generated"] == 1

    # 获取映射ID并锁定
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    mapping_id = resp.json()["data"]["items"][0]["id"]
    original_content_hash = resp.json()["data"]["items"][0]["content_hash"]

    resp = client.post(
        f"{QM}/course/{course.id}/{mapping_id}/status",
        json={"status": "locked"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "locked"

    # 重跑(regenerate=False) -> 跳过 locked
    resp = client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [_doc(session, course.id).document_id],
              "regenerate": False},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["generated"] == 0
    assert resp.json()["data"]["skipped_locked"] == 1

    # 重跑(regenerate=True) -> 仍然跳过 locked（安全阀门）
    resp = client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [_doc(session, course.id).document_id],
              "regenerate": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["generated"] == 0
    assert resp.json()["data"]["skipped_locked"] == 1

    # 验证映射未被覆盖
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == mapping_id
    assert items[0]["status"] == "locked"
    assert items[0]["content_hash"] == original_content_hash
    assert items[0]["version"] == 1


def test_teacher_edit_mapping_becomes_teacher_edited(client, session):
    """教师编辑后状态变为 teacher_edited，生成新版本。"""
    teacher = _user(session, "qb_editmap_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    q = _question(
        session, question_text="编辑映射题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )

    token = _token(teacher)

    # 生成映射(v1, pending_review) - P1-4 后默认 pending_review
    client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [_doc(session, course.id).document_id],
              "regenerate": False},
        headers=_auth(token),
    )

    # 获取映射ID
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    mapping_id = resp.json()["data"]["items"][0]["id"]

    # 教师编辑映射
    resp = client.put(
        f"{QM}/course/{course.id}/{mapping_id}",
        json={
            "mapping_reason": "教师手动调整",
            "confidence": 0.95,
            "page_start": 1,
            "page_end": 5,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2

    # 验证状态变为 teacher_edited
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "teacher_edited"
    assert items[0]["version"] == 2
    assert items[0]["mapping_reason"] == "教师手动调整"
    assert items[0]["confidence"] == 0.95
    assert items[0]["page_start"] == 1
    assert items[0]["page_end"] == 5


def test_reject_mapping_status(client, session):
    """拒绝映射。"""
    teacher = _user(session, "qb_rejectmap_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    q = _question(
        session, question_text="拒绝映射题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )

    token = _token(teacher)

    # 生成映射
    client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [_doc(session, course.id).document_id],
              "regenerate": False},
        headers=_auth(token),
    )

    # 获取映射ID
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    mapping_id = resp.json()["data"]["items"][0]["id"]

    # 拒绝映射
    resp = client.post(
        f"{QM}/course/{course.id}/{mapping_id}/status",
        json={"status": "rejected"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rejected"

    # 验证
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["status"] == "rejected"


def test_mapping_version_history_traceable(client, session):
    """版本历史可追溯。

    生成映射(v1) -> 教师编辑(v2) -> 版本历史包含两个版本，
    通过 prev_version_id 链可追溯。
    """
    teacher = _user(session, "qb_vermap_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    q = _question(
        session, question_text="版本追溯题目", course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )

    token = _token(teacher)

    # 生成映射 (v1, pending_review) - P1-4 后默认 pending_review
    client.post(
        f"{QM}/course/{course.id}/generate",
        json={"question_ids": [q.id], "document_ids": [_doc(session, course.id).document_id],
              "regenerate": False},
        headers=_auth(token),
    )

    # 获取映射ID
    resp = client.get(f"{QM}/course/{course.id}", headers=_auth(token))
    mapping_id = resp.json()["data"]["items"][0]["id"]

    # 教师编辑 -> v2, teacher_edited
    resp = client.put(
        f"{QM}/course/{course.id}/{mapping_id}",
        json={"mapping_reason": "第一次编辑"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2

    # 获取版本历史
    resp = client.get(
        f"{QM}/course/{course.id}/{mapping_id}/versions",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    versions = resp.json()["data"]["versions"]
    assert len(versions) == 2

    # 最新版本在前
    assert versions[0]["version"] == 2
    assert versions[0]["is_latest"] is True
    assert versions[0]["status"] == "teacher_edited"

    # 旧版本(v1) - P1-4 后初始状态为 pending_review
    assert versions[1]["version"] == 1
    assert versions[1]["is_latest"] is False
    assert versions[1]["status"] == "pending_review"


def test_student_payload_hides_answer_and_objective_attempt_is_scored(client, session):
    teacher = _user(session, "qb_answer_teacher", UserRole.TEACHER)
    student = _user(session, "qb_answer_student")
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()
    question = _question(
        session,
        question_text="1 + 1 = ?",
        answer="B",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )
    question.question_type = QuestionType.SINGLE_CHOICE
    question.options = {"A": "1", "B": "2"}
    session.add(question)
    session.commit()

    response = client.get(
        f"{QB}/course/{course.id}",
        headers=_auth(_token(student)),
    )
    assert response.status_code == 200
    assert "answer" not in response.json()["data"]["items"][0]

    response = client.post(
        f"{QB}/course/{course.id}/{question.id}/attempt",
        json={"student_answer": "b"},
        headers=_auth(_token(student)),
    )
    assert response.status_code == 200
    assert response.json()["data"]["score"] == 1.0
    attempt = session.get(QuestionAttempt, response.json()["data"]["attempt_id"])
    assert attempt.measurement_role == "scored_performance"
    assert attempt.source_event_id.startswith("qe_")
    assert attempt.question_version == question.version
    assert attempt.question_content_hash

    response = client.post(
        f"{QB}/course/{course.id}/{question.id}/attempt",
        json={"student_answer": "B"},
        headers=_auth(_token(teacher)),
    )
    assert response.status_code == 403


def test_mapping_without_real_parsed_text_is_rejected(client, session):
    teacher = _user(session, "qb_unparsed_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    question = _question(
        session,
        question_text="未解析课件题目",
        course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
    )
    artifact = DocumentArtifact(
        document_id="unparsed-doc",
        course_id=course.id,
        file_name="unparsed.pdf",
        mime_type="application/pdf",
    )
    session.add(artifact)
    session.commit()
    response = client.post(
        f"{QM}/course/{course.id}/generate",
        json={
            "question_ids": [question.id],
            "document_ids": [artifact.document_id],
        },
        headers=_auth(_token(teacher)),
    )
    assert response.status_code == 409
    assert response.json()["code"] == 409
    assert response.json()["data"]["error_code"] == "SELECTED_DOCUMENT_NOT_PARSED"
