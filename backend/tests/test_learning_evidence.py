"""B1-4 QuestionAttempt -> scored LearningEvidence 单元测试。

核心契约：
1. 评分型(已评判)答题记录产生 QUIZ_ACCURACY 证据并持久化。
2. 未评判(pending)答题记录不产生任何证据。
3. 证据类型必须是 quiz_accuracy，绝不是 engagement（观看时长/访问次数
   不得作为掌握度证据）。
4. 教师评分产生 confidence=1.0，自动评判产生 confidence=0.8。
5. record_scored_evidence 对同一答题记录幂等。

遵循 test_question_bank.py / test_course_access.py 的 fixture 模式，
使用统一权限解析器，不依赖旧 teacher_id。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionAttempt,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
)
from app.models.user_model import User, UserRole
from app.services.cognitive_service import record_scored_evidence
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)

from app.models.course_model import Course, CourseStatus


# ==================== 辅助函数 ====================

def _user(session, name, role=UserRole.STUDENT):
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
    course = Course(
        fanya_course_id=f"le-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="LE Course",
        title="LE Course",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _token(user):
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _question(
    session,
    *,
    question_text="测试题目",
    answer="测试答案",
    course_id=None,
    status=QuestionStatus.PUBLISHED,
    question_type=QuestionType.SHORT_ANSWER,
    options=None,
    knowledge_node_ids=None,
):
    item = QuestionBankItem(
        question_text=question_text,
        answer=answer,
        options=options or {},
        similar_questions=[],
        question_type=question_type,
        difficulty=QuestionDifficulty.MEDIUM,
        category="测试分类",
        course_id=course_id,
        knowledge_node_ids=knowledge_node_ids or [],
        prerequisite_node_ids=[],
        status=status,
        version=1,
        is_latest=True,
        generated_by="excel_import",
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


QB = "/api/v1/question-bank"


def _evidence_for_attempt(session, attempt_id):
    return session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.question_attempt_id == attempt_id,
        )
    ).first()


def _evidence_for_student(session, student_id, course_id):
    return session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.student_id == student_id,
            LearningEvidenceRecord.course_id == course_id,
        )
    ).all()


# ==================== 测试 ====================

def test_scored_attempt_creates_quiz_accuracy_evidence(client, session):
    """已评判的正确答题记录产生 QUIZ_ACCURACY 证据。

    自动评判的客观题(single_choice)答对后：
    - is_correct=True, score=1.0
    - 生成一条 LearningEvidenceRecord
    - evidence_type == "quiz_accuracy"
    - value == 1.0
    - confidence == 0.8 (自动评判)
    - source 包含 question_attempt
    """
    teacher = _user(session, "le_scored_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_scored_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="1 + 1 = ?",
        answer="B",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.SINGLE_CHOICE,
        options={"A": "1", "B": "2"},
    )

    resp = client.post(
        f"{QB}/course/{course.id}/{question.id}/attempt",
        json={"student_answer": "B"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["score"] == 1.0
    assert data["is_correct"] is True
    attempt_id = data["attempt_id"]

    evidence = _evidence_for_attempt(session, attempt_id)
    assert evidence is not None
    assert evidence.evidence_type == "quiz_accuracy"
    assert evidence.value == 1.0
    assert evidence.confidence == 0.8
    assert "question_attempt" in evidence.source
    assert "auto" in evidence.source
    assert evidence.question_attempt_id == attempt_id
    attempt = session.get(QuestionAttempt, attempt_id)
    assert attempt.source_event_id in evidence.event_refs


def test_ungraded_attempt_creates_no_evidence(client, session):
    """未评判的答题记录不产生任何证据。

    主观题(short_answer)提交后 is_correct=None（待教师评分），
    不应生成任何 LearningEvidenceRecord。
    """
    teacher = _user(session, "le_ungraded_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_ungraded_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="请简述机器学习的定义",
        answer="机器学习是人工智能的一个分支",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.SHORT_ANSWER,
    )

    resp = client.post(
        f"{QB}/course/{course.id}/{question.id}/attempt",
        json={"student_answer": "机器学习是让计算机从数据中学习"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["judgement_status"] == "pending"
    attempt_id = resp.json()["data"]["attempt_id"]

    evidence = _evidence_for_attempt(session, attempt_id)
    assert evidence is None

    all_evidence = _evidence_for_student(session, student.id, course.id)
    assert all_evidence == []


def test_evidence_type_is_quiz_accuracy_not_engagement(client, session):
    """证据类型是 quiz_accuracy，绝不是 engagement。

    观看时长和访问次数不得作为掌握度证据。从 QuestionAttempt 流程
    产生的所有证据必须是 quiz_accuracy 类型。
    """
    teacher = _user(session, "le_type_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_type_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="判断题：Python 是编译型语言",
        answer="false",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.TRUE_FALSE,
    )

    resp = client.post(
        f"{QB}/course/{course.id}/{question.id}/attempt",
        json={"student_answer": "错误"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_correct"] is True

    all_evidence = _evidence_for_student(session, student.id, course.id)
    assert len(all_evidence) >= 1
    for record in all_evidence:
        assert record.evidence_type == "quiz_accuracy"
        assert record.evidence_type != "engagement"


def test_teacher_grading_creates_high_confidence_evidence(client, session):
    """教师评分产生 confidence=1.0 的 QUIZ_ACCURACY 证据。

    主观题先提交(pending，无证据)，教师评分后生成证据，
    confidence=1.0（高于自动评判的 0.8）。
    """
    teacher = _user(session, "le_grade_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_grade_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="请论述深度学习的优势",
        answer="深度学习能自动提取特征",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.SHORT_ANSWER,
    )

    # 学生提交 -> pending, 无证据
    resp = client.post(
        f"{QB}/course/{course.id}/{question.id}/attempt",
        json={"student_answer": "深度学习可以自动学习特征表示"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    attempt_id = resp.json()["data"]["attempt_id"]
    assert _evidence_for_attempt(session, attempt_id) is None

    # 教师评分
    resp = client.post(
        f"{QB}/course/{course.id}/attempt/{attempt_id}/grade",
        json={"score": 0.8, "feedback": "部分正确"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["score"] == 0.8

    evidence = _evidence_for_attempt(session, attempt_id)
    assert evidence is not None
    assert evidence.evidence_type == "quiz_accuracy"
    assert evidence.value == 0.8
    assert evidence.confidence == 1.0
    assert "teacher" in evidence.source


def test_record_scored_evidence_idempotent(session):
    """record_scored_evidence 对同一答题记录幂等。

    对同一已评判 attempt 多次调用不会产生重复证据记录。
    """
    teacher = _user(session, "le_idem_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_idem_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="2 + 2 = ?",
        answer="4",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.FILL_BLANK,
    )

    attempt = QuestionAttempt(
        question_id=question.id,
        course_id=course.id,
        student_id=student.id,
        measurement_role="scored_performance",
        student_answer="4",
        is_correct=True,
        score=1.0,
        judged_by="auto",
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    first = record_scored_evidence(session, attempt)
    session.commit()
    assert first is not None

    second = record_scored_evidence(session, attempt)
    session.commit()
    assert second is not None
    assert second.id == first.id

    count = len(_evidence_for_student(session, student.id, course.id))
    assert count == 1


def test_record_scored_evidence_rejects_ungraded_attempt(session):
    """record_scored_evidence 拒绝未评判的 attempt（返回 None）。"""
    teacher = _user(session, "le_reject_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_reject_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="论述题",
        answer="答案",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.SHORT_ANSWER,
    )

    attempt = QuestionAttempt(
        question_id=question.id,
        course_id=course.id,
        student_id=student.id,
        measurement_role="scored_performance",
        student_answer="学生回答",
        is_correct=None,
        score=None,
        judged_by="teacher",
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    result = record_scored_evidence(session, attempt)
    assert result is None
    assert _evidence_for_student(session, student.id, course.id) == []


def test_record_scored_evidence_rejects_non_scored_role(session):
    """非 scored_performance 角色的 attempt 不产生表现轴证据。

    交互状态(measurement_role != scored_performance)不得写入
    表现轴证据，以保持表现轴只含评分型显性证据。
    """
    teacher = _user(session, "le_role_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_role_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="查看题",
        answer="答案",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.TRUE_FALSE,
    )

    attempt = QuestionAttempt(
        question_id=question.id,
        course_id=course.id,
        student_id=student.id,
        measurement_role="engagement_signal",
        student_answer="true",
        is_correct=True,
        score=1.0,
        judged_by="auto",
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    result = record_scored_evidence(session, attempt)
    assert result is None
    assert _evidence_for_student(session, student.id, course.id) == []


def test_evidence_node_id_from_question_knowledge_nodes(session):
    """证据的 node_id 从题目的 knowledge_node_ids 解析。"""
    teacher = _user(session, "le_node_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "le_node_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    question = _question(
        session,
        question_text="节点题",
        answer="true",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
        question_type=QuestionType.TRUE_FALSE,
        knowledge_node_ids=[42],
    )

    attempt = QuestionAttempt(
        question_id=question.id,
        course_id=course.id,
        student_id=student.id,
        measurement_role="scored_performance",
        student_answer="正确",
        is_correct=True,
        score=1.0,
        judged_by="auto",
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    record = record_scored_evidence(session, attempt)
    session.commit()
    assert record is not None
    assert record.node_id == 42
