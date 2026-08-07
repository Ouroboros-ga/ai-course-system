"""G2 六维认知状态计算引擎

从 QuestionAttempt 记录计算六维认知状态，复用已有的：
  - RuleBasedMasteryProvider 的加权计算思路
  - LearningEvidence / EvidenceType 领域模型结构
  - MasteryState / MasteryLevel 领域模型

关键规则：
  - observed_performance_score: 仅从评分型显性证据计算，不含提问次数/观看时长
  - evidence_confidence: 基于样本量（答题数），样本不足时降低
  - confusion_risk: 重复错误模式 + 纠正频率
  - inquiry_depth: 提问深度（独立于表现分）
  - hint_dependency: 提示使用频率
  - explanation_need: 理解度分析 + 困惑指标
  - 数据不足时输出 None (unknown)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import (
    CognitiveState,
    LearningEvidenceRecord,
    QuestionDepthRecord,
    COGNITIVE_POLICY_VERSION,
)
from app.models.question_bank_model import QuestionAttempt, QuestionBankItem
from app.models.progress_model import LearningProgress, NodeProgress
from app.domain.learning.evidence import LearningEvidence, EvidenceType
from app.domain.learning.mastery_state import MasteryState, MasteryLevel, MasterySource
from app.services.knowledge_node_identity_service import resolve_node_id

# 最小样本量阈值：低于此值时输出 unknown
MIN_SAMPLE_FOR_PERFORMANCE = 3
MIN_SAMPLE_FOR_CONFIDENCE = 5
MIN_SAMPLE_FOR_CONFUSION = 3
MIN_SAMPLE_FOR_HINT = 2
PERFORMANCE_WINDOW_SIZE = 5
# 提问深度：LLM 标定记录的最少条数，不足时保持 unknown（不武断判断）
MIN_SAMPLE_FOR_INQUIRY = 2
INQUIRY_WINDOW_SIZE = 10
# 观看时长佐证：该节点累计观看达到阈值时小幅提升证据置信度（不直接进入表现分）
MIN_WATCH_SECONDS_FOR_BOOST = 300  # 5 分钟
WATCH_TIME_CONFIDENCE_BOOST = 0.05
MAX_EVIDENCE_CONFIDENCE = 0.95


def _attempt_ref(attempt: QuestionAttempt) -> str:
    return attempt.source_event_id or f"legacy_question_attempt:{attempt.id}"


def _attempt_score(attempt: QuestionAttempt) -> Optional[float]:
    if attempt.score is not None:
        return max(0.0, min(float(attempt.score), 1.0))
    if attempt.is_correct is not None:
        return float(attempt.is_correct)
    return None


def compute_cognitive_state(
    session: Session,
    student_id: int,
    course_id: int,
    node_id: Optional[int] = None,
) -> CognitiveState:
    """计算学生六维认知状态

    从 QuestionAttempt + 课程隔离的 NodeProgress 读取原始数据，
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
        candidate_questions = session.exec(
            select(QuestionBankItem).where(
                QuestionBankItem.course_id == course_id,
                QuestionBankItem.is_latest == True,
            )
        ).all()
        question_ids = [
            question.id
            for question in candidate_questions
            if node_id in (question.knowledge_node_ids or [])
        ]
        if not question_ids:
            attempt_stmt = attempt_stmt.where(QuestionAttempt.id == -1)
        else:
            attempt_stmt = attempt_stmt.where(
                QuestionAttempt.question_id.in_(question_ids)
            )

    attempts = list(session.exec(attempt_stmt).all())
    judged_attempts = [a for a in attempts if _attempt_score(a) is not None]
    judged_attempts.sort(
        key=lambda item: (item.created_at, item.id or 0),
        reverse=True,
    )
    judged_attempts = judged_attempts[:PERFORMANCE_WINDOW_SIZE]
    total_attempts = len(judged_attempts)
    score_values = [_attempt_score(a) for a in judged_attempts]

    # 2. 计算 observed_performance_score（仅评分型显性证据）
    observed_performance: Optional[float] = None
    if len(judged_attempts) >= MIN_SAMPLE_FOR_PERFORMANCE:
        observed_performance = (
            sum(score for score in score_values if score is not None)
            / len(judged_attempts)
        )
        evidence = _create_evidence(
            student_id, course_id, node_id,
            EvidenceType.QUIZ_ACCURACY,
            value=observed_performance,
            confidence=min(len(judged_attempts) / 10.0, 1.0),
            label=f"评分型表现 {observed_performance:.0%}",
            description=(
                f"基于最近 {len(judged_attempts)} 个独立评分项，"
                f"窗口上限 {PERFORMANCE_WINDOW_SIZE}"
            ),
            event_refs=sorted(_attempt_ref(a) for a in judged_attempts),
        )
        evidence_refs.append(evidence.evidence_id)
        _persist_evidence(session, evidence, question_attempt_id=None)
        reason_codes.append("performance_from_quiz_accuracy")
    elif total_attempts > 0:
        reason_codes.append("insufficient_judged_attempts")
    else:
        reason_codes.append("no_attempt_data")

    # 3. 计算 evidence_confidence（基于样本量 + 观看时长佐证）
    evidence_confidence: Optional[float] = None
    if total_attempts >= MIN_SAMPLE_FOR_CONFIDENCE:
        evidence_confidence = 0.85
        reason_codes.append("confidence_from_sample_size")
    elif total_attempts > 0:
        evidence_confidence = 0.3
        reason_codes.append("low_sample_size")
    # 观看时长佐证：该节点累计观看秒数达标时小幅提升置信度，不直接进入表现分。
    watch_seconds = _node_watch_seconds(session, student_id, course_id, node_id)
    if (
        evidence_confidence is not None
        and watch_seconds is not None
        and watch_seconds >= MIN_WATCH_SECONDS_FOR_BOOST
    ):
        evidence_confidence = min(
            evidence_confidence + WATCH_TIME_CONFIDENCE_BOOST,
            MAX_EVIDENCE_CONFIDENCE,
        )
        reason_codes.append("confidence_boosted_by_watch_time")

    # 4. 计算 confusion_risk（重复错误 + 纠正频率）
    confusion_risk: Optional[float] = None
    wrong_attempts = [
        attempt for attempt in judged_attempts
        if (_attempt_score(attempt) or 0.0) < 0.6
    ]
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
            event_refs=sorted(_attempt_ref(a) for a in wrong_attempts),
        )
        evidence_refs.append(evidence.evidence_id)
        _persist_evidence(session, evidence, question_attempt_id=None)
        reason_codes.append("confusion_from_error_pattern")

    # 5. 计算 inquiry_depth（来自教学 Agent 实时 LLM 标定的提问深度记录）
    #    每次提问由 LLM 标定一条 QuestionDepthRecord；此处取最近窗口的均值。
    #    样本不足时保持 unknown，不武断判断提问深度。
    inquiry_depth: Optional[float] = None
    depth_stmt = select(QuestionDepthRecord).where(
        QuestionDepthRecord.student_id == student_id,
        QuestionDepthRecord.course_id == course_id,
    )
    if node_id:
        depth_stmt = depth_stmt.where(QuestionDepthRecord.node_id == node_id)
    else:
        depth_stmt = depth_stmt.where(QuestionDepthRecord.node_id.is_(None))
    depth_stmt = depth_stmt.order_by(
        QuestionDepthRecord.created_at.desc()
    ).limit(INQUIRY_WINDOW_SIZE)
    depth_records = list(session.exec(depth_stmt).all())
    if len(depth_records) >= MIN_SAMPLE_FOR_INQUIRY:
        inquiry_depth = sum(r.depth_score for r in depth_records) / len(depth_records)
        reason_codes.append("inquiry_depth_from_llm_calibration")
    elif depth_records:
        reason_codes.append("inquiry_insufficient_samples")
    else:
        reason_codes.append("inquiry_no_calibration_records")

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
    node_progress_stmt = (
        select(NodeProgress)
        .join(LearningProgress, NodeProgress.progress_id == LearningProgress.id)
        .where(
            LearningProgress.user_id == student_id,
            LearningProgress.course_id == course_id,
        )
    )
    if node_id:
        node_progress_stmt = node_progress_stmt.where(NodeProgress.node_id == node_id)
    node_progresses = list(session.exec(node_progress_stmt).all())

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
        evidence_refs=sorted(set(evidence_refs)),
        reason_codes=sorted(set(reason_codes)),
        sample_size=total_attempts,
        is_latest=True,
        computed_at=utcnow_aware(),
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


def record_question_depth(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    node_id: Optional[int],
    depth_score: float,
    trace_id: str = "",
    depth_label: str = "",
    source: str = "teaching_agent",
) -> QuestionDepthRecord:
    """写入一条 LLM 标定的提问深度记录（追加型）。

    由教学 Agent 在回答学生问题时随请求实时调用；只保存深度分数与标签，
    不保存原始问题全文（数据最小化）。失败不抛出：深度标定记录缺失不应
    影响学生提问的正常回答。
    """
    record = QuestionDepthRecord(
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        depth_score=max(0.0, min(float(depth_score), 1.0)),
        depth_label=depth_label,
        trace_id=trace_id,
        source=source,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _node_watch_seconds(
    session: Session,
    student_id: int,
    course_id: int,
    node_id: Optional[int],
) -> Optional[int]:
    """读取该节点累计观看时长（秒）。

    从 NodeProgress.time_spent 汇总（前端上报的听课时间）。node_id 为空或
    无记录时返回 None，表示无法确认观看时长（不参与置信度佐证）。
    """
    if node_id is None:
        return None
    stmt = (
        select(NodeProgress)
        .join(LearningProgress, NodeProgress.progress_id == LearningProgress.id)
        .where(
            LearningProgress.user_id == student_id,
            LearningProgress.course_id == course_id,
            NodeProgress.node_id == node_id,
        )
    )
    progresses = list(session.exec(stmt).all())
    if not progresses:
        return None
    return sum(int(np.time_spent or 0) for np in progresses)


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
    stable_refs = sorted(set(event_refs or []))
    stable_key = "|".join([
        COGNITIVE_POLICY_VERSION,
        evidence_type.value,
        str(student_id),
        str(course_id),
        str(node_id or ""),
        ",".join(stable_refs),
    ])
    return LearningEvidence(
        evidence_type=evidence_type,
        student_id=student_id,
        course_id=course_id,
        # evidence_id 必须使用 ev_ 前缀 + UUID hex，与 record_scored_evidence
        # 及其他证据域保持一致（project_memory.md 硬约束）。
        evidence_id="ev_" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex,
        node_id=node_id,
        event_refs=stable_refs,
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
    existing = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.evidence_id == evidence.evidence_id,
            LearningEvidenceRecord.student_id == evidence.student_id,
            LearningEvidenceRecord.course_id == evidence.course_id,
        )
    ).first()
    if existing is not None:
        return existing

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
        timestamp=evidence.timestamp,
        question_attempt_id=question_attempt_id,
        event_refs=evidence.event_refs,
    )
    session.add(record)
    return record


def record_scored_evidence(
    session: Session,
    attempt: QuestionAttempt,
) -> Optional[LearningEvidenceRecord]:
    """Convert a graded QuestionAttempt into a persisted QUIZ_ACCURACY evidence record.

    Only fires when ``attempt.is_correct`` is not ``None`` (auto-judged or
    teacher-graded). Viewing time, access frequency, and question count are
    NEVER treated as mastery here: only scored quiz performance contributes to
    scored evidence. The ``measurement_role`` must be ``scored_performance``;
    interaction-state attempts are rejected to keep the performance axis clean.

    Returns the persisted (or pre-existing) record, or ``None`` when the
    attempt is still ungraded.
    """
    # Guard: only scored, judged attempts produce scored evidence.
    if attempt.is_correct is None:
        return None
    if attempt.measurement_role != "scored_performance":
        return None

    score = attempt.score if attempt.score is not None else float(attempt.is_correct)
    score = max(0.0, min(score, 1.0))

    # Teacher-graded attempts are higher confidence than auto-judged ones.
    is_teacher_graded = attempt.judged_by == "teacher"
    confidence = 1.0 if is_teacher_graded else 0.8

    # Resolve the knowledge node from the question's node list, if any.
    node_id: Optional[int] = None
    question = session.get(QuestionBankItem, attempt.question_id)
    if question is not None and question.knowledge_node_ids:
        raw_node_id = question.knowledge_node_ids[0]
        node_id = resolve_node_id(session, attempt.course_id, raw_node_id)
        # Preserve old, pre-identity Demo records until they are migrated.
        if node_id is None and str(raw_node_id).isdigit():
            node_id = int(raw_node_id)

    event_refs = [attempt.source_event_id] if attempt.source_event_id else []

    # Stable, idempotent evidence_id derived from the source event so that
    # re-grading the same attempt updates rather than duplicates. The ``ev_``
    # prefix keeps the identifier aligned with the rest of the practice
    # evidence domain (e.g. learning actions, recommendation links).
    stable_key = f"question_attempt|{attempt.source_event_id or attempt.id}|quiz_accuracy"
    evidence_id = "ev_" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex

    existing = session.exec(
        select(LearningEvidenceRecord).where(
            LearningEvidenceRecord.evidence_id == evidence_id,
        )
    ).first()
    if existing is not None:
        # 教师改分/重新评判时更新可变字段，确保认知状态计算基于最新评判而非首次值。
        existing.value = score
        existing.confidence = confidence
        existing.label = f"答题正确率 {score:.0%}"
        existing.description = f"来自答题记录 #{attempt.id} (评判方式: {attempt.judged_by})"
        existing.source = f"question_attempt:{attempt.judged_by}"
        existing.timestamp = datetime.now(timezone.utc).isoformat()
        existing.question_attempt_id = attempt.id
        existing.event_refs = event_refs
        session.add(existing)
        return existing

    record = LearningEvidenceRecord(
        evidence_id=evidence_id,
        student_id=attempt.student_id,
        course_id=attempt.course_id,
        node_id=node_id,
        evidence_type=EvidenceType.QUIZ_ACCURACY.value,
        value=score,
        confidence=confidence,
        label=f"答题正确率 {score:.0%}",
        description=f"来自答题记录 #{attempt.id} (评判方式: {attempt.judged_by})",
        source=f"question_attempt:{attempt.judged_by}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        question_attempt_id=attempt.id,
        event_refs=event_refs,
    )
    session.add(record)
    return record
