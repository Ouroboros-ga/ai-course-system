"""G2 六维认知状态计算引擎

从 QuestionAttempt 记录计算六维认知状态，复用已有的：
  - RuleBasedMasteryProvider 的加权计算思路
  - LearningEvidence / EvidenceType 领域模型结构
  - MasteryState / MasteryLevel 领域模型

关键规则：
  - observed_performance_score: 仅从答题正确率计算，不含提问次数/观看时长
  - evidence_confidence: 基于样本量（答题数），样本不足时降低
  - confusion_risk: 重复错误模式 + 纠正频率
  - inquiry_depth: 提问深度（独立于表现分）
  - hint_dependency: 提示使用频率
  - explanation_need: 理解度分析 + 困惑指标
  - 数据不足时输出 None (unknown)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.cognitive_state_model import (
    CognitiveState,
    LearningEvidenceRecord,
    COGNITIVE_POLICY_VERSION,
)
from app.models.question_bank_model import QuestionAttempt, QuestionBankItem
from app.models.progress_model import NodeProgress, UnderstandingAnalysis
from app.domain.learning.evidence import LearningEvidence, EvidenceType
from app.domain.learning.mastery_state import MasteryState, MasteryLevel, MasterySource

# 最小样本量阈值：低于此值时输出 unknown
MIN_SAMPLE_FOR_PERFORMANCE = 3
MIN_SAMPLE_FOR_CONFIDENCE = 5
MIN_SAMPLE_FOR_CONFUSION = 3
MIN_SAMPLE_FOR_HINT = 2


def compute_cognitive_state(
    session: Session,
    student_id: int,
    course_id: int,
    node_id: Optional[int] = None,
) -> CognitiveState:
    """计算学生六维认知状态

    从 QuestionAttempt + NodeProgress + UnderstandingAnalysis 读取原始数据，
    计算六维状态值。数据不足时对应维度为 None (unknown)。

    不跨学生、课程读取或写入状态。
    """
    # 标记旧记录为非最新
    old_states = session.exec(
        select(CognitiveState).where(
            CognitiveState.student_id == student_id,
            CognitiveState.course_id == course_id,
            CognitiveState.node_id == (node_id if node_id else None),
            CognitiveState.is_latest == True,
        )
    ).all()
    for old in old_states:
        old.is_latest = False
        session.add(old)

    # 收集证据
    evidence_refs: list[str] = []
    reason_codes: list[str] = []

    # 1. 获取答题记录
    attempt_stmt = select(QuestionAttempt).where(
        QuestionAttempt.student_id == student_id,
        QuestionAttempt.course_id == course_id,
    )
    if node_id:
        # 通过 question -> question_bank_items 关联节点（如果有知识点关联）
        attempt_stmt = attempt_stmt  # 当前按课程级聚合

    attempts = session.exec(attempt_stmt).all()
    total_attempts = len(attempts)
    judged_attempts = [a for a in attempts if a.is_correct is not None]
    correct_count = sum(1 for a in judged_attempts if a.is_correct)

    # 2. 计算 observed_performance_score（仅答题正确率）
    observed_performance: Optional[float] = None
    if len(judged_attempts) >= MIN_SAMPLE_FOR_PERFORMANCE:
        observed_performance = correct_count / len(judged_attempts) if judged_attempts else None
        evidence = _create_evidence(
            student_id, course_id, node_id,
            EvidenceType.QUIZ_ACCURACY,
            value=observed_performance,
            confidence=min(len(judged_attempts) / 10.0, 1.0),
            label=f"答题正确率 {observed_performance:.0%}",
            description=f"基于 {len(judged_attempts)} 次评判记录",
            event_refs=[str(a.id) for a in judged_attempts],
        )
        evidence_refs.append(evidence.evidence_id)
        _persist_evidence(session, evidence, question_attempt_id=None)
        reason_codes.append("performance_from_quiz_accuracy")
    elif total_attempts > 0:
        reason_codes.append("insufficient_judged_attempts")
    else:
        reason_codes.append("no_attempt_data")

    # 3. 计算 evidence_confidence（基于样本量）
    evidence_confidence: Optional[float] = None
    if total_attempts >= MIN_SAMPLE_FOR_CONFIDENCE:
        # 置信度随样本量递增，上限0.95
        evidence_confidence = min(0.5 + (total_attempts - MIN_SAMPLE_FOR_CONFIDENCE) * 0.05, 0.95)
        reason_codes.append("confidence_from_sample_size")
    elif total_attempts > 0:
        evidence_confidence = 0.3  # 低置信度
        reason_codes.append("low_sample_size")
    # else: None = unknown

    # 4. 计算 confusion_risk（重复错误 + 纠正频率）
    confusion_risk: Optional[float] = None
    wrong_attempts = [a for a in judged_attempts if a.is_correct is False]
    if len(judged_attempts) >= MIN_SAMPLE_FOR_CONFUSION and wrong_attempts:
        wrong_rate = len(wrong_attempts) / len(judged_attempts)
        # 检查重复错误模式（同一题目多次错误）
        question_errors: dict[int, int] = {}
        for a in wrong_attempts:
            question_errors[a.question_id] = question_errors.get(a.question_id, 0) + 1
        repeated_errors = sum(1 for count in question_errors.values() if count > 1)
        repeat_factor = min(repeated_errors / max(len(question_errors), 1), 1.0)
        confusion_risk = min(wrong_rate * 0.7 + repeat_factor * 0.3, 1.0)

        evidence = _create_evidence(
            student_id, course_id, node_id,
            EvidenceType.QUIZ_PATTERN,
            value=confusion_risk,
            confidence=min(len(wrong_attempts) / 5.0, 1.0),
            label=f"困惑风险 {confusion_risk:.2f}",
            description=f"错误率{wrong_rate:.0%}, 重复错误{repeated_errors}题",
            event_refs=[str(a.id) for a in wrong_attempts],
        )
        evidence_refs.append(evidence.evidence_id)
        _persist_evidence(session, evidence, question_attempt_id=None)
        reason_codes.append("confusion_from_error_pattern")

    # 5. 计算 inquiry_depth（提问深度，不计入表现分）
    # 从 UnderstandingAnalysis 读取提问记录
    inquiry_depth: Optional[float] = None
    analyses = session.exec(
        select(UnderstandingAnalysis).where(
            UnderstandingAnalysis.student_id == student_id,  # 如果有此字段
        )
    ).all() if hasattr(UnderstandingAnalysis, 'student_id') else []

    # 从 QA 消息读取提问数
    from app.models.qa_model import QAMessage, QASession
    qa_sessions = session.exec(
        select(QASession).where(
            QASession.user_id == student_id,
            QASession.course_id == course_id,
        )
    ).all()
    total_questions = 0
    for qs in qa_sessions:
        msgs = session.exec(
            select(QAMessage).where(
                QAMessage.session_id == qs.id,
                QAMessage.role == "user",
            )
        ).all()
        total_questions += len(msgs)

    if total_questions > 0:
        # 提问深度：基于提问数量，但不计入表现分
        inquiry_depth = min(total_questions / 20.0, 1.0)  # 20个问题满分
        reason_codes.append("inquiry_depth_from_qa_count")
        reason_codes.append("inquiry_not_in_performance")  # 明确不计入表现分

    # 6. 计算 hint_dependency（提示依赖度）
    # 从 cognitive_context 中读取 hint 使用情况
    hint_attempts = [a for a in attempts if a.cognitive_context.get("hint_used")]
    if len(attempts) >= MIN_SAMPLE_FOR_HINT and hint_attempts:
        hint_dependency = len(hint_attempts) / len(attempts)
        reason_codes.append("hint_dependency_from_attempt_context")
    else:
        hint_dependency = None  # 数据不足

    # 7. 计算 explanation_need（解释需求度）
    explanation_need: Optional[float] = None
    # 从理解度分析中读取
    low_understanding_count = 0
    total_analyses = 0
    # 尝试从 NodeProgress 读取理解度
    node_progresses = session.exec(
        select(NodeProgress).where(
            NodeProgress.user_id == student_id,  # 如果有此字段
        )
    ).all() if hasattr(NodeProgress, 'user_id') else []

    if node_progresses:
        total_analyses = len(node_progresses)
        low_understanding_count = sum(
            1 for np in node_progresses
            if np.understanding_score is not None and np.understanding_score < 0.5
        )
        if total_analyses >= MIN_SAMPLE_FOR_CONFUSION:
            explanation_need = low_understanding_count / total_analyses
            reason_codes.append("explanation_need_from_understanding")

    # 8. 计算 mastery_level（复用 RuleBasedMasteryProvider 思路）
    mastery_score = observed_performance if observed_performance is not None else None
    mastery_level = "unknown"
    if mastery_score is not None:
        if mastery_score >= 0.8:
            mastery_level = "advanced"
        elif mastery_score >= 0.6:
            mastery_level = "proficient"
        elif mastery_score >= 0.4:
            mastery_level = "developing"
        else:
            mastery_level = "beginner"

    # 9. 创建并持久化认知状态
    state = CognitiveState(
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        observed_performance_score=observed_performance,
        evidence_confidence=evidence_confidence,
        confusion_risk=confusion_risk,
        inquiry_depth=inquiry_depth,
        hint_dependency=hint_dependency,
        explanation_need=explanation_need,
        mastery_level=mastery_level,
        mastery_score=mastery_score,
        policy_version=COGNITIVE_POLICY_VERSION,
        evidence_refs=evidence_refs,
        reason_codes=reason_codes,
        sample_size=total_attempts,
        is_latest=True,
        computed_at=datetime.utcnow(),
    )
    session.add(state)
    session.commit()
    session.refresh(state)

    return state


def get_latest_cognitive_state(
    session: Session,
    student_id: int,
    course_id: int,
    node_id: Optional[int] = None,
) -> Optional[CognitiveState]:
    """获取学生最新的六维认知状态"""
    stmt = select(CognitiveState).where(
        CognitiveState.student_id == student_id,
        CognitiveState.course_id == course_id,
        CognitiveState.is_latest == True,
    )
    if node_id:
        stmt = stmt.where(CognitiveState.node_id == node_id)
    else:
        stmt = stmt.where(CognitiveState.node_id.is_(None))
    return session.exec(stmt).first()


def _create_evidence(
    student_id: int,
    course_id: int,
    node_id: Optional[int],
    evidence_type: EvidenceType,
    value: Optional[float] = None,
    confidence: float = 0.0,
    label: str = "",
    description: str = "",
    event_refs: list[str] = None,
) -> LearningEvidence:
    """创建内存 LearningEvidence 对象（复用领域模型）"""
    return LearningEvidence(
        evidence_type=evidence_type,
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        event_refs=event_refs or [],
        confidence=confidence,
        value=value,
        label=label,
        description=description,
        source="cognitive_service",
    )


def _persist_evidence(
    session: Session,
    evidence: LearningEvidence,
    question_attempt_id: Optional[int] = None,
) -> LearningEvidenceRecord:
    """将内存 LearningEvidence 持久化到数据库"""
    record = LearningEvidenceRecord(
        evidence_id=evidence.evidence_id,
        student_id=evidence.student_id,
        course_id=evidence.course_id,
        node_id=evidence.node_id,
        evidence_type=evidence.evidence_type.value,
        value=evidence.value,
        confidence=evidence.confidence,
        label=evidence.label,
        description=evidence.description,
        source=evidence.source,
        question_attempt_id=question_attempt_id,
        event_refs=evidence.event_refs,
    )
    session.add(record)
    return record
