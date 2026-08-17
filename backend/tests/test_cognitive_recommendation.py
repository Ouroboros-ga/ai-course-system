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
from app.models.graph_production_model import CourseKnowledgeNode, CourseKnowledgeNodeStatus
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
from app.services.recommendation_service import (
    generate_recommendation,
    lock_recommendation,
    mark_recommendation_consumed,
    refresh_cognition_and_recommendation,
    unlock_recommendation,
)

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


def test_cognition_fuses_scored_quiz_and_server_verified_code_evidence_by_weight(session):
    teacher = _user(session, "cr_fusion_teacher", UserRole.TEACHER)
    student = _user(session, "cr_fusion_student")
    course = _setup_course(session, teacher, student)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_cognition_fusion",
        title="Loop boundary",
    )
    session.add(node)
    session.flush()

    for is_correct in (True, False):
        question = _create_published_question(session, course.id)
        question.knowledge_node_ids = [node.id]
        session.add(question)
        session.commit()
        _create_attempt(
            session, student.id, course.id, question.id, is_correct=is_correct,
        )

    code_evidence = LearningEvidenceRecord(
        evidence_id="ev_coding_fusion_1",
        student_id=student.id,
        course_id=course.id,
        node_id=node.id,
        evidence_type="coding_execution",
        value=0.0,
        confidence=1.0,
        source="experiment_finalize_service",
        event_refs=["att_coding_fusion_1", "run_coding_fusion_1"],
    )
    session.add(code_evidence)
    session.commit()

    state = compute_cognitive_state(session, student.id, course.id, node_id=node.id)

    # (1.0 * 1.0 + 0.0 * 1.0 + 0.0 * 1.5) / 3.5
    assert state.observed_performance_score == pytest.approx(1 / 3.5)
    assert state.sample_size == 3
    assert code_evidence.evidence_id in state.evidence_refs
    assert "performance_from_quiz_accuracy" in state.reason_codes
    assert "performance_from_coding_execution" in state.reason_codes
    assert "performance_from_weighted_fusion" in state.reason_codes
    assert "source_code" not in str(state.model_dump())


def test_one_server_verified_code_failure_is_insufficient_for_mastery_conclusion(session):
    teacher = _user(session, "cr_code_only_teacher", UserRole.TEACHER)
    student = _user(session, "cr_code_only_student")
    course = _setup_course(session, teacher, student)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_code_only",
        title="Array bounds",
    )
    session.add(node)
    session.flush()
    session.add(LearningEvidenceRecord(
        evidence_id="ev_coding_only_failure",
        student_id=student.id,
        course_id=course.id,
        node_id=node.id,
        evidence_type="coding_execution",
        value=0.0,
        confidence=1.0,
        source="experiment_finalize_service",
        event_refs=["att_coding_only", "run_coding_only"],
    ))
    session.commit()

    state = compute_cognitive_state(session, student.id, course.id, node_id=node.id)

    assert state.sample_size == 1
    assert state.observed_performance_score is None
    assert state.mastery_level == "unknown"
    assert "insufficient_effective_scored_weight" in state.reason_codes


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
    """低表现+置信度不足：表现分<0.5且置信度<0.6时，推荐策略为诊断题。

    reason_codes 包含 diagnostic_not_weakness，不直接判定薄弱。
    3次答题（1正确2错误）-> perf=1/3≈0.33 < 0.5
    M1 连续化：3 个评分项 -> confidence = 3/6 = 0.5 < CONFIDENCE_HIGH=0.6
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
    # M1 连续化：3 个评分项 -> 0.5，未达高置信门槛 0.6（不判弱、不高优先）
    assert state.evidence_confidence < 0.6

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


# ==================== 批次4：教师安全阀 - 锁定推荐项测试 ====================


def test_lock_recommendation_prevents_overwrite(session):
    """教师锁定推荐项后，generate_recommendation 不应覆盖该锁定项。

    场景：先生成低表现推荐（practice_quiz, high），教师锁定后，再次调用
    generate_recommendation（即使 force_recompute=True）应直接返回锁定的
    推荐记录，不创建新记录，且字段保持锁定时的快照。
    """
    teacher = _user(session, "cr_lock_teacher", UserRole.TEACHER)
    student = _user(session, "cr_lock_student")
    course = _setup_course(session, teacher, student)

    # 7次答题：3正确4错误 -> 低表现+高置信度 -> practice_quiz, high
    for i in range(7):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))

    original_rec = generate_recommendation(session, student.id, course.id, force_recompute=True)
    assert original_rec.recommendation_type == "practice_quiz"
    assert original_rec.priority == "high"
    assert original_rec.is_locked is False

    # 教师锁定该推荐
    locked = lock_recommendation(session, original_rec.recommendation_id, teacher.id)
    assert locked is not None
    assert locked.is_locked is True
    assert locked.locked_by == teacher.id
    assert locked.locked_at is not None
    assert locked.recommendation_id == original_rec.recommendation_id

    # 再次生成推荐（即使 force_recompute=True）应返回锁定的推荐，不创建新记录
    rerun = generate_recommendation(session, student.id, course.id, force_recompute=True)
    assert rerun.recommendation_id == original_rec.recommendation_id
    assert rerun.is_locked is True
    assert rerun.locked_by == teacher.id

    # 数据库中只有一条推荐记录（未生成新记录覆盖锁定项）
    all_records = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.student_id == student.id,
            RecommendationRecord.course_id == course.id,
        )
    ).all()
    assert len(all_records) == 1
    assert all_records[0].is_locked is True


def test_unlock_recommendation_allows_recompute(session):
    """教师解锁后，generate_recommendation 可重新生成推荐覆盖旧记录。

    场景：锁定推荐后解锁，再次调用 generate_recommendation(force_recompute=True)
    应生成新的推荐记录，旧锁定记录保留但不再阻止重新生成。
    """
    teacher = _user(session, "cr_unlock_teacher", UserRole.TEACHER)
    student = _user(session, "cr_unlock_student")
    course = _setup_course(session, teacher, student)

    # 低表现 -> practice_quiz, high
    for i in range(7):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))

    original_rec = generate_recommendation(session, student.id, course.id, force_recompute=True)
    lock_recommendation(session, original_rec.recommendation_id, teacher.id)

    # 解锁
    unlocked = unlock_recommendation(session, original_rec.recommendation_id)
    assert unlocked is not None
    assert unlocked.is_locked is False
    assert unlocked.locked_by is None
    assert unlocked.locked_at is None

    # 解锁后可重新生成（创建新记录）
    rerun = generate_recommendation(session, student.id, course.id, force_recompute=True)
    assert rerun.recommendation_id != original_rec.recommendation_id
    assert rerun.is_locked is False

    # 数据库中存在两条推荐记录（旧解锁 + 新生成）
    all_records = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.student_id == student.id,
            RecommendationRecord.course_id == course.id,
        )
    ).all()
    assert len(all_records) == 2


def test_lock_recommendation_unknown_id_returns_none(session):
    """锁定不存在的推荐ID时返回 None（fail-closed，不抛异常）。"""
    teacher = _user(session, "cr_lock_unknown_teacher", UserRole.TEACHER)
    result = lock_recommendation(session, "non-existent-id", teacher.id)
    assert result is None

    result = unlock_recommendation(session, "non-existent-id")
    assert result is None


def test_lock_recommendation_scoped_to_node(session):
    """锁定推荐按 node_id 隔离：锁定节点A的推荐不影响节点B的重新生成。

    场景：在节点A生成并锁定推荐后，在节点B调用 generate_recommendation
    应能正常生成节点B的推荐（不受节点A锁定影响）。
    """
    teacher = _user(session, "cr_lock_node_teacher", UserRole.TEACHER)
    student = _user(session, "cr_lock_node_student")
    course = _setup_course(session, teacher, student)

    # 在节点101创建答题数据
    for i in range(5):
        q = _create_published_question(session, course.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=False)

    # 节点101生成推荐并锁定
    rec_node_a = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=True,
    )
    lock_recommendation(session, rec_node_a.recommendation_id, teacher.id)

    # 节点202生成推荐（不应被节点101的锁定阻止）
    rec_node_b = generate_recommendation(
        session, student.id, course.id, node_id=202, force_recompute=True,
    )
    assert rec_node_b.recommendation_id != rec_node_a.recommendation_id
    assert rec_node_b.is_locked is False
    assert rec_node_b.node_id == 202

    # 节点101再次生成应返回锁定项
    rerun_a = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=True,
    )
    assert rerun_a.recommendation_id == rec_node_a.recommendation_id
    assert rerun_a.is_locked is True


def test_lock_recommendation_api_requires_permission(client, session):
    """锁定推荐API需 analytics.view_member 或 agent.policy.configure 权限。

    场景：无课程成员关系的用户调用锁定接口应返回 403；
    具备 owner 角色的教师（默认拥有 analytics.view_member）可成功锁定。
    """
    teacher = _user(session, "cr_lock_api_teacher", UserRole.TEACHER)
    student = _user(session, "cr_lock_api_student")
    course = _setup_course(session, teacher, student)

    # 学生生成推荐
    for i in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    # 无课程成员关系的用户调用锁定 -> 403
    outsider = _user(session, "cr_lock_api_outsider", UserRole.TEACHER)
    outsider_token = _token(outsider)
    resp = client.post(
        f"{CR}/recommendation/{rec.recommendation_id}/lock",
        headers=_auth(outsider_token),
    )
    assert resp.status_code == 403

    # 课程教师（owner，具备 analytics.view_member）调用锁定 -> 200
    teacher_token = _token(teacher)
    resp = client.post(
        f"{CR}/recommendation/{rec.recommendation_id}/lock",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["is_locked"] is True
    assert body["locked_by"] == teacher.id
    assert body["locked_at"] is not None


def test_unlock_recommendation_api_requires_permission(client, session):
    """解锁推荐API需 analytics.view_member 或 agent.policy.configure 权限。"""
    teacher = _user(session, "cr_unlock_api_teacher", UserRole.TEACHER)
    student = _user(session, "cr_unlock_api_student")
    course = _setup_course(session, teacher, student)

    for i in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)
    lock_recommendation(session, rec.recommendation_id, teacher.id)

    # 无成员关系用户调用解锁 -> 403
    outsider = _user(session, "cr_unlock_api_outsider", UserRole.TEACHER)
    outsider_token = _token(outsider)
    resp = client.post(
        f"{CR}/recommendation/{rec.recommendation_id}/unlock",
        headers=_auth(outsider_token),
    )
    assert resp.status_code == 403
    # 推荐仍处于锁定状态
    refreshed = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == rec.recommendation_id,
        )
    ).first()
    assert refreshed.is_locked is True

    # 课程教师调用解锁 -> 200
    teacher_token = _token(teacher)
    resp = client.post(
        f"{CR}/recommendation/{rec.recommendation_id}/unlock",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["is_locked"] is False
    assert body["locked_by"] is None


def test_lock_api_returns_404_for_unknown_recommendation(client, session):
    """锁定/解锁不存在的推荐ID时返回 404。"""
    teacher = _user(session, "cr_lock_404_teacher", UserRole.TEACHER)
    teacher_token = _token(teacher)

    resp = client.post(
        f"{CR}/recommendation/non-existent-id/lock",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 404

    resp = client.post(
        f"{CR}/recommendation/non-existent-id/unlock",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 404


def test_lock_recommendation_does_not_block_consumed(session):
    """已消费的锁定推荐不再阻止重新生成（仅未消费的锁定项阻止覆盖）。

    场景：锁定推荐后学生消费该推荐，再次调用 generate_recommendation
    应能生成新推荐（_find_locked_unconsumed 只匹配 consumed=False 的锁定项）。
    """
    teacher = _user(session, "cr_lock_consumed_teacher", UserRole.TEACHER)
    student = _user(session, "cr_lock_consumed_student")
    course = _setup_course(session, teacher, student)

    for i in range(5):
        q = _create_published_question(session, course.id)
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 3))
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)
    lock_recommendation(session, rec.recommendation_id, teacher.id)

    # 学生消费该推荐
    mark_recommendation_consumed(session, rec.recommendation_id, student.id)
    refreshed = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == rec.recommendation_id,
        )
    ).first()
    assert refreshed.consumed is True
    assert refreshed.is_locked is True

    # 已消费的锁定推荐不再阻止重新生成
    rerun = generate_recommendation(session, student.id, course.id, force_recompute=True)
    assert rerun.recommendation_id != rec.recommendation_id
    assert rerun.is_locked is False


# ==================== 批次3：已确认薄弱前置集合推荐测试 ====================


def test_prereq_review_recommendation_for_confirmed_weak_prerequisite(session):
    """批次3：当当前知识点的先修节点被确认为薄弱（低表现+高置信度）时，
    生成 PREREQ_REVIEW 推荐而非普通补弱练习。

    验收：低置信度只进入"需要更多证据"，不直接断言薄弱。
    """
    from app.services.graph_production_service import (
        create_evidence as create_graph_evidence,
        publish_snapshot,
    )
    from app.models.access_control_model import CourseCapability

    teacher = _user(session, "cr_prereq_teacher", UserRole.TEACHER)
    student = _user(session, "cr_prereq_student")
    course = _setup_course(session, teacher, student)
    # 开启 knowledge_graph capability
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    if cap:
        cap.knowledge_graph = True
        session.add(cap)
        session.commit()

    # 发布图谱快照：n2(先修) -> n1(当前)
    evidence = create_graph_evidence(
        session, course_id=course.id, text_snippet="前置知识证据"
    )
    publish_snapshot(
        session, course_id=course.id,
        nodes=[
            {"node_id": "101", "label": "当前知识点", "type": "knowledge_point"},
            {"node_id": "202", "label": "前置知识点", "type": "knowledge_point"},
        ],
        relations=[{
            "relation_id": "r1", "source": "202", "target": "101",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }],
        user_id=teacher.id,
    )

    # 在先修节点 202 上制造低表现+高置信度的认知状态（5次全错）
    for _ in range(5):
        q = _create_published_question(session, course.id, QuestionDifficulty.EASY)
        q.knowledge_node_ids = [202]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=False)
    prereq_state = compute_cognitive_state(session, student.id, course.id, node_id=202)
    assert prereq_state.observed_performance_score is not None
    assert prereq_state.observed_performance_score < 0.5
    assert prereq_state.evidence_confidence is not None
    assert prereq_state.evidence_confidence >= 0.6

    # 在当前节点 101 上也有一些答题数据
    for i in range(3):
        q = _create_published_question(session, course.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 2))

    # 生成当前节点 101 的推荐 -> 应为 PREREQ_REVIEW
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=True,
    )
    assert rec.recommendation_type == "prereq_review"
    assert rec.priority == "high"
    assert "confirmed_weak_prerequisite" in rec.reason_codes
    assert "prerequisite_review" in rec.reason_codes
    assert any("weak_prerequisite_node=202" in rc for rc in rec.reason_codes)
    assert rec.policy_version == COGNITIVE_POLICY_VERSION
    assert rec.evidence_refs  # 携带证据引用


def test_prereq_review_not_triggered_for_low_confidence_prerequisite(session):
    """批次3：先修节点置信度不足时不触发 PREREQ_REVIEW（低置信度只进入需要更多证据）。

    验收：低置信度只进入"需要更多证据"，不直接断言薄弱。
    """
    from app.services.graph_production_service import (
        create_evidence as create_graph_evidence,
        publish_snapshot,
    )
    from app.models.access_control_model import CourseCapability

    teacher = _user(session, "cr_prereq_lc_teacher", UserRole.TEACHER)
    student = _user(session, "cr_prereq_lc_student")
    course = _setup_course(session, teacher, student)
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    if cap:
        cap.knowledge_graph = True
        session.add(cap)
        session.commit()

    evidence = create_graph_evidence(
        session, course_id=course.id, text_snippet="前置知识证据"
    )
    publish_snapshot(
        session, course_id=course.id,
        nodes=[
            {"node_id": "101", "label": "当前知识点"},
            {"node_id": "202", "label": "前置知识点"},
        ],
        relations=[{
            "relation_id": "r1", "source": "202", "target": "101",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }],
        user_id=teacher.id,
    )

    # 先修节点 202 仅 1 次答题（样本不足，置信度低）-> 不应断言薄弱
    q = _create_published_question(session, course.id, QuestionDifficulty.EASY)
    q.knowledge_node_ids = [202]
    session.add(q)
    session.commit()
    _create_attempt(session, student.id, course.id, q.id, is_correct=False)
    prereq_state = compute_cognitive_state(session, student.id, course.id, node_id=202)
    # 样本不足时置信度低
    assert prereq_state.evidence_confidence is None or prereq_state.evidence_confidence < 0.6

    # 当前节点 101 答题
    for i in range(3):
        q = _create_published_question(session, course.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 2))

    # 生成推荐 -> 不应为 PREREQ_REVIEW（因先修复置信度不足）
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=True,
    )
    assert rec.recommendation_type != "prereq_review"


def test_prereq_review_not_triggered_without_graph_snapshot(session):
    """批次3：无已发布图谱快照时不触发 PREREQ_REVIEW（回退到普通推荐）。"""
    teacher = _user(session, "cr_prereq_nograph_teacher", UserRole.TEACHER)
    student = _user(session, "cr_prereq_nograph_student")
    course = _setup_course(session, teacher, student)

    # 不发布图谱快照，直接在节点上答题
    for i in range(5):
        q = _create_published_question(session, course.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=False)

    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=True,
    )
    assert rec.recommendation_type != "prereq_review"


def test_prereq_recommendation_cross_course_isolation(session):
    """批次3：课程A的图谱先修关系不影响课程B的推荐（课程隔离验收）。"""
    from app.services.graph_production_service import (
        create_evidence as create_graph_evidence,
        publish_snapshot,
    )
    from app.models.access_control_model import CourseCapability

    teacher_a = _user(session, "cr_prereq_iso_ta", UserRole.TEACHER)
    teacher_b = _user(session, "cr_prereq_iso_tb", UserRole.TEACHER)
    student = _user(session, "cr_prereq_iso_student")
    course_a = _setup_course(session, teacher_a, student)
    course_b = _setup_course(session, teacher_b, student)

    for c in (course_a, course_b):
        cap = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == c.id)
        ).first()
        if cap:
            cap.knowledge_graph = True
            session.add(cap)
    session.commit()

    # 仅在课程A发布图谱快照
    evidence = create_graph_evidence(
        session, course_id=course_a.id, text_snippet="课程A前置证据"
    )
    publish_snapshot(
        session, course_id=course_a.id,
        nodes=[
            {"node_id": "101", "label": "当前"},
            {"node_id": "202", "label": "前置"},
        ],
        relations=[{
            "relation_id": "r1", "source": "202", "target": "101",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }],
        user_id=teacher_a.id,
    )

    # 课程B无图谱快照，在节点101答题
    for i in range(5):
        q = _create_published_question(session, course_b.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course_b.id, q.id, is_correct=False)

    # 课程B的推荐不应是 PREREQ_REVIEW（无图谱快照）
    rec_b = generate_recommendation(
        session, student.id, course_b.id, node_id=101, force_recompute=True,
    )
    assert rec_b.recommendation_type != "prereq_review"
    assert rec_b.course_id == course_b.id


# ==================== P2-13: 低置信度永不 high priority ====================


@pytest.mark.parametrize(
    "scenario, attempt_count, correct_count, expected_confidence_lt",
    [
        # 数据完全不足：0 次答题 -> confidence=None (unknown)
        ("zero_attempts", 0, 0, None),
        # M1 连续化：1 次答题（权重 1）-> confidence=0.25 < 0.6
        ("one_attempt_all_wrong", 1, 0, 0.6),
        # M1 连续化：2 次答题（权重 2）-> confidence=0.40 < 0.6
        ("two_attempts_all_wrong", 2, 0, 0.6),
        # M1 连续化：3 次答题（权重 3）-> confidence=0.50 < 0.6
        ("three_attempts_low_perf", 3, 1, 0.6),
        # M1 连续化：4 次答题（权重 4）-> confidence≈0.571 < 0.6
        ("four_attempts_all_wrong", 4, 0, 0.6),
    ],
)
def test_low_confidence_never_produces_high_priority(
    session, scenario, attempt_count, correct_count, expected_confidence_lt,
):
    """P2-13: 低置信度场景下推荐 priority 永不为 "high"。

    project_memory.md 硬约束：低置信度推荐必须只进入"需要更多证据"状态，
    不得直接断言薄弱（不得为 high priority）。

    覆盖五种低置信度场景：
    - 0 次答题（数据完全不足，confidence=None）
    - 1/2/3/4 次答题（M1 连续化后 confidence 单调上升但均 < 0.6，
      未达 CONFIDENCE_HIGH 高置信门槛，不判弱、不高优先）

    在所有这些场景下：
    - rec.priority != "high"
    - rec.priority ∈ {"low", "medium"}
    - reason_codes 包含"需要更多证据"语义标记
    """
    teacher = _user(session, f"cr_p213_{scenario}_teacher", UserRole.TEACHER)
    student = _user(session, f"cr_p213_{scenario}_student")
    course = _setup_course(session, teacher, student)

    # 按场景构造答题数据
    for i in range(attempt_count):
        q = _create_published_question(session, course.id)
        _create_attempt(
            session, student.id, course.id, q.id,
            is_correct=(i < correct_count),
        )

    # 计算认知状态，验证置信度确实为低
    state = compute_cognitive_state(session, student.id, course.id)
    if expected_confidence_lt is None:
        # 0 次答题：confidence 应为 None（unknown）
        assert state.evidence_confidence is None, (
            f"场景 {scenario}: 0 次答题置信度应为 None，实际 {state.evidence_confidence}"
        )
        assert state.sample_size == 0
    else:
        assert state.evidence_confidence is not None
        assert state.evidence_confidence < expected_confidence_lt, (
            f"场景 {scenario}: 置信度应 < {expected_confidence_lt}，"
            f"实际 {state.evidence_confidence}"
        )

    # 生成推荐
    rec = generate_recommendation(session, student.id, course.id, force_recompute=True)

    # 核心断言：低置信度下 priority 永不为 high
    assert rec.priority != "high", (
        f"场景 {scenario}: 低置信度（confidence={state.evidence_confidence}）"
        f"下 priority 不应为 high，实际 {rec.priority}，"
        f"reason_codes={rec.reason_codes}"
    )
    # priority 只能是 low 或 medium
    assert rec.priority in ("low", "medium"), (
        f"场景 {scenario}: priority 应为 low/medium，实际 {rec.priority}"
    )

    # 不应有"已确认薄弱"语义的 reason_code（低置信度不武断）
    assert "confirmed_weak_prerequisite" not in rec.reason_codes
    # 数据不足场景应明确标记"需要更多证据"语义
    if state.evidence_confidence is None or state.observed_performance_score is None:
        assert (
            "insufficient_data" in rec.reason_codes
            or "insufficient_performance_data" in rec.reason_codes
            or "diagnostic_not_weakness" in rec.reason_codes
            or "need_more_evidence" in rec.reason_codes
        ), f"场景 {scenario}: 数据不足应标记需要更多证据，reason_codes={rec.reason_codes}"


def test_low_confidence_prerequisite_never_triggers_high_priority_prereq_review(session):
    """P2-13 补充：先修节点低置信度时，不触发 PREREQ_REVIEW（high priority）。

    project_memory.md 硬约束：低置信度只进入"需要更多证据"，
    不直接断言薄弱。PREREQ_REVIEW 是 high priority 推荐类型，
    只有当先修节点置信度达标（>= 0.6）时才触发。

    本测试构造先修节点仅有 1 次答题（低置信度）的场景，
    验证不触发 PREREQ_REVIEW，且当前节点推荐 priority 不为 high。
    """
    from app.services.graph_production_service import (
        create_evidence as create_graph_evidence,
        publish_snapshot,
    )
    from app.models.access_control_model import CourseCapability

    teacher = _user(session, "cr_p213_prereq_teacher", UserRole.TEACHER)
    student = _user(session, "cr_p213_prereq_student")
    course = _setup_course(session, teacher, student)
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    if cap:
        cap.knowledge_graph = True
        session.add(cap)
        session.commit()

    # 发布图谱快照：n2(先修) -> n1(当前)
    evidence = create_graph_evidence(
        session, course_id=course.id, text_snippet="先修知识证据"
    )
    publish_snapshot(
        session, course_id=course.id,
        nodes=[
            {"node_id": "101", "label": "当前知识点"},
            {"node_id": "202", "label": "前置知识点"},
        ],
        relations=[{
            "relation_id": "r1", "source": "202", "target": "101",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }],
        user_id=teacher.id,
    )

    # 先修节点 202 仅 2 次答题（低置信度，confidence=0.3 < 0.6）
    for i in range(2):
        q = _create_published_question(session, course.id, QuestionDifficulty.EASY)
        q.knowledge_node_ids = [202]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=False)
    prereq_state = compute_cognitive_state(session, student.id, course.id, node_id=202)
    assert prereq_state.evidence_confidence is not None
    assert prereq_state.evidence_confidence < 0.6, (
        f"先修节点置信度应 < 0.6（低置信度），实际 {prereq_state.evidence_confidence}"
    )

    # 当前节点 101 答题
    for i in range(3):
        q = _create_published_question(session, course.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 1))

    # 生成当前节点 101 的推荐
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=True,
    )

    # 核心断言：低置信度先修节点不应触发 PREREQ_REVIEW（high priority）
    assert rec.recommendation_type != "prereq_review", (
        "先修节点低置信度时不应触发 PREREQ_REVIEW"
    )
    assert rec.priority != "high", (
        f"先修节点低置信度时当前节点推荐 priority 不应为 high，"
        f"实际 {rec.priority}，reason_codes={rec.reason_codes}"
    )
    assert rec.priority in ("low", "medium")


def test_kn_identity_snapshot_and_answer_refresh_persist_formal_links(session):
    """Automatic snapshots and answer refresh keep graph/cognitive IDs aligned."""
    teacher = _user(session, "kn_identity_teacher", UserRole.TEACHER)
    student = _user(session, "kn_identity_student")
    course = _setup_course(session, teacher, student)

    current = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_current",
        title="当前知识点",
        status=CourseKnowledgeNodeStatus.PUBLISHED,
    )
    session.add(current)
    session.commit()
    session.refresh(current)

    from app.services.graph_production_service import publish_snapshot

    snapshot = publish_snapshot(
        session,
        course_id=course.id,
        nodes=[{
            "id": current.node_key,
            "identity_id": current.id,
            "title": current.title,
            "type": "knowledge_point",
        }],
        relations=[],
        user_id=teacher.id,
    )

    question = _create_published_question(session, course.id)
    question.knowledge_node_ids = [current.id]
    session.add(question)
    session.commit()
    attempt = _create_attempt(
        session, student.id, course.id, question.id, is_correct=True,
    )

    from app.services.cognitive_service import record_scored_evidence

    evidence = record_scored_evidence(session, attempt)
    session.commit()
    state, recommendation = refresh_cognition_and_recommendation(
        session,
        student_id=student.id,
        course_id=course.id,
        node_id=evidence.node_id,
    )

    assert state is not None and state.node_id == current.id
    assert recommendation is not None
    assert recommendation.graph_snapshot_id == snapshot.snapshot_id
    assert recommendation.knowledge_node_id == current.id
