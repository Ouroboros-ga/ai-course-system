"""G2 六维认知与推荐测试。

测试要点：
1. 权限与隔离：跨课程隔离、跨学生隔离、权限校验(需CourseMembership)、
   平台管理员跨课程访问。
2. 六维计算逻辑：无数据输出unknown、表现分仅从答题正确率计算、
   低表现+高置信度、低表现+低置信度、提示依赖高、表现良好。
3. 推荐可解释性：每次推荐带policy_version、reason_codes、evidence_refs，
   数据不足时输出"需要更多证据"。
4. 答题证据：答题结果形成LearningEvidenceRecord、证据与交互状态分离。

使用 conftest.py 的 session / client fixture 和统一权限解析器，
不依赖旧 teacher_id 或 StudentEnrollment。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest
from sqlmodel import Session, select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.cognitive_state_model import (
    COGNITIVE_POLICY_VERSION,
    CognitiveState,
    LearningEvidenceRecord,
    RecommendationRecord,
)
from app.models.qa_model import MessageRole, QAMessage, QASession
from app.models.question_bank_model import (
    QuestionAttempt,
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
from app.services.cognitive_service import (
    compute_cognitive_state,
    get_latest_cognitive_state,
)
from app.services.recommendation_service import generate_recommendation

CR = "/api/v1/cognitive"


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
        fanya_course_id=f"cr-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="CR",
        title="CR",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _setup_course(session, teacher, student):
    """创建课程并建立权限基线（教师 owner + 学生 active membership）。"""
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()
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


def _principal(user):
    """构造 resolve_course_access 所需的 principal 字典。"""
    return {"user_id": str(user.id), "role": user.role.value, "username": user.username}


def _create_published_question(session, course_id, difficulty=QuestionDifficulty.MEDIUM):
    """创建已发布题目并提交。"""
    q = QuestionBankItem(
        question_text="test question",
        answer="test answer",
        options={},
        similar_questions=[],
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=difficulty,
        course_id=course_id,
        knowledge_node_ids=[],
        prerequisite_node_ids=[],
        status=QuestionStatus.PUBLISHED,
        version=1,
        is_latest=True,
        generated_by="teacher_manual",
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def _create_attempt(session, student_id, course_id, question_id,
                     is_correct=None, cognitive_context=None):
    """创建答题记录并提交。"""
    attempt = QuestionAttempt(
        question_id=question_id,
        course_id=course_id,
        student_id=student_id,
        student_answer="test",
        is_correct=is_correct,
        cognitive_context=cognitive_context or {},
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return attempt


def _create_qa_messages(session, student_id, course_id, count=5):
    """创建问答会话和消息（模拟学生提问），返回创建的消息列表。"""
    qs = QASession(user_id=student_id, course_id=course_id)
    session.add(qs)
    session.commit()
    session.refresh(qs)

    messages = []
    for i in range(count):
        msg = QAMessage(
            session_id=qs.id,
            role=MessageRole.USER,
            content=f"test question {i}",
        )
        session.add(msg)
        messages.append(msg)
    session.commit()
    for msg in messages:
        session.refresh(msg)
    return messages


# ==================== 权限与隔离测试 ====================

def test_cross_course_isolation(session):
    """跨课程隔离：学生A在课程1的认知状态不影响课程2。

    学生在课程1有答题记录，计算认知状态后有表现分；
    在课程2无答题记录，认知状态为 unknown。
    """
    teacher = _user(session, "cr_iso_teacher", UserRole.TEACHER)
    student = _user(session, "cr_iso_student")
    course1 = _setup_course(session, teacher, student)
    # 课程2使用同一教师和学生
    course2 = _course(session, teacher.id)
    establish_course_access_baseline(session, course2.id, teacher.id)
    activate_student_membership(session, course2.id, student.id)
    session.commit()

    # 在课程1创建答题记录（全部正确）
    for _ in range(5):
        q = _create_published_question(session, course1.id)
        _create_attempt(session, student.id, course1.id, q.id, is_correct=True)

    # 课程1：有数据 -> 表现分不为 None
    state1 = compute_cognitive_state(session, student.id, course1.id)
    assert state1.observed_performance_score is not None
    assert state1.sample_size == 5
    assert state1.observed_performance_score == pytest.approx(1.0)

    # 课程2：无数据 -> 表现分为 None (unknown)
    state2 = compute_cognitive_state(session, student.id, course2.id)
    assert state2.observed_performance_score is None
    assert state2.sample_size == 0
    assert state2.mastery_level == "unknown"
    assert "no_attempt_data" in state2.reason_codes

    # 确保课程1的状态没有泄漏到课程2
    assert state2.course_id == course2.id
    assert state1.course_id == course1.id


def test_cross_student_isolation(session):
    """跨学生隔离：学生A的推荐不读取学生B的状态。

    学生A表现差（推荐补弱练习），学生B表现好（推荐前进）。
    两者的推荐互相独立，不读取对方数据。
    """
    teacher = _user(session, "cr_cross_teacher", UserRole.TEACHER)
    student_a = _user(session, "cr_cross_student_a")
    student_b = _user(session, "cr_cross_student_b")
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    activate_student_membership(session, course.id, student_a.id)
    activate_student_membership(session, course.id, student_b.id)
    session.commit()

    # 学生A：最近5次中1次正确 -> 低表现
    for i in range(7):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student_a.id, course.id, q.id, is_correct=(i < 3))

    # 学生B：5次答题，全部正确 -> 高表现
    for _ in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student_b.id, course.id, q.id, is_correct=True)

    # 计算认知状态
    state_a = compute_cognitive_state(session, student_a.id, course.id)
    state_b = compute_cognitive_state(session, student_b.id, course.id)

    # 学生A的状态反映A的数据，不读取B的
    assert state_a.student_id == student_a.id
    assert state_a.observed_performance_score == pytest.approx(1 / 5)
    assert state_a.sample_size == 5

    # 学生B的状态反映B的数据，不读取A的
    assert state_b.student_id == student_b.id
    assert state_b.observed_performance_score == pytest.approx(1.0)
    assert state_b.sample_size == 5

    # 生成推荐，验证互不干扰
    rec_a = generate_recommendation(session, student_a.id, course.id, force_recompute=True)
    rec_b = generate_recommendation(session, student_b.id, course.id, force_recompute=True)

    # 学生A的推荐反映A的低表现
    assert rec_a.student_id == student_a.id
    assert rec_a.recommendation_type == "practice_quiz"
    assert rec_a.priority == "high"
    assert rec_a.cognitive_snapshot["observed_performance_score"] == pytest.approx(1 / 5)

    # 学生B的推荐反映B的高表现
    assert rec_b.student_id == student_b.id
    assert rec_b.recommendation_type == "advance_next"
    assert rec_b.cognitive_snapshot["observed_performance_score"] == pytest.approx(1.0)


def test_cognitive_api_requires_membership_not_teacher_id(client, session):
    """权限校验：需要CourseMembership才能访问认知API（不依赖旧teacher_id）。

    仅在 Course.teacher_id 上设置教师ID，但不创建 CourseMembership 和
    CourseCapability，则 resolve_course_access 返回无权限，API 返回 403。
    建立基线后权限恢复。
    """
    teacher = _user(session, "cr_perm_teacher", UserRole.TEACHER)
    student = _user(session, "cr_perm_student")
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    # 故意不调用 establish_course_access_baseline
    session.commit()

    # 服务层：无成员关系 -> 无权限
    principal = _principal(teacher)
    context = resolve_course_access(session, principal, course.id)
    assert context.role is None
    assert not context.allows("course.progress.read_self")

    # API层：教师获取认知状态 -> 403
    token = _token(teacher)
    resp = client.get(
        f"{CR}/course/{course.id}/state?student_id={student.id}",
        headers=_auth(token),
    )
    assert resp.status_code == 403

    # 建立基线（创建 CourseMembership + CourseCapability）后 -> 有权限
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    context = resolve_course_access(session, principal, course.id)
    assert context.role is not None
    assert context.allows("course.progress.read_self")

    # API层：教师获取认知状态 -> 200
    resp = client.get(
        f"{CR}/course/{course.id}/state?student_id={student.id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200


def test_platform_admin_cross_course_cognitive_access(client, session):
    """平台管理员可跨课程访问认知API。

    管理员无 CourseMembership，但有 PlatformPermissionAssignment(ADMIN)，
    可以访问任何课程的认知状态。
    """
    teacher = _user(session, "cr_admin_teacher", UserRole.TEACHER)
    student = _user(session, "cr_admin_student")
    course = _setup_course(session, teacher, student)

    # 在课程中创建答题记录
    q = _create_published_question(session, course.id)
    _create_attempt(session, student.id, course.id, q.id, is_correct=True)

    # 平台管理员（无课程成员关系，全局角色为 STUDENT）
    admin = _user(session, "cr_admin_user", UserRole.STUDENT)
    session.add(PlatformPermissionAssignment(
        user_id=admin.id, permission=PlatformPermission.ADMIN,
    ))
    session.commit()

    token = _token(admin)

    # 管理员访问课程认知状态 -> 200
    resp = client.get(
        f"{CR}/course/{course.id}/state?student_id={student.id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200

    # 管理员不能以自己的身份生成学生学情推荐
    resp = client.post(
        f"{CR}/course/{course.id}/recommend",
        json={},
        headers=_auth(token),
    )
    assert resp.status_code == 403


# ==================== 六维计算逻辑测试 ====================

def test_no_data_outputs_unknown(session):
    """无数据时输出unknown：新学生没有任何答题记录时，observed_performance_score=None。

    同时 evidence_confidence、confusion_risk、hint_dependency 均为 None，
    mastery_level 为 "unknown"。
    """
    teacher = _user(session, "cr_unknown_teacher", UserRole.TEACHER)
    student = _user(session, "cr_unknown_student")
    course = _setup_course(session, teacher, student)

    state = compute_cognitive_state(session, student.id, course.id)

    assert state.observed_performance_score is None
    assert state.evidence_confidence is None
    assert state.confusion_risk is None
    assert state.hint_dependency is None
    assert state.explanation_need is None
    assert state.mastery_level == "unknown"
    assert state.mastery_score is None
    assert state.sample_size == 0
    assert "no_attempt_data" in state.reason_codes


def test_performance_score_only_from_quiz_accuracy(session):
    """表现分仅从答题正确率计算：不把提问次数或观看时长计入表现分。

    创建答题记录（3正确1错误）和QA提问消息（5条），
    验证 observed_performance_score == 3/4（仅答题正确率），
    无结构化语义标签时 inquiry_depth 必须保持 unknown。
    """
    teacher = _user(session, "cr_perf_teacher", UserRole.TEACHER)
    student = _user(session, "cr_perf_student")
    course = _setup_course(session, teacher, student)

    # 创建4次答题：3正确1错误
    for i in range(4):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))

    # 创建5条QA提问消息（不应影响表现分）
    _create_qa_messages(session, student.id, course.id, count=5)

    state = compute_cognitive_state(session, student.id, course.id)

    # 表现分仅从答题正确率计算
    assert state.observed_performance_score == pytest.approx(3 / 4)
    assert state.sample_size == 4

    assert state.inquiry_depth is None

    # 确认原因码标注了提问不计入表现分
    assert "performance_from_quiz_accuracy" in state.reason_codes
    assert "inquiry_unknown_without_semantic_evidence" in state.reason_codes


def test_low_performance_high_confidence_recommendation(session):
    """低表现+高置信度：表现分<0.5且置信度>=0.6时，推荐策略为补弱练习(PRACTICE_QUIZ, HIGH)。

    最近5次答题中1次正确 -> perf=0.2 < 0.5，5个评分项 -> 高置信度。
    """
    teacher = _user(session, "cr_lowhi_teacher", UserRole.TEACHER)
    student = _user(session, "cr_lowhi_student")
    course = _setup_course(session, teacher, student)

    # 7次答题：3正确4错误
    for i in range(7):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))

    state = compute_cognitive_state(session, student.id, course.id)

    # 验证六维状态
    assert state.observed_performance_score == pytest.approx(1 / 5)
    assert state.observed_performance_score < 0.5
    assert state.evidence_confidence is not None
    assert state.evidence_confidence >= 0.6

    # 生成推荐
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert rec.recommendation_type == "practice_quiz"
    assert rec.priority == "high"
    assert "low_performance_high_confidence" in rec.reason_codes


def test_low_performance_low_confidence_recommendation(session):
    """低表现+低置信度：表现分<0.5且置信度<0.4时，推荐策略为诊断题。

    reason_codes 包含 diagnostic_not_weakness，不直接判定薄弱。
    3次答题（1正确2错误）-> perf=1/3≈0.33 < 0.5
    3次总答题 < 5 -> confidence = 0.3 < 0.4
    """
    teacher = _user(session, "cr_lowlow_teacher", UserRole.TEACHER)
    student = _user(session, "cr_lowlow_student")
    course = _setup_course(session, teacher, student)

    # 3次答题：1正确2错误
    for i in range(3):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 1))

    state = compute_cognitive_state(session, student.id, course.id)

    # 验证六维状态
    assert state.observed_performance_score == pytest.approx(1 / 3)
    assert state.observed_performance_score < 0.5
    assert state.evidence_confidence is not None
    assert state.evidence_confidence < 0.4

    # 生成推荐
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert rec.recommendation_type == "practice_quiz"
    assert rec.priority == "medium"
    assert "diagnostic_not_weakness" in rec.reason_codes


def test_high_hint_dependency_recommendation(session):
    """提示依赖高：hint_dependency>=0.5时，推荐策略包含hint_fade_strategy。

    4次答题（2正确2错误，其中2次使用提示）-> perf=0.5, hint_dependency=0.5
    表现分0.5不<0.5，跳过低表现分支，命中提示依赖分支。
    """
    teacher = _user(session, "cr_hint_teacher", UserRole.TEACHER)
    student = _user(session, "cr_hint_student")
    course = _setup_course(session, teacher, student)

    # 4次答题：2正确（无提示），2错误（使用提示）
    for i in range(4):
        q = _create_published_question(session, course.id)
        hint_used = i >= 2  # 后2次使用提示
        _create_attempt(
            session, student.id, course.id, q.id,
            is_correct=(i < 2),
            cognitive_context={"hint_used": hint_used},
        )

    state = compute_cognitive_state(session, student.id, course.id)

    # 验证六维状态
    assert state.observed_performance_score == pytest.approx(0.5)
    assert state.hint_dependency is not None
    assert state.hint_dependency >= 0.5

    # 生成推荐
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert "hint_fade_strategy" in rec.reason_codes


def test_good_performance_advance_recommendation(session):
    """表现良好：表现分>=0.7时，推荐策略为前进(ADVANCE_NEXT)。

    5次答题全部正确 -> perf=1.0 >= 0.7
    无提示依赖、无困惑风险 -> 跳过中间分支，命中前进分支。
    """
    teacher = _user(session, "cr_good_teacher", UserRole.TEACHER)
    student = _user(session, "cr_good_student")
    course = _setup_course(session, teacher, student)

    # 5次答题全部正确
    for _ in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=True)

    state = compute_cognitive_state(session, student.id, course.id)

    # 验证六维状态
    assert state.observed_performance_score == pytest.approx(1.0)
    assert state.observed_performance_score >= 0.7
    assert state.hint_dependency is None

    # 生成推荐
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert rec.recommendation_type == "advance_next"
    assert "advance_next" in rec.reason_codes


# ==================== 推荐可解释性测试 ====================

def test_recommendation_has_policy_version(session):
    """每次推荐带policy_version：推荐记录包含非空policy_version。"""
    teacher = _user(session, "cr_pv_teacher", UserRole.TEACHER)
    student = _user(session, "cr_pv_student")
    course = _setup_course(session, teacher, student)

    # 创建一些答题数据
    for i in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=True)

    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert rec.policy_version is not None
    assert rec.policy_version != ""
    assert rec.policy_version == COGNITIVE_POLICY_VERSION


def test_recommendation_has_reason_codes(session):
    """每次推荐带reason_codes：推荐记录包含非空reason_codes列表。"""
    teacher = _user(session, "cr_rc_teacher", UserRole.TEACHER)
    student = _user(session, "cr_rc_student")
    course = _setup_course(session, teacher, student)

    # 创建答题数据（低表现）
    for i in range(7):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))

    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert rec.reason_codes is not None
    assert isinstance(rec.reason_codes, list)
    assert len(rec.reason_codes) > 0


def test_recommendation_has_evidence_refs(session):
    """每次推荐带evidence_refs：推荐记录包含evidence_refs（数据不足时可为空列表）。

    有答题数据时evidence_refs非空；无数据时evidence_refs为空列表但字段存在。
    """
    teacher = _user(session, "cr_er_teacher", UserRole.TEACHER)
    student_a = _user(session, "cr_er_student_a")
    student_b = _user(session, "cr_er_student_b")
    course = _setup_course(session, teacher, student_a)
    activate_student_membership(session, course.id, student_b.id)
    session.commit()

    # 学生A：有答题数据 -> evidence_refs 非空
    for i in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student_a.id, course.id, q.id, is_correct=True)

    rec_with_data = generate_recommendation(session, student_a.id, course.id, force_recompute=True)
    assert rec_with_data.evidence_refs is not None
    assert isinstance(rec_with_data.evidence_refs, list)
    assert len(rec_with_data.evidence_refs) > 0

    # 学生B：无答题数据 -> evidence_refs 为空列表但字段存在
    rec_no_data = generate_recommendation(session, student_b.id, course.id, force_recompute=True)
    assert rec_no_data.evidence_refs is not None
    assert isinstance(rec_no_data.evidence_refs, list)
    assert len(rec_no_data.evidence_refs) == 0


def test_insufficient_data_outputs_need_more_evidence(session):
    """数据不足时输出"需要更多证据"：推荐标题包含"需要更多证据"或描述包含。

    新学生无答题数据 -> 推荐标题为"需要更多证据"。
    """
    teacher = _user(session, "cr_insuf_teacher", UserRole.TEACHER)
    student = _user(session, "cr_insuf_student")
    course = _setup_course(session, teacher, student)

    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    assert "需要更多证据" in rec.title or "需要更多证据" in rec.description
    assert rec.recommendation_type == "continue"
    assert "insufficient_data" in rec.reason_codes


# ==================== 答题证据测试 ====================

def test_quiz_results_form_learning_evidence(session):
    """答题结果形成LearningEvidence：答题后计算认知状态时生成LearningEvidenceRecord。

    有足够评判记录时，生成 quiz_accuracy 类型证据和 quiz_pattern 类型证据。
    """
    teacher = _user(session, "cr_ev_teacher", UserRole.TEACHER)
    student = _user(session, "cr_ev_student")
    course = _setup_course(session, teacher, student)

    # 创建答题记录（部分正确部分错误）
    for i in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))

    # 计算认知状态（会生成证据）
    compute_cognitive_state(session, student.id, course.id)

    # 查询 LearningEvidenceRecord
    evidence_records = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == student.id,
            LearningEvidenceRecord.course_id == course.id,
        )
    ).all()

    assert len(evidence_records) > 0

    # 应包含 quiz_accuracy 类型证据（表现分证据）
    evidence_types = {r.evidence_type for r in evidence_records}
    assert "quiz_accuracy" in evidence_types

    # 验证证据记录的基本字段
    for record in evidence_records:
        assert record.evidence_id is not None
        assert record.evidence_id != ""
        assert record.source == "cognitive_service"
        assert record.policy_version == COGNITIVE_POLICY_VERSION


def test_evidence_separated_from_question_attempt(session):
    """证据与交互状态分离：LearningEvidenceRecord独立于QuestionAttempt存储。

    LearningEvidenceRecord 存储在独立表中，通过 event_refs 引用答题记录ID，
    而非内嵌在 QuestionAttempt 中。
    """
    teacher = _user(session, "cr_sep_teacher", UserRole.TEACHER)
    student = _user(session, "cr_sep_student")
    course = _setup_course(session, teacher, student)

    # 创建答题记录
    attempt_ids = []
    for i in range(5):
        q = _create_published_question(session, course.id)
        attempt = _create_attempt(
            session, student.id, course.id, q.id, is_correct=(i < 3),
        )
        attempt_ids.append(attempt.id)

    # 计算认知状态
    compute_cognitive_state(session, student.id, course.id)

    # 查询 LearningEvidenceRecord
    evidence_records = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == student.id,
            LearningEvidenceRecord.course_id == course.id,
        )
    ).all()

    assert len(evidence_records) > 0

    # 验证证据记录独立于 QuestionAttempt 存储（不同的表）
    # QuestionAttempt 和 LearningEvidenceRecord 是不同的持久化实体
    qa_records = session.exec(
        select(QuestionAttempt).where(
            QuestionAttempt.student_id == student.id,
            QuestionAttempt.course_id == course.id,
        )
    ).all()
    assert len(qa_records) == 5

    # 证据记录的数量与答题记录不同（证据是聚合的，不是1对1）
    # quiz_accuracy 证据是1条（聚合所有答题），quiz_pattern 证据是1条（聚合错误模式）
    assert len(evidence_records) < len(qa_records)

    # 证据的 event_refs 引用了稳定来源事件ID
    all_event_refs = set()
    for record in evidence_records:
        all_event_refs.update(record.event_refs)
    assert len(all_event_refs) > 0

    attempt_event_refs = {record.source_event_id for record in qa_records}
    assert all_event_refs.issubset(attempt_event_refs)

    # LearningEvidenceRecord 有独立的表名和主键
    assert evidence_records[0].__tablename__ == "learning_evidence_records"
    assert qa_records[0].__tablename__ == "question_attempts"


def test_scored_performance_uses_scores_and_node_scope(session):
    teacher = _user(session, "cr_score_teacher", UserRole.TEACHER)
    student = _user(session, "cr_score_student")
    course = _setup_course(session, teacher, student)

    for score in (0.2, 0.6, 1.0):
        question = _create_published_question(session, course.id)
        question.knowledge_node_ids = [101]
        session.add(question)
        session.commit()
        attempt = _create_attempt(
            session,
            student.id,
            course.id,
            question.id,
            is_correct=score >= 0.999,
        )
        attempt.score = score
        session.add(attempt)
        session.commit()

    for _ in range(3):
        question = _create_published_question(session, course.id)
        question.knowledge_node_ids = [202]
        session.add(question)
        session.commit()
        attempt = _create_attempt(
            session,
            student.id,
            course.id,
            question.id,
            is_correct=False,
        )
        attempt.score = 0.0
        session.add(attempt)
        session.commit()

    node_state = compute_cognitive_state(session, student.id, course.id, node_id=101)
    assert node_state.observed_performance_score == pytest.approx(0.6)
    assert node_state.sample_size == 3
    assert node_state.evidence_refs
