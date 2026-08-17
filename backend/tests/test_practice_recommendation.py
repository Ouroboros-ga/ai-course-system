"""阶段5 题库、练习推荐、正式学习证据 端到端测试。

覆盖路线图 §8 验收与 PageDesign前端API契约规划.md §3.4 PRACTICE：
- 题库导入运行：创建/列表/详情，跨课程隔离
- AI 草稿审核：教师通过升级为 QuestionBankItem，拒绝状态机；草稿不直接对学生发布
- 个性化推荐运行：题库优先检索、无匹配题生成草稿、policy_version/six_dimensions/
  reason_codes/evidence_refs/confidence 齐备；数据不足返回 unknown 语义
- 学生开始推荐项：草稿未审核前不可开始作答（409）
- 答题提交：自动判分、写入正式 LearningEvidence、LearningEvidenceLink 上下文追溯
- 评分策略版本化：不同 purpose 不同策略
- 学习动作完成：非评分动作不抬高表现分，评分型动作写入正式证据

四类必备测试：成功、权限拒绝、跨课程拒绝、降级（草稿未审核、数据不足）。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.cognitive_state_model import (
    CognitiveState,
    COGNITIVE_POLICY_VERSION,
    LearningEvidenceRecord,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.practice_recommendation_model import (
    AssessmentPolicy,
    AssessmentPurpose,
    EvidenceLinkContext,
    GenerationDraftStatus,
    ImportRunStatus,
    LearningEvidenceLink,
    QuestionGenerationDraft,
    QuestionImportRun,
    QuestionRecommendationItem,
    QuestionRecommendationRun,
    QuestionSource,
    RecommendationRunStatus,
)
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
)
from app.services.practice_recommendation_service import (
    PRACTICE_POLICY_VERSION,
    assessment_policy_service,
    learning_evidence_link_service,
    practice_recommendation_service,
    question_generation_draft_service,
    question_import_service,
)


PRACTICE = "/api/v1/practice"
FACADE = "/api/v1/facade"
QUESTION_BANK = "/api/v1/question-bank"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(
    session,
    teacher_id: int,
    *,
    title: str = "Stage5 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s5-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_capabilities(session, course_id: int, **overrides) -> None:
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True,
        "course_building": True,
        "knowledge_graph": True,
        "evidence": True,
        "experiment": False,
        "coding_sandbox": False,
        "cognitive_analysis": True,
        "safety_policy": False,
    }
    defaults.update(overrides)
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
    enr = StudentEnrollment(
        student_id=student_id,
        course_id=course_id,
        overall_progress=0.0,
        last_study_time=datetime.utcnow(),
        is_active=True,
    )
    session.add(enr)
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _published_question(
    session,
    course_id: int,
    *,
    text: str = "二分查找的时间复杂度是？",
    answer: str = "O(log n)",
    node_id: int | None = None,
    question_type: QuestionType = QuestionType.SHORT_ANSWER,
    status: QuestionStatus = QuestionStatus.PUBLISHED,
) -> QuestionBankItem:
    q = QuestionBankItem(
        question_text=text,
        answer=answer,
        question_type=question_type,
        difficulty=QuestionDifficulty.MEDIUM,
        course_id=course_id,
        status=status,
        knowledge_node_ids=[node_id] if node_id else [],
        is_latest=True,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def _make_cognitive_state(
    session,
    *,
    student_id: int,
    course_id: int,
    node_id: int | None = None,
    observed_performance: float | None = 0.7,
    evidence_confidence: float | None = 0.8,
    sample_size: int = 5,
) -> CognitiveState:
    """直接构造一个 CognitiveState 记录，避免依赖 attempt 数据。"""
    state = CognitiveState(
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        observed_performance_score=observed_performance,
        evidence_confidence=evidence_confidence,
        confusion_risk=0.2,
        inquiry_depth=None,
        hint_dependency=None,
        explanation_need=None,
        mastery_level="proficient",
        mastery_score=observed_performance,
        policy_version=COGNITIVE_POLICY_VERSION,
        evidence_refs=["ev_seed_1"],
        reason_codes=["performance_from_quiz_accuracy"],
        sample_size=sample_size,
        is_latest=True,
        computed_at=datetime.utcnow(),
    )
    session.add(state)
    session.commit()
    session.refresh(state)
    return state


def _create_attempt(
    session,
    *,
    course_id: int,
    student_id: int,
    question_id: int,
    is_correct: bool | None = None,
    score: float | None = None,
) -> QuestionAttempt:
    attempt = QuestionAttempt(
        question_id=question_id,
        course_id=course_id,
        student_id=student_id,
        source_event_id=f"qe_{uuid.uuid4().hex}",
        measurement_role="scored_performance",
        question_version=1,
        question_content_hash="hash",
        student_answer="",
        is_correct=is_correct,
        score=score,
        cognitive_context={},
        judged_by="auto" if is_correct is not None else "teacher",
        judged_at=datetime.utcnow() if is_correct is not None else None,
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return attempt


# ---------------------------------------------------------------------------
# 1. 题库导入运行
# ---------------------------------------------------------------------------


def test_create_import_run_returns_202(client, session):
    """教师创建题库导入运行，返回 202 + run_id + status=pending。"""
    teacher = _user(session, "s5_import_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/import-runs",
        json={
            "source_file": "题库.xlsx",
            "source_object_key": "uploads/qb.xlsx",
            "total_rows": 100,
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 202
    data = body["data"]
    assert data["run_id"].startswith("qir_")
    assert data["status"] == "pending"
    assert data["total_rows"] == 100


def test_list_import_runs_isolated_by_course(client, session):
    """题库导入运行按课程隔离。"""
    teacher_a = _user(session, "s5_import_iso_a")
    teacher_b = _user(session, "s5_import_iso_b")
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    question_import_service.create_run(
        session,
        course_id=course_a.id,
        source_file="a.xlsx",
        initiated_by=teacher_a.id,
    )
    question_import_service.create_run(
        session,
        course_id=course_b.id,
        source_file="b.xlsx",
        initiated_by=teacher_b.id,
    )
    session.commit()

    resp_a = client.get(
        f"{PRACTICE}/course/{course_a.id}/import-runs",
        headers=_auth(_token(teacher_a)),
    )
    assert resp_a.status_code == 200
    data_a = resp_a.json()["data"]
    assert data_a["total"] == 1
    assert data_a["items"][0]["source_file"] == "a.xlsx"

    resp_b = client.get(
        f"{PRACTICE}/course/{course_b.id}/import-runs",
        headers=_auth(_token(teacher_b)),
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["data"]["total"] == 1
    assert resp_b.json()["data"]["items"][0]["source_file"] == "b.xlsx"


def test_get_import_run_unknown_returns_404(client, session):
    """查询不存在的导入运行返回 404。"""
    teacher = _user(session, "s5_import_404_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.get(
        f"{PRACTICE}/course/{course.id}/import-runs/qir_nonexistent",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. AI 草稿审核
# ---------------------------------------------------------------------------


def test_approve_draft_upgrades_to_published_question(client, session):
    """教师审核通过 AI 草稿：升级为正式 QuestionBankItem（status=published）。"""
    teacher = _user(session, "s5_approve_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    draft = question_generation_draft_service.create_draft(
        session,
        course_id=course.id,
        node_id=10,
        question_type="short_answer",
        question_text="解释什么是递归。",
        answer="递归是函数自调用。",
        difficulty="medium",
        generation_purpose="diagnose",
        six_dimensions={"observed_performance_score": 0.5},
        reason_codes=["insufficient_data"],
        evidence_refs=["ev_seed_1"],
        confidence=0.6,
        generated_by=teacher.id,
    )
    session.commit()

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/drafts/{draft.draft_id}/approve",
        json={"review_comment": "题目合适", "publish_status": "published"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["draft"]["status"] == "approved"
    assert data["draft"]["upgraded_question_id"] is not None
    assert data["question"]["status"] == "published"
    assert data["question"]["is_latest"] is True

    # 升级后的题目可被学生检索
    student = _user(session, "s5_approve_student", UserRole.STUDENT)
    _enroll_student(session, course.id, student.id)
    questions = session.exec(
        select(QuestionBankItem).where(
            QuestionBankItem.course_id == course.id,
            QuestionBankItem.status == QuestionStatus.PUBLISHED,
            QuestionBankItem.is_latest == True,  # noqa: E712
        )
    ).all()
    assert any(q.id == data["question"]["question_id"] for q in questions)


def test_approve_draft_idempotent_rejects(client, session):
    """已 approved 的草稿不可重复审核，返回 409。"""
    teacher = _user(session, "s5_approve_repeat_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    draft = question_generation_draft_service.create_draft(
        session,
        course_id=course.id,
        node_id=11,
        question_type="short_answer",
        question_text="测试题",
        answer="答案",
        generated_by=teacher.id,
    )
    session.commit()
    question_generation_draft_service.approve_draft(
        session,
        course_id=course.id,
        draft_id=draft.draft_id,
        reviewed_by=teacher.id,
    )
    session.commit()

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/drafts/{draft.draft_id}/approve",
        json={},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_code"] == "STATE_CONFLICT"


def test_reject_draft_changes_status(client, session):
    """教师拒绝草稿后状态变为 rejected，且不可再 approve。"""
    teacher = _user(session, "s5_reject_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    draft = question_generation_draft_service.create_draft(
        session,
        course_id=course.id,
        node_id=12,
        question_type="short_answer",
        question_text="错误题目",
        answer="错误答案",
        generated_by=teacher.id,
    )
    session.commit()

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/drafts/{draft.draft_id}/reject",
        json={"review_comment": "答案有误"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "rejected"

    # rejected 不可再 approve
    resp2 = client.post(
        f"{PRACTICE}/course/{course.id}/drafts/{draft.draft_id}/approve",
        json={},
        headers=_auth(_token(teacher)),
    )
    assert resp2.status_code == 409


def test_list_drafts_filters_by_status(client, session):
    """列出草稿，按 status 过滤。"""
    teacher = _user(session, "s5_list_drafts_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    d1 = question_generation_draft_service.create_draft(
        session, course_id=course.id, node_id=13, question_type="short_answer",
        question_text="草稿 1", answer="答案 1", generated_by=teacher.id,
    )
    d2 = question_generation_draft_service.create_draft(
        session, course_id=course.id, node_id=14, question_type="short_answer",
        question_text="草稿 2", answer="答案 2", generated_by=teacher.id,
    )
    session.commit()
    question_generation_draft_service.approve_draft(
        session, course_id=course.id, draft_id=d2.draft_id, reviewed_by=teacher.id,
    )
    session.commit()

    resp = client.get(
        f"{PRACTICE}/course/{course.id}/drafts?status=draft",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["draft_id"] == d1.draft_id


# ---------------------------------------------------------------------------
# 3. 个性化推荐运行
# ---------------------------------------------------------------------------


def test_create_recommendation_with_bank_question(client, session):
    """题库命中已发布题时，推荐项 question_source=bank。"""
    teacher = _user(session, "s5_rec_bank_teacher")
    student = _user(session, "s5_rec_bank_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _published_question(
        session, course_id=course.id, node_id=20,
        text="什么是二分查找？", answer="二分查找是...",
    )
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=20,
        observed_performance=0.7, evidence_confidence=0.8, sample_size=5,
    )

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 20, "purpose": "diagnose", "item_count": 1, "allow_generation": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201
    data = body["data"]
    assert data["status"] == "succeeded"
    assert data["item_count"] == 1
    assert data["policy_version"] == PRACTICE_POLICY_VERSION
    # 必须携带可解释字段
    assert "six_dimensions" in data
    assert "reason_codes" in data
    assert "evidence_refs" in data
    assert isinstance(data["confidence"], (int, float))


def test_create_recommendation_generates_draft_when_no_bank_match(client, session):
    """题库无匹配题且 allow_generation=True 时生成 AI 草稿（不直接发布）。"""
    teacher = _user(session, "s5_rec_gen_teacher")
    student = _user(session, "s5_rec_gen_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=21,
        observed_performance=0.4, evidence_confidence=0.3, sample_size=2,
    )

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 21, "purpose": "remediation", "item_count": 2, "allow_generation": True},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["item_count"] == 2
    # 数据不足时 reason_codes 应包含 evidence_needed
    assert "evidence_needed" in data["reason_codes"]


def test_recommendation_carry_policy_and_six_dimensions(client, session):
    """推荐运行必须携带 policy_version, six_dimensions, reason_codes, evidence_refs, confidence。"""
    teacher = _user(session, "s5_rec_meta_teacher")
    student = _user(session, "s5_rec_meta_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=22,
    )

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 22, "purpose": "diagnose", "item_count": 1, "allow_generation": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["policy_version"] == PRACTICE_POLICY_VERSION
    assert "observed_performance_score" in data["six_dimensions"]
    assert "evidence_confidence" in data["six_dimensions"]
    assert "confusion_risk" in data["six_dimensions"]
    assert "inquiry_depth" in data["six_dimensions"]
    assert "hint_dependency" in data["six_dimensions"]
    assert "explanation_need" in data["six_dimensions"]
    assert isinstance(data["reason_codes"], list)
    assert isinstance(data["evidence_refs"], list)


def test_get_recommendation_student_view_hides_internal_fields(client, session):
    """学生视图获取推荐运行时不暴露 generation_draft_id 内部字段。"""
    teacher = _user(session, "s5_rec_view_teacher")
    student = _user(session, "s5_rec_view_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=23,
        observed_performance=0.4, evidence_confidence=0.3, sample_size=2,
    )

    # 创建带 generated_draft 的推荐
    create_resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 23, "purpose": "diagnose", "item_count": 1, "allow_generation": True},
        headers=_auth(_token(student)),
    )
    assert create_resp.status_code == 200
    rec_id = create_resp.json()["data"]["recommendation_id"]

    # 学生视图
    resp = client.get(
        f"{PRACTICE}/course/{course.id}/recommendations/{rec_id}",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["items"]) >= 1
    item = data["items"][0]
    # 学生视图不暴露 generation_draft_id
    assert "generation_draft_id" not in item

    # 教师视图可看
    resp_t = client.get(
        f"{PRACTICE}/course/{course.id}/recommendations/{rec_id}",
        headers=_auth(_token(teacher)),
    )
    assert resp_t.status_code == 200
    item_t = resp_t.json()["data"]["items"][0]
    if item_t["question_source"] == "generated_draft":
        assert "generation_draft_id" in item_t


def test_start_recommendation_item_rejects_unapproved_draft(client, session):
    """AI 草稿未审核前不可开始作答，返回 409 STATE_CONFLICT。"""
    teacher = _user(session, "s5_start_reject_teacher")
    student = _user(session, "s5_start_reject_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=24,
        observed_performance=0.4, evidence_confidence=0.3, sample_size=2,
    )

    create_resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 24, "purpose": "diagnose", "item_count": 1, "allow_generation": True},
        headers=_auth(_token(student)),
    )
    assert create_resp.status_code == 200
    data = create_resp.json()["data"]
    rec_id = data["recommendation_id"]

    # 找到 generated_draft 推荐项
    items = session.exec(
        select(QuestionRecommendationItem).where(
            QuestionRecommendationItem.recommendation_id == rec_id,
            QuestionRecommendationItem.question_source == QuestionSource.GENERATED_DRAFT,
        )
    ).all()
    assert len(items) >= 1
    item_id = items[0].item_id

    # 学生开始作答 -> 409
    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations/{rec_id}/items/{item_id}/start",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_code"] == "STATE_CONFLICT"


def test_start_recommendation_item_after_draft_approved(client, session):
    """教师审核通过草稿后，学生可开始作答。"""
    teacher = _user(session, "s5_start_ok_teacher")
    student = _user(session, "s5_start_ok_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=25,
        observed_performance=0.4, evidence_confidence=0.3, sample_size=2,
    )

    create_resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 25, "purpose": "diagnose", "item_count": 1, "allow_generation": True},
        headers=_auth(_token(student)),
    )
    rec_id = create_resp.json()["data"]["recommendation_id"]
    items = session.exec(
        select(QuestionRecommendationItem).where(
            QuestionRecommendationItem.recommendation_id == rec_id,
            QuestionRecommendationItem.question_source == QuestionSource.GENERATED_DRAFT,
        )
    ).all()
    item = items[0]
    # 审核草稿
    draft = session.exec(
        select(QuestionGenerationDraft).where(
            QuestionGenerationDraft.draft_id == item.generation_draft_id,
        )
    ).first()
    question_generation_draft_service.approve_draft(
        session, course_id=course.id, draft_id=draft.draft_id, reviewed_by=teacher.id,
    )
    session.commit()

    # 学生开始作答
    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations/{rec_id}/items/{item.item_id}/start",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["is_started"] is True


def test_list_student_recommendations_isolated_by_user(client, session):
    """学生只能看自己的推荐历史。"""
    teacher = _user(session, "s5_list_rec_teacher")
    student_a = _user(session, "s5_list_rec_student_a", UserRole.STUDENT)
    student_b = _user(session, "s5_list_rec_student_b", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student_a.id)
    _enroll_student(session, course.id, student_b.id)
    _make_cognitive_state(
        session, student_id=student_a.id, course_id=course.id, node_id=26,
    )
    _make_cognitive_state(
        session, student_id=student_b.id, course_id=course.id, node_id=26,
    )

    # 学生 A 创建推荐
    client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 26, "purpose": "diagnose", "item_count": 1, "allow_generation": False},
        headers=_auth(_token(student_a)),
    )

    # 学生 A 看到自己
    resp_a = client.get(
        f"{PRACTICE}/course/{course.id}/recommendations",
        headers=_auth(_token(student_a)),
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["data"]["total"] == 1

    # 学生 B 看不到学生 A 的
    resp_b = client.get(
        f"{PRACTICE}/course/{course.id}/recommendations",
        headers=_auth(_token(student_b)),
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["data"]["total"] == 0


# ---------------------------------------------------------------------------
# 4. 答题提交与正式学习证据
# ---------------------------------------------------------------------------


def test_submit_attempt_writes_formal_evidence_and_link(client, session):
    """客观题答题自动判分后写入正式 LearningEvidence 与 LearningEvidenceLink 上下文。"""
    teacher = _user(session, "s5_submit_teacher")
    student = _user(session, "s5_submit_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    q = QuestionBankItem(
        question_text="2 + 2 = ?",
        answer="4",
        question_type=QuestionType.FILL_BLANK,
        difficulty=QuestionDifficulty.EASY,
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        knowledge_node_ids=[30],
        is_latest=True,
    )
    session.add(q)
    session.commit()
    session.refresh(q)

    attempt = _create_attempt(
        session,
        course_id=course.id,
        student_id=student.id,
        question_id=q.id,
        is_correct=None,
        score=None,
    )

    resp = client.post(
        f"{PRACTICE}/attempts/{attempt.id}/submit",
        json={
            "student_answer": "4",
            "purpose": "diagnose",
        },
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["judgement_status"] == "judged"
    assert data["is_correct"] is True
    assert data["score"] == 1.0
    assert data["writes_formal_evidence"] is True
    assert data["evidence_id"].startswith("ev_")

    # 验证 LearningEvidenceRecord 落库
    evidence_records = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == student.id,
            LearningEvidenceRecord.course_id == course.id,
        )
    ).all()
    assert any(r.evidence_id == data["evidence_id"] for r in evidence_records)

    # 验证 LearningEvidenceLink 链接到 attempt 上下文
    links = session.exec(
        select(LearningEvidenceLink).where(
            LearningEvidenceLink.evidence_id == data["evidence_id"],
            LearningEvidenceLink.context_type == EvidenceLinkContext.QUESTION_ATTEMPT,
        )
    ).all()
    assert len(links) >= 1


def test_submit_attempt_subjective_question_no_auto_judge(client, session):
    """主观题（论述题）不自动判分，不写入正式证据。"""
    teacher = _user(session, "s5_subjective_teacher")
    student = _user(session, "s5_subjective_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    q = QuestionBankItem(
        question_text="论述递归的优缺点。",
        answer="参考答案",
        question_type=QuestionType.ESSAY,
        difficulty=QuestionDifficulty.HARD,
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        knowledge_node_ids=[31],
        is_latest=True,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    attempt = _create_attempt(
        session,
        course_id=course.id,
        student_id=student.id,
        question_id=q.id,
        is_correct=None,
        score=None,
    )

    resp = client.post(
        f"{PRACTICE}/attempts/{attempt.id}/submit",
        json={"student_answer": "递归优点是...", "purpose": "summative"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["judgement_status"] == "pending"
    assert data["is_correct"] is None
    assert data["writes_formal_evidence"] is False


def test_submit_attempt_rejects_cross_student(client, session):
    """学生 B 不能提交学生 A 的答题记录（404）。"""
    teacher = _user(session, "s5_cross_submit_teacher")
    student_a = _user(session, "s5_cross_submit_a", UserRole.STUDENT)
    student_b = _user(session, "s5_cross_submit_b", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student_a.id)
    _enroll_student(session, course.id, student_b.id)
    q = _published_question(
        session, course_id=course.id, node_id=32,
        text="3 + 3 = ?", answer="6",
        question_type=QuestionType.FILL_BLANK,
    )
    attempt = _create_attempt(
        session,
        course_id=course.id,
        student_id=student_a.id,
        question_id=q.id,
        is_correct=None,
        score=None,
    )

    # 学生 B 提交学生 A 的 attempt -> 404
    resp = client.post(
        f"{PRACTICE}/attempts/{attempt.id}/submit",
        json={"student_answer": "6", "purpose": "diagnose"},
        headers=_auth(_token(student_b)),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. 评分策略版本化
# ---------------------------------------------------------------------------


def test_create_assessment_policy(client, session):
    """教师创建评分策略，返回 201。"""
    teacher = _user(session, "s5_policy_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/policies",
        json={
            "purpose": "diagnose",
            "policy_version": "test-policy-v1.0",
            "passing_score": 0.7,
            "confidence_threshold": 0.6,
            "writes_formal_evidence": True,
            "max_attempts_per_node": 5,
            "cooldown_minutes": 15,
            "rules": {"time_limit": 600},
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201
    data = body["data"]
    assert data["purpose"] == "diagnose"
    assert data["passing_score"] == 0.7
    assert data["is_active"] is True


def test_list_policies_filter_by_purpose(client, session):
    """列出评分策略，按 purpose 过滤。"""
    teacher = _user(session, "s5_list_policy_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="list-v1.0",
    )
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.REMEDIATION,
        created_by=teacher.id,
        policy_version="list-v1.0",
    )
    session.commit()

    resp = client.get(
        f"{PRACTICE}/course/{course.id}/policies?purpose=diagnose",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["purpose"] == "diagnose"


def test_policy_idempotent_create_returns_existing(client, session):
    """同 purpose+policy_version 重复创建返回已存在策略，不报错。"""
    teacher = _user(session, "s5_policy_idem_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    body = {
        "purpose": "summative",
        "policy_version": "idem-v1.0",
        "passing_score": 0.6,
    }
    resp1 = client.post(
        f"{PRACTICE}/course/{course.id}/policies",
        json=body,
        headers=_auth(_token(teacher)),
    )
    assert resp1.status_code == 200
    resp2 = client.post(
        f"{PRACTICE}/course/{course.id}/policies",
        json=body,
        headers=_auth(_token(teacher)),
    )
    assert resp2.status_code == 200
    # 同一个 policy_id
    assert resp1.json()["data"]["policy_id"] == resp2.json()["data"]["policy_id"]


# ---------------------------------------------------------------------------
# 6. facade 学习动作完成
# ---------------------------------------------------------------------------


def test_complete_learning_action_non_scored_no_evidence(client, session):
    """非评分动作不写入正式证据（writes_formal_evidence=False）。"""
    teacher = _user(session, "s5_action_nonscored_teacher")
    student = _user(session, "s5_action_nonscored_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/sign",
        json={
            "node_id": 40,
            "action_type": "video_watch",
            "duration_seconds": 300,
            "payload": {"video_id": "vid-1"},
            "is_scored": False,
        },
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # P0-1: 学生端始终不写入正式证据
    assert data["is_scored"] is False
    assert data["writes_formal_evidence"] is False
    assert data["evidence_id"] is None
    assert data["return_anchor"]["action_type"] == "video_watch"
    # action_id 必须是签名格式 la_{hex}.{sig}
    assert data["action_id"].startswith("la_")
    assert "." in data["action_id"]


def test_complete_learning_action_scored_does_not_write_evidence_from_client(client, session):
    """P0-1: 学生端提交 is_scored=True/score 不再写入正式证据。

    旧契约允许学生提交 is_scored=True, score=0.85 直接写入 LearningEvidenceRecord，
    存在伪造高分证据风险。修复后学生端始终返回 writes_formal_evidence=False。
    """
    teacher = _user(session, "s5_action_scored_teacher")
    student = _user(session, "s5_action_scored_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    # 准备评分策略（即使策略允许写正式证据，学生端也不写）
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="action-v1.0",
        writes_formal_evidence=True,
    )
    session.commit()

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/sign",
        json={
            "node_id": 41,
            "action_type": "quiz",
            "duration_seconds": 60,
            "payload": {"quiz_id": "qz-1"},
            "is_scored": True,  # 学生伪造评分
            "score": 0.85,      # 学生伪造高分
        },
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # 即使学生提交 is_scored=True/score=0.85，也不写入正式证据
    assert data["is_scored"] is False
    assert data["score"] is None
    assert data["writes_formal_evidence"] is False
    assert data["evidence_id"] is None
    # 返回签名 action_id 供服务端评分器使用
    assert data["action_id"].startswith("la_")
    assert "." in data["action_id"]

    # 确认数据库中无新增 LearningEvidenceRecord
    evidence_count = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.course_id == course.id,
            LearningEvidenceRecord.student_id == student.id,
        )
    ).all()
    assert len(evidence_count) == 0


def test_complete_learning_action_rejects_non_learner(client, session):
    """非课程学习者（教师）记录学习动作返回 409。"""
    teacher = _user(session, "s5_action_teacher_only")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/sign",
        json={
            "node_id": 42,
            "action_type": "video_watch",
            "is_scored": False,
        },
        headers=_auth(_token(teacher)),
    )
    # 教师 analytics_eligible=False，应被拒绝
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 6b. P0-1 attach-evidence: 服务端评分器写入正式证据
# ---------------------------------------------------------------------------


_INTERNAL_TOKEN = "test-internal-service-token"


def _internal_auth() -> dict[str, str]:
    return {"X-Internal-Service-Token": _INTERNAL_TOKEN}


def _complete_action(client, student, course, *, action_type: str = "quiz") -> str:
    """辅助：学生完成学习动作，返回签名 action_id"""
    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/sign",
        json={"action_type": action_type, "duration_seconds": 60},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["action_id"]


def test_attach_evidence_writes_formal_evidence(client, session):
    """P0-1: 服务端评分器通过 attach-evidence 写入正式证据。"""
    teacher = _user(session, "s5_attach_teacher")
    student = _user(session, "s5_attach_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="attach-v1.0",
        writes_formal_evidence=True,
    )
    session.commit()

    action_id = _complete_action(client, student, course)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "node_id": 50,
            "score": 0.85,
            "evidence_source": "quiz",
            "evidence_type": "learning_action_scored",
            "label": "quiz-scored",
            "description": "Quiz 服务端评分",
        },
        headers=_internal_auth(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["writes_formal_evidence"] is True
    assert data["evidence_id"].startswith("ev_")
    assert data["action_id"] == action_id

    # 验证 LearningEvidenceRecord 落库
    record = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.evidence_id == data["evidence_id"],
        )
    ).first()
    assert record is not None
    assert record.source == "quiz"
    assert record.value == 0.85
    assert action_id in (record.event_refs or [])

    # 验证 LearningEvidenceLink 链接到动作上下文
    links = session.exec(
        select(LearningEvidenceLink).where(
            LearningEvidenceLink.evidence_id == data["evidence_id"],
            LearningEvidenceLink.context_type == EvidenceLinkContext.LEARNING_ACTION,
        )
    ).all()
    assert len(links) >= 1


def test_attach_evidence_rejects_missing_service_token(client, session):
    """P0-1: 缺少 X-Internal-Service-Token 头拒绝写证据。"""
    teacher = _user(session, "s5_attach_no_token_teacher")
    student = _user(session, "s5_attach_no_token_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    action_id = _complete_action(client, student, course)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.9,
            "evidence_source": "quiz",
        },
        # 不带 X-Internal-Service-Token
    )
    assert resp.status_code == 401


def test_attach_evidence_rejects_invalid_service_token(client, session):
    """P0-1: 无效 X-Internal-Service-Token 拒绝写证据。"""
    teacher = _user(session, "s5_attach_bad_token_teacher")
    student = _user(session, "s5_attach_bad_token_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    action_id = _complete_action(client, student, course)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.9,
            "evidence_source": "quiz",
        },
        headers={"X-Internal-Service-Token": "wrong-token"},
    )
    assert resp.status_code == 403


def test_attach_evidence_rejects_forged_action_id(client, session):
    """P0-1: 伪造的 action_id 签名验证失败，拒绝写证据。"""
    teacher = _user(session, "s5_attach_forged_teacher")
    student = _user(session, "s5_attach_forged_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="forged-v1.0",
        writes_formal_evidence=True,
    )
    session.commit()

    # 伪造一个 action_id（格式正确但签名错误）
    forged_action_id = "la_" + uuid.uuid4().hex + ".decafbeefdeadbeef"

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{forged_action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.9,
            "evidence_source": "quiz",
        },
        headers=_internal_auth(),
    )
    assert resp.status_code == 422


def test_attach_evidence_rejects_cross_student_action_id(client, session):
    """P0-1: 学生 A 的 action_id 不能为学生 B 写证据（签名绑定 student_id）。"""
    teacher = _user(session, "s5_attach_cross_teacher")
    student_a = _user(session, "s5_attach_cross_student_a", UserRole.STUDENT)
    student_b = _user(session, "s5_attach_cross_student_b", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student_a.id)
    _enroll_student(session, course.id, student_b.id)
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="cross-v1.0",
        writes_formal_evidence=True,
    )
    session.commit()

    # 学生 A 完成动作
    action_id_a = _complete_action(client, student_a, course)

    # 尝试用学生 A 的 action_id 为学生 B 写证据
    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id_a}/attach-evidence",
        json={
            "student_id": student_b.id,  # 不同学生
            "action_type": "quiz",
            "score": 0.9,
            "evidence_source": "quiz",
        },
        headers=_internal_auth(),
    )
    assert resp.status_code == 422


def test_attach_evidence_rejects_invalid_source(client, session):
    """P0-1: evidence_source 不在白名单内拒绝写证据。"""
    teacher = _user(session, "s5_attach_bad_source_teacher")
    student = _user(session, "s5_attach_bad_source_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="badsrc-v1.0",
        writes_formal_evidence=True,
    )
    session.commit()

    action_id = _complete_action(client, student, course)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.9,
            "evidence_source": "student_self_report",  # 不在白名单
        },
        headers=_internal_auth(),
    )
    assert resp.status_code == 422


def test_attach_evidence_idempotent(client, session):
    """P0-1: 相同 action_id 重复调用 attach-evidence 幂等返回。"""
    teacher = _user(session, "s5_attach_idempotent_teacher")
    student = _user(session, "s5_attach_idempotent_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="idem-v1.0",
        writes_formal_evidence=True,
    )
    session.commit()

    action_id = _complete_action(client, student, course)

    # 第一次写证据
    resp1 = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.85,
            "evidence_source": "quiz",
        },
        headers=_internal_auth(),
    )
    assert resp1.status_code == 200
    evidence_id_1 = resp1.json()["data"]["evidence_id"]

    # 第二次重复调用（幂等）
    resp2 = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.95,  # 不同分数
            "evidence_source": "quiz",
        },
        headers=_internal_auth(),
    )
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    assert data2["idempotent"] is True
    assert data2["evidence_id"] == evidence_id_1


def test_attach_evidence_rejects_policy_not_writing_formal(client, session):
    """P0-1: 评分策略 writes_formal_evidence=False 时拒绝写证据。"""
    teacher = _user(session, "s5_attach_no_formal_teacher")
    student = _user(session, "s5_attach_no_formal_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    # 策略明确不允许写正式证据
    assessment_policy_service.get_or_create_policy(
        session,
        course_id=course.id,
        purpose=AssessmentPurpose.DIAGNOSE,
        created_by=teacher.id,
        policy_version="no-formal-v1.0",
        writes_formal_evidence=False,
    )
    session.commit()

    action_id = _complete_action(client, student, course)

    resp = client.post(
        f"{FACADE}/course/{course.id}/learning-actions/{action_id}/attach-evidence",
        json={
            "student_id": student.id,
            "action_type": "quiz",
            "score": 0.85,
            "evidence_source": "quiz",
        },
        headers=_internal_auth(),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 7. 权限拒绝：未登录、学生越权
# ---------------------------------------------------------------------------


def test_create_import_run_requires_authentication(client, session):
    """未登录创建导入运行返回 401。"""
    teacher = _user(session, "s5_unauth_import_teacher")
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/import-runs",
        json={"source_file": "x.xlsx"},
    )
    assert resp.status_code == 401


def test_student_cannot_create_import_run(client, session):
    """学生不能创建题库导入运行，返回 403。"""
    teacher = _user(session, "s5_student_import_teacher")
    student = _user(session, "s5_student_import_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/import-runs",
        json={"source_file": "x.xlsx"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_student_cannot_approve_draft(client, session):
    """学生不能审核 AI 草稿，返回 403。"""
    teacher = _user(session, "s5_student_approve_teacher")
    student = _user(session, "s5_student_approve_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    draft = question_generation_draft_service.create_draft(
        session, course_id=course.id, node_id=50, question_type="short_answer",
        question_text="题目", answer="答案", generated_by=teacher.id,
    )
    session.commit()

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/drafts/{draft.draft_id}/approve",
        json={},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_student_cannot_list_drafts(client, session):
    """学生不能查看 AI 草稿列表（question_bank.manage），返回 403。"""
    teacher = _user(session, "s5_student_list_drafts_teacher")
    student = _user(session, "s5_student_list_drafts_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    resp = client.get(
        f"{PRACTICE}/course/{course.id}/drafts",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. 跨课程拒绝
# ---------------------------------------------------------------------------


def test_create_recommendation_rejects_cross_course(client, session):
    """学生 A 不能在课程 B 创建推荐（未选课 -> 403）。"""
    teacher_a = _user(session, "s5_cross_rec_teacher_a")
    teacher_b = _user(session, "s5_cross_rec_teacher_b")
    student_a = _user(session, "s5_cross_rec_student_a", UserRole.STUDENT)
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    # 学生 A 仅加入课程 A
    _enroll_student(session, course_a.id, student_a.id)

    # 学生 A 尝试在课程 B 创建推荐 -> 403
    resp = client.post(
        f"{PRACTICE}/course/{course_b.id}/recommendations",
        json={"node_id": 60, "purpose": "diagnose", "item_count": 1, "allow_generation": False},
        headers=_auth(_token(student_a)),
    )
    assert resp.status_code == 403


def test_get_recommendation_rejects_cross_student(client, session):
    """学生 B 不能查看学生 A 的推荐运行（404，不泄露存在性）。"""
    teacher = _user(session, "s5_cross_get_rec_teacher")
    student_a = _user(session, "s5_cross_get_rec_a", UserRole.STUDENT)
    student_b = _user(session, "s5_cross_get_rec_b", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student_a.id)
    _enroll_student(session, course.id, student_b.id)
    _make_cognitive_state(
        session, student_id=student_a.id, course_id=course.id, node_id=61,
    )

    create_resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 61, "purpose": "diagnose", "item_count": 1, "allow_generation": False},
        headers=_auth(_token(student_a)),
    )
    rec_id = create_resp.json()["data"]["recommendation_id"]

    # 学生 B 访问学生 A 的推荐 -> 404
    resp = client.get(
        f"{PRACTICE}/course/{course.id}/recommendations/{rec_id}",
        headers=_auth(_token(student_b)),
    )
    assert resp.status_code == 404


def test_drafts_isolated_across_courses(client, session):
    """课程 A 的草稿不会出现在课程 B 列表中。"""
    teacher_a = _user(session, "s5_drafts_iso_a")
    teacher_b = _user(session, "s5_drafts_iso_b")
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)
    question_generation_draft_service.create_draft(
        session, course_id=course_a.id, node_id=70, question_type="short_answer",
        question_text="课程 A 草稿", answer="A", generated_by=teacher_a.id,
    )
    question_generation_draft_service.create_draft(
        session, course_id=course_b.id, node_id=71, question_type="short_answer",
        question_text="课程 B 草稿", answer="B", generated_by=teacher_b.id,
    )
    session.commit()

    resp_a = client.get(
        f"{PRACTICE}/course/{course_a.id}/drafts",
        headers=_auth(_token(teacher_a)),
    )
    assert resp_a.status_code == 200
    data_a = resp_a.json()["data"]
    assert data_a["total"] == 1
    assert data_a["items"][0]["question_text"] == "课程 A 草稿"

    resp_b = client.get(
        f"{PRACTICE}/course/{course_b.id}/drafts",
        headers=_auth(_token(teacher_b)),
    )
    assert resp_b.status_code == 200
    data_b = resp_b.json()["data"]
    assert data_b["total"] == 1
    assert data_b["items"][0]["question_text"] == "课程 B 草稿"


# ---------------------------------------------------------------------------
# 9. 学习证据链接追溯
# ---------------------------------------------------------------------------


def test_evidence_link_supports_context_traceback(client, session):
    """LearningEvidenceLink 支持按 context 查询证据追溯。"""
    teacher = _user(session, "s5_link_trace_teacher")
    student = _user(session, "s5_link_trace_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    # 写入一条 LearningEvidenceRecord
    evidence_id = "ev_trace_test_" + uuid.uuid4().hex
    record = LearningEvidenceRecord(
        evidence_id=evidence_id,
        student_id=student.id,
        course_id=course.id,
        node_id=80,
        evidence_type="quiz_accuracy",
        value=0.9,
        confidence=0.85,
        label="trace test",
        description="trace test",
        source="cognitive_service",
        timestamp=datetime.utcnow().isoformat(),
        event_refs=[],
        policy_version=COGNITIVE_POLICY_VERSION,
    )
    session.add(record)
    session.flush()

    # 链接到推荐上下文
    rec_id = "rec_trace_" + uuid.uuid4().hex
    learning_evidence_link_service.link(
        session,
        course_id=course.id,
        student_id=student.id,
        evidence_id=evidence_id,
        context_type=EvidenceLinkContext.RECOMMENDATION,
        context_id=rec_id,
        context_snapshot={"purpose": "diagnose", "score": 0.9},
    )
    # 链接到 attempt 上下文
    attempt_id = "attempt_123"
    learning_evidence_link_service.link(
        session,
        course_id=course.id,
        student_id=student.id,
        evidence_id=evidence_id,
        context_type=EvidenceLinkContext.QUESTION_ATTEMPT,
        context_id=attempt_id,
        context_snapshot={"score": 0.9},
    )
    session.commit()

    # 按 evidence_id 查询所有上下文链接
    links = learning_evidence_link_service.list_links_for_evidence(
        session, course_id=course.id, evidence_id=evidence_id,
    )
    assert len(links) == 2
    context_types = {l.context_type for l in links}
    assert EvidenceLinkContext.RECOMMENDATION in context_types
    assert EvidenceLinkContext.QUESTION_ATTEMPT in context_types

    # 按 context 查询证据
    rec_links = learning_evidence_link_service.list_links_for_context(
        session,
        course_id=course.id,
        context_type=EvidenceLinkContext.RECOMMENDATION,
        context_id=rec_id,
    )
    assert len(rec_links) == 1
    assert rec_links[0].evidence_id == evidence_id


# ---------------------------------------------------------------------------
# 10. 数据不足语义：不把交互当掌握度
# ---------------------------------------------------------------------------


def test_recommendation_low_confidence_carries_evidence_needed(client, session):
    """低置信度（< 0.4）的推荐 reason_codes 必须包含 evidence_needed。"""
    teacher = _user(session, "s5_low_conf_teacher")
    student = _user(session, "s5_low_conf_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    # 认知状态置信度 0.2 + 样本量 1 -> 数据不足
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=90,
        observed_performance=0.3, evidence_confidence=0.2, sample_size=1,
    )

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 90, "purpose": "diagnose", "item_count": 1, "allow_generation": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "evidence_needed" in data["reason_codes"]
    assert "insufficient_data" in data["reason_codes"]  # 样本量 < 3
    assert data["confidence"] < 0.4


def test_unpublished_question_not_in_recommendation(client, session):
    """未发布、rejected、stale 题目不能进入推荐池。"""
    teacher = _user(session, "s5_unpub_teacher")
    student = _user(session, "s5_unpub_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=91,
    )
    # 多种状态题目都不应被推荐
    _published_question(
        session, course_id=course.id, node_id=91,
        text="published 题", answer="A", status=QuestionStatus.PUBLISHED,
    )
    QuestionBankItem(
        question_text="auto_accepted 题（不应被推荐）",
        answer="A",
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM,
        course_id=course.id,
        status=QuestionStatus.AUTO_ACCEPTED,
        knowledge_node_ids=[91],
        is_latest=True,
    )
    session.add(QuestionBankItem(
        question_text="rejected 题（不应被推荐）",
        answer="A",
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM,
        course_id=course.id,
        status=QuestionStatus.REJECTED,
        knowledge_node_ids=[91],
        is_latest=True,
    ))
    session.add(QuestionBankItem(
        question_text="stale 题（不应被推荐）",
        answer="A",
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM,
        course_id=course.id,
        status=QuestionStatus.STALE,
        knowledge_node_ids=[91],
        is_latest=True,
    ))
    session.commit()

    # 推荐池只应包含 1 道 published 题
    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 91, "purpose": "diagnose", "item_count": 5, "allow_generation": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # allow_generation=False + 仅 1 道 published -> item_count=1
    assert data["item_count"] == 1


# ---------------------------------------------------------------------------
# 11. G7: Excel 题库导入执行链路（execute_run + Task Worker）
# ---------------------------------------------------------------------------


def _make_excel_bytes(
    rows: list[dict[str, Any]] | None = None,
) -> bytes:
    """生成测试用 Excel 文件字节内容。

    默认构造 3 行有效数据 + 1 行空 question_text（验证行级失败明细）。
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        pytest.skip("openpyxl 未安装")
    import io

    wb = Workbook()
    ws = wb.active
    # 表头（与 import_question_bank.COLUMN_MAP 对齐）
    ws.append(["规则分类", "标准问题", "答案", "规则状态", "匹配模式"])
    if rows is None:
        rows = [
            {"规则分类": "算法", "标准问题": "二分查找时间复杂度？", "答案": "O(log n)",
             "规则状态": "active", "匹配模式": "exact"},
            {"规则分类": "算法", "标准问题": "快速查找最坏复杂度？", "答案": "O(n^2)",
             "规则状态": "active", "匹配模式": "exact"},
            {"规则分类": "数据结构", "标准问题": "栈的特点？", "答案": "后进先出",
             "规则状态": "active", "匹配模式": "exact"},
            # 行级失败：question_text 为空
            {"规则分类": "空题", "标准问题": "", "答案": "无意义",
             "规则状态": "active", "匹配模式": "exact"},
        ]
    for row in rows:
        ws.append([
            row.get("规则分类", ""),
            row.get("标准问题", ""),
            row.get("答案", ""),
            row.get("规则状态", ""),
            row.get("匹配模式", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_execute_import_run_succeeds_with_local_file(client, session, tmp_path):
    """execute_run 从本地文件导入：标记 succeeded，题目 status=UNASSIGNED。"""
    teacher = _user(session, "s7_exec_local_teacher")
    course = _course(session, teacher.id, title="G7 本地导入课程")
    _enable_capabilities(session, course.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "test_bank.xlsx"
    file_path.write_bytes(excel_bytes)

    run = question_import_service.create_run(
        session,
        course_id=course.id,
        source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()

    # 执行导入
    result = question_import_service.execute_run(
        session, run_id=run.run_id, course_id=course.id,
    )
    session.commit()

    assert result.status.value == "partial_success"  # 3 成功 + 1 跳过
    assert result.imported_count == 3
    assert result.skipped_count == 1
    assert result.failed_count == 1
    assert result.error_code == ""
    assert result.started_at is not None
    assert result.finished_at is not None

    # 验证题目已创建且 status=UNASSIGNED（不可被学生检索）
    items = session.exec(
        select(QuestionBankItem).where(
            QuestionBankItem.course_id == course.id,
            QuestionBankItem.import_batch_id.is_not(None),
        )
    ).all()
    assert len(items) == 3
    for item in items:
        assert item.status == QuestionStatus.UNASSIGNED
        assert item.course_id == course.id
        assert item.is_latest is True
        assert item.generated_by == "excel_import"
        assert item.import_batch_id is not None
        # 所有题目共享同一 batch_id
        assert item.import_batch_id == items[0].import_batch_id

    # 行级失败明细应记录空 question_text 行
    assert len(result.failure_details) == 1
    assert result.failure_details[0]["row"] == 5  # Excel 行号


def test_execute_import_run_idempotent_skips_duplicate(client, session, tmp_path):
    """同 course_id + 同文件 SHA256 的重复导入标记 succeeded + skipped=all。"""
    teacher = _user(session, "s7_idem_teacher")
    course = _course(session, teacher.id, title="G7 幂等课程")
    _enable_capabilities(session, course.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "test_bank_idem.xlsx"
    file_path.write_bytes(excel_bytes)

    # 第一次导入
    run1 = question_import_service.create_run(
        session, course_id=course.id, source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()
    question_import_service.execute_run(
        session, run_id=run1.run_id, course_id=course.id,
    )
    session.commit()

    # 第二次导入同文件：应跳过
    run2 = question_import_service.create_run(
        session, course_id=course.id, source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()
    result2 = question_import_service.execute_run(
        session, run_id=run2.run_id, course_id=course.id,
    )
    session.commit()

    assert result2.status.value == "succeeded"
    assert result2.imported_count == 0
    # 幂等短路：检测到同 course_id + batch_id 已存在，整批 4 行全部跳过
    # （包含首次因空 question_text 被跳过的行；语义为"本运行未处理任何行"）
    assert result2.skipped_count == 4
    assert result2.total_rows == 4

    # 总题数仍为 3（不重复入库）
    items = session.exec(
        select(QuestionBankItem).where(QuestionBankItem.course_id == course.id)
    ).all()
    assert len(items) == 3


def test_execute_import_run_failed_when_source_missing(session):
    """源文件不存在时 execute_run 标记 FAILED + SOURCE_FILE_NOT_FOUND。"""
    teacher = _user(session, "s7_missing_teacher")
    course = _course(session, teacher.id, title="G7 缺源课程")
    _enable_capabilities(session, course.id)

    run = question_import_service.create_run(
        session, course_id=course.id,
        source_file="/nonexistent/path/bank.xlsx",
        initiated_by=teacher.id,
    )
    session.commit()

    result = question_import_service.execute_run(
        session, run_id=run.run_id, course_id=course.id,
    )
    session.commit()

    assert result.status.value == "failed"
    assert result.error_code == "SOURCE_FILE_NOT_FOUND"
    assert "不存在" in result.error_message or "未提供" in result.error_message
    assert result.imported_count == 0


def test_execute_import_run_course_isolation(session, tmp_path):
    """导入的题目 course_id 与 run.course_id 严格一致，不跨课程污染。"""
    teacher_a = _user(session, "s7_iso_teacher_a")
    teacher_b = _user(session, "s7_iso_teacher_b")
    course_a = _course(session, teacher_a.id, title="G7 课程 A")
    course_b = _course(session, teacher_b.id, title="G7 课程 B")
    _enable_capabilities(session, course_a.id)
    _enable_capabilities(session, course_b.id)

    excel_bytes = _make_excel_bytes()
    file_a = tmp_path / "bank_a.xlsx"
    file_a.write_bytes(excel_bytes)
    file_b = tmp_path / "bank_b.xlsx"
    file_b.write_bytes(excel_bytes)

    # 两个课程各导入同一文件
    run_a = question_import_service.create_run(
        session, course_id=course_a.id, source_file=str(file_a),
        initiated_by=teacher_a.id,
    )
    run_b = question_import_service.create_run(
        session, course_id=course_b.id, source_file=str(file_b),
        initiated_by=teacher_b.id,
    )
    session.commit()
    question_import_service.execute_run(
        session, run_id=run_a.run_id, course_id=course_a.id,
    )
    question_import_service.execute_run(
        session, run_id=run_b.run_id, course_id=course_b.id,
    )
    session.commit()

    # 各课程 3 道题（同文件可在不同课程各导入一次）
    items_a = session.exec(
        select(QuestionBankItem).where(QuestionBankItem.course_id == course_a.id)
    ).all()
    items_b = session.exec(
        select(QuestionBankItem).where(QuestionBankItem.course_id == course_b.id)
    ).all()
    assert len(items_a) == 3
    assert len(items_b) == 3
    # 题目不跨课程
    assert all(i.course_id == course_a.id for i in items_a)
    assert all(i.course_id == course_b.id for i in items_b)


def test_execute_import_run_rejects_repeated_execution(session, tmp_path):
    """已 succeeded 的 run 不可重复执行（状态机拒绝）。"""
    from fastapi import HTTPException
    teacher = _user(session, "s7_repeat_teacher")
    course = _course(session, teacher.id, title="G7 重复执行课程")
    _enable_capabilities(session, course.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "bank_repeat.xlsx"
    file_path.write_bytes(excel_bytes)

    run = question_import_service.create_run(
        session, course_id=course.id, source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()
    question_import_service.execute_run(
        session, run_id=run.run_id, course_id=course.id,
    )
    session.commit()

    # 重复执行应被拒绝（reject_state_conflict 抛出 HTTPException 409）
    with pytest.raises(HTTPException):
        question_import_service.execute_run(
            session, run_id=run.run_id, course_id=course.id,
        )


def test_import_run_via_object_storage(session, monkeypatch, tmp_path):
    """execute_run 通过 source_object_key 从对象存储读取 Excel。"""
    teacher = _user(session, "s7_obj_teacher")
    course = _course(session, teacher.id, title="G7 对象存储课程")
    _enable_capabilities(session, course.id)

    excel_bytes = _make_excel_bytes()

    # 注入 Fake ObjectStorageProvider
    class _FakeProvider:
        def get(self, object_key: str) -> bytes:
            if object_key == "uploads/g7_bank.xlsx":
                return excel_bytes
            raise FileNotFoundError(object_key)

    from app.services import object_storage as _os_module
    fake_provider = _FakeProvider()
    monkeypatch.setattr(_os_module, "get_object_storage", lambda: fake_provider)

    run = question_import_service.create_run(
        session, course_id=course.id,
        source_file="bank.xlsx",  # 仅用于显示
        source_object_key="uploads/g7_bank.xlsx",
        initiated_by=teacher.id,
    )
    session.commit()

    result = question_import_service.execute_run(
        session, run_id=run.run_id, course_id=course.id,
    )
    session.commit()

    assert result.status.value == "partial_success"
    assert result.imported_count == 3
    assert result.skipped_count == 1


def test_question_bank_import_handler_via_worker(session, tmp_path):
    """Task Worker handler 端到端：创建 run + 提交 worker.run_inline + 验证状态。"""
    from app.platform.tasks.worker import LocalTaskWorker, TaskHandlerContext
    from app.platform.tasks.handlers import question_bank_import_handler
    from app.services.task_service import task_service, TaskCreateRequest
    from app.models.database import session_factory

    teacher = _user(session, "s7_worker_teacher")
    course = _course(session, teacher.id, title="G7 Worker 课程")
    _enable_capabilities(session, course.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "worker_bank.xlsx"
    file_path.write_bytes(excel_bytes)

    # 1. 创建导入运行
    run = question_import_service.create_run(
        session, course_id=course.id, source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()

    # 2. 创建任务记录
    task_request = TaskCreateRequest(
        task_type="question_bank.import",
        owner_user_id=teacher.id,
        course_id=course.id,
        input_summary="G7 Worker 测试",
        input_payload={"course_id": course.id, "run_id": run.run_id},
    )
    task_view = task_service.create_task(session, task_request)
    session.commit()

    # 3. 通过 worker 同步执行
    worker = LocalTaskWorker()
    worker.register("question_bank.import", question_bank_import_handler)
    import asyncio
    asyncio.run(worker.run_inline(
        session_factory, task_view.task_id, task_request.input_payload,
    ))

    # 4. 验证 run 状态
    session.expire_all()
    final_run = session.exec(
        select(QuestionImportRun).where(
            QuestionImportRun.run_id == run.run_id,
            QuestionImportRun.course_id == course.id,
        )
    ).first()
    assert final_run is not None
    assert final_run.status.value == "partial_success"
    assert final_run.imported_count == 3

    # 5. 验证 task 状态
    final_task = task_service.get_task(
        session, task_view.task_id, owner_user_id=teacher.id,
    )
    assert final_task.status == "succeeded"
    assert final_task.result_data["imported_count"] == 3
    assert final_task.result_data["run_id"] == run.run_id


def test_imported_questions_not_visible_to_students_until_published(client, session, tmp_path):
    """导入的 UNASSIGNED 题目不可被学生推荐（需教师升级为 PUBLISHED）。"""
    teacher = _user(session, "s7_invis_teacher")
    student = _user(session, "s7_invis_student", UserRole.STUDENT)
    course = _course(session, teacher.id, title="G7 不可见课程")
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "invisible_bank.xlsx"
    file_path.write_bytes(excel_bytes)

    run = question_import_service.create_run(
        session, course_id=course.id, source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()
    question_import_service.execute_run(
        session, run_id=run.run_id, course_id=course.id,
    )
    session.commit()

    # 学生请求推荐：题库 0 命中（UNASSIGNED 不可见）
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=1,
    )
    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 1, "item_count": 3, "allow_generation": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 无 published 题且 allow_generation=False -> item_count=0
    assert data["item_count"] == 0
    assert data["status"] == "partial_success"


def test_import_run_api_creates_task_and_run(client, session, tmp_path):
    """API 端点创建 run + task 并关联 task_id；run.status=pending。"""
    teacher = _user(session, "s7_api_teacher")
    course = _course(session, teacher.id, title="G7 API 课程")
    _enable_capabilities(session, course.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "api_bank.xlsx"
    file_path.write_bytes(excel_bytes)

    resp = client.post(
        f"{PRACTICE}/course/{course.id}/import-runs",
        json={
            "source_file": str(file_path),
            "source_object_key": "",
            "total_rows": 0,
        },
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 202
    data = body["data"]
    assert data["run_id"].startswith("qir_")
    assert data["status"] == "pending"
    assert data["task_id"] is not None
    assert data["task_id"].startswith("task_") or len(data["task_id"]) > 0


def test_imported_question_can_be_published_then_recommended(client, session, tmp_path):
    """导入的 UNASSIGNED 题目经教师升级为 PUBLISHED 后可被学生推荐。"""
    teacher = _user(session, "s7_pub_teacher")
    student = _user(session, "s7_pub_student", UserRole.STUDENT)
    course = _course(session, teacher.id, title="G7 发布后推荐课程")
    _enable_capabilities(session, course.id)
    _enroll_student(session, course.id, student.id)

    excel_bytes = _make_excel_bytes()
    file_path = tmp_path / "pub_bank.xlsx"
    file_path.write_bytes(excel_bytes)

    run = question_import_service.create_run(
        session, course_id=course.id, source_file=str(file_path),
        initiated_by=teacher.id,
    )
    session.commit()
    question_import_service.execute_run(
        session, run_id=run.run_id, course_id=course.id,
    )
    session.commit()

    # 教师将导入的题目升级为 PUBLISHED
    items = session.exec(
        select(QuestionBankItem).where(
            QuestionBankItem.course_id == course.id,
            QuestionBankItem.status == QuestionStatus.UNASSIGNED,
        )
    ).all()
    assert len(items) == 3
    for item in items:
        item.status = QuestionStatus.PUBLISHED
        item.knowledge_node_ids = [42]  # 绑定知识点
        session.add(item)
    session.commit()

    # 学生请求推荐：应命中 published 题
    _make_cognitive_state(
        session, student_id=student.id, course_id=course.id, node_id=42,
    )
    resp = client.post(
        f"{PRACTICE}/course/{course.id}/recommendations",
        json={"node_id": 42, "item_count": 5, "allow_generation": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["item_count"] == 3  # 3 道 published 题全部命中
