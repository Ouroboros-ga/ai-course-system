"""G2 六维认知驱动的推荐策略引擎

根据六维认知状态筛选题目，生成可解释的推荐。
每次推荐带 policy_version、reason_codes、evidence_refs。

推荐策略：
  - 低表现+高置信度 -> 补弱练习 (PRACTICE_QUIZ, HIGH)
  - 低表现+低置信度 -> 诊断题，不判定薄弱 (PRACTICE_QUIZ, MEDIUM, reason=diagnostic)
  - 提示依赖高 -> 逐步撤除提示的题目 (PRACTICE_QUIZ, MEDIUM, reason=hint_fade)
  - 困惑/解释需求高 -> 短反馈、分步题 (PRACTICE_QUIZ, MEDIUM, reason=step_by_step)
  - 表现良好 -> 前进 (ADVANCE_NEXT, LOW)
  - 数据不足 -> unknown (CONTINUE, LOW, reason=insufficient_data)

不把提问次数或观看时长直接计入表现分。
数据不足时输出 unknown 或"需要更多证据"。
不跨学生、课程读取或写入状态。
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import (
    CognitiveState,
    RecommendationRecord,
    LearningEvidenceRecord,
    COGNITIVE_POLICY_VERSION,
)
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionStatus,
    QuestionDifficulty,
)
from app.domain.learning.recommendation import (
    Recommendation,
    RecommendationType,
    RecommendationPriority,
    RECOMMENDATION_VERSION,
)
from app.services.cognitive_service import compute_cognitive_state, get_latest_cognitive_state
from app.services.graph_production_service import get_prerequisite_nodes

# 推荐策略阈值
PERFORMANCE_LOW = 0.5
PERFORMANCE_HIGH = 0.7
CONFIDENCE_LOW = 0.4
CONFIDENCE_HIGH = 0.6
CONFUSION_HIGH = 0.5
HINT_HIGH = 0.5
EXPLANATION_HIGH = 0.5
INQUIRY_HIGH = 0.6
# 批次3：已确认薄弱前置集合阈值（置信度需达标才判定薄弱，避免低置信度误判）
PREREQ_WEAK_PERF = 0.5
PREREQ_WEAK_CONFIDENCE = 0.6


def generate_recommendation(
    session: Session,
    student_id: int,
    course_id: int,
    node_id: Optional[int] = None,
    force_recompute: bool = False,
) -> RecommendationRecord:
    """生成六维认知驱动的推荐

    流程：
    1. 获取或计算六维认知状态
    2. 根据六维状态选择推荐策略
    3. 从课程题库筛选匹配的题目
    4. 持久化推荐记录(含policy_version, reason_codes, evidence_refs)

    批次4教师安全阀：若同 student+course+node 已有未消费的锁定推荐，
    直接返回该锁定推荐，不重新生成（即使 force_recompute=True）。
    """
    # 0. 教师安全阀：检查是否存在未消费的锁定推荐（防止覆盖教师锁定项）
    locked_existing = _find_locked_unconsumed(session, student_id, course_id, node_id)
    if locked_existing is not None:
        return locked_existing

    # 1. 获取或计算认知状态
    if force_recompute:
        state = compute_cognitive_state(session, student_id, course_id, node_id)
    else:
        state = get_latest_cognitive_state(session, student_id, course_id, node_id)
        if state is None:
            state = compute_cognitive_state(session, student_id, course_id, node_id)

    # 2. 批次3：检查已确认薄弱前置集合（仅在当前知识点表现不佳时触发）
    #    读取 GraphSnapshot 的 PREREQUISITE_OF 关系，定位前置节点认知状态
    #    低置信度只进入"需要更多证据"，不直接断言薄弱
    prereq_weak = _find_confirmed_weak_prerequisites(session, student_id, course_id, state)

    # 3. 决定推荐策略
    if prereq_weak:
        rec_type, priority, title, description, reason_codes, target_difficulty = _prereq_review_strategy(
            state, prereq_weak
        )
    else:
        rec_type, priority, title, description, reason_codes, target_difficulty = _decide_strategy(state)

    # 4. 从课程题库筛选题目
    question = _select_question(session, course_id, state, target_difficulty)

    # 5. 收集证据引用
    evidence_refs = (state.evidence_refs or []) + [
        ref for prereq in prereq_weak for ref in prereq.get("evidence_refs", [])
    ]

    # 6. 创建推荐记录
    cognitive_snapshot = {
        "observed_performance_score": state.observed_performance_score,
        "evidence_confidence": state.evidence_confidence,
        "confusion_risk": state.confusion_risk,
        "inquiry_depth": state.inquiry_depth,
        "hint_dependency": state.hint_dependency,
        "explanation_need": state.explanation_need,
        "mastery_level": state.mastery_level,
        "sample_size": state.sample_size,
    }

    record = RecommendationRecord(
        recommendation_id=str(uuid.uuid4()),
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        recommendation_type=rec_type.value,
        priority=priority.value,
        title=title,
        description=description,
        policy_version=COGNITIVE_POLICY_VERSION,
        reason_codes=reason_codes,
        evidence_refs=evidence_refs,
        question_id=question.id if question else None,
        knowledge_node_ids=question.knowledge_node_ids if question else [],
        cognitive_snapshot=cognitive_snapshot,
        source="recommendation_service",
        source_version=RECOMMENDATION_VERSION,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    return record


def _find_confirmed_weak_prerequisites(
    session: Session,
    student_id: int,
    course_id: int,
    state: CognitiveState,
) -> list[dict]:
    """批次3：从已发布 GraphSnapshot 读取当前节点的一跳先修节点，
    并检查其认知状态，返回"已确认薄弱"的前置节点集合。

    判定薄弱的硬约束（避免低置信度误判）：
      - 前置节点的 observed_performance_score 不是 None
      - 前置节点的 evidence_confidence 达标（>= PREREQ_WEAK_CONFIDENCE）
      - 前置节点的 observed_performance_score < PREREQ_WEAK_PERF
    低置信度（样本不足）的前置节点不进入此集合，避免武断判弱。
    只读取已发布快照，不暴露草稿；严格按课程隔离。
    """
    if not state.node_id:
        return []
    node_id_str = str(state.node_id)
    prereq_nodes = get_prerequisite_nodes(
        session, course_id, node_id_str, direction="incoming"
    )
    if not prereq_nodes:
        return []
    weak: list[dict] = []
    for node in prereq_nodes:
        prereq_id = str(node.get("id") or node.get("node_id") or "")
        if not prereq_id:
            continue
        try:
            prereq_id_int = int(prereq_id)
        except (TypeError, ValueError):
            # 图谱节点 ID 若不是整数则无法对齐 cognitive_state.node_id，
            # 跳过而非伪造数据。
            continue
        prereq_state = get_latest_cognitive_state(
            session, student_id, course_id, prereq_id_int
        )
        if prereq_state is None:
            continue
        if prereq_state.observed_performance_score is None:
            continue
        if prereq_state.evidence_confidence is None:
            continue
        if prereq_state.evidence_confidence < PREREQ_WEAK_CONFIDENCE:
            continue
        if prereq_state.observed_performance_score >= PREREQ_WEAK_PERF:
            continue
        weak.append({
            "node_id": prereq_id,
            "title": node.get("title") or node.get("label") or prereq_id,
            "performance": prereq_state.observed_performance_score,
            "confidence": prereq_state.evidence_confidence,
            "evidence_refs": prereq_state.evidence_refs or [],
        })
    return weak


def _prereq_review_strategy(
    state: CognitiveState,
    prereq_weak: list[dict],
) -> tuple[
    RecommendationType, RecommendationPriority, str, str, list[str], Optional[QuestionDifficulty]
]:
    """批次3：生成"已确认薄弱前置集合"推荐策略。

    每条推荐携带 policy_version、evidence_refs、reason_codes、置信度。
    reason_codes 包含 confirmed_weak_prerequisite + prerequisite_review，
    以及每个薄弱前置节点的 ID，便于追溯。
    """
    reason_codes = ["confirmed_weak_prerequisite", "prerequisite_review"]
    weak_ids = [p["node_id"] for p in prereq_weak]
    reason_codes.extend(f"weak_prerequisite_node={nid}" for nid in weak_ids)
    titles = ", ".join(p["title"] for p in prereq_weak[:3])
    return (
        RecommendationType.PREREQ_REVIEW,
        RecommendationPriority.HIGH,
        "补学前置知识点",
        f"检测到 {len(prereq_weak)} 个已确认薄弱前置知识点（{titles}）。"
        f"建议先复习这些前置内容再回到当前知识点。置信度达标，非武断判弱。",
        reason_codes,
        QuestionDifficulty.EASY,
    )


def _decide_strategy(state: CognitiveState) -> tuple[
    RecommendationType, RecommendationPriority, str, str, list[str], Optional[QuestionDifficulty]
]:
    """根据六维状态决定推荐策略

    返回: (推荐类型, 优先级, 标题, 描述, 原因码, 目标题目难度)
    """
    perf = state.observed_performance_score
    conf = state.evidence_confidence
    confusion = state.confusion_risk
    inquiry = state.inquiry_depth
    hint = state.hint_dependency
    explanation = state.explanation_need

    reason_codes: list[str] = []

    # 数据不足 -> unknown
    if perf is None and state.sample_size == 0:
        return (
            RecommendationType.CONTINUE,
            RecommendationPriority.LOW,
            "需要更多证据",
            "当前没有足够的答题数据来生成推荐。请完成更多练习后再获取推荐。",
            ["insufficient_data", "no_attempt_records"],
            None,
        )

    if perf is None:
        return (
            RecommendationType.CONTINUE,
            RecommendationPriority.LOW,
            "需要更多证据",
            "答题数据不足以计算表现分，暂无法生成针对性推荐。",
            ["insufficient_performance_data", f"sample_size={state.sample_size}"],
            None,
        )

    # 低表现 + 高置信度 -> 补弱练习
    if perf < PERFORMANCE_LOW and conf is not None and conf >= CONFIDENCE_HIGH:
        reason_codes.append("low_performance_high_confidence")
        reason_codes.append("remedial_practice")
        if confusion and confusion >= CONFUSION_HIGH:
            reason_codes.append("high_confusion_risk")
            return (
                RecommendationType.PRACTICE_QUIZ,
                RecommendationPriority.HIGH,
                "补弱练习：重点突破薄弱知识点",
                f"表现分 {perf:.0%}（置信度 {conf:.0%}），困惑风险 {confusion:.2f}。"
                f"建议针对薄弱知识点进行专项练习。",
                reason_codes,
                QuestionDifficulty.EASY,
            )
        return (
            RecommendationType.PRACTICE_QUIZ,
            RecommendationPriority.HIGH,
            "补弱练习",
            f"表现分 {perf:.0%}（置信度 {conf:.0%}）。建议复习后进行基础练习巩固。",
            reason_codes,
            QuestionDifficulty.EASY,
        )

    # 低表现 + 低置信度 -> 诊断题，不直接判定薄弱
    if perf < PERFORMANCE_LOW and (conf is None or conf < CONFIDENCE_LOW):
        reason_codes.append("low_performance_low_confidence")
        reason_codes.append("diagnostic_not_weakness")
        reason_codes.append("need_more_evidence")
        return (
            RecommendationType.PRACTICE_QUIZ,
            RecommendationPriority.MEDIUM,
            "诊断练习：收集更多证据",
            f"表现分 {perf:.0%}，但置信度不足（样本量 {state.sample_size}）。"
            f"不会直接判定薄弱，建议完成诊断题以收集更多数据。",
            reason_codes,
            QuestionDifficulty.MEDIUM,
        )

    # 提示依赖高 -> 逐步撤除提示
    if hint is not None and hint >= HINT_HIGH:
        reason_codes.append("high_hint_dependency")
        reason_codes.append("hint_fade_strategy")
        return (
            RecommendationType.PRACTICE_QUIZ,
            RecommendationPriority.MEDIUM,
            "逐步撤除提示的练习",
            f"提示依赖度 {hint:.2f}。建议尝试不带提示的练习，逐步建立独立解题能力。",
            reason_codes,
            QuestionDifficulty.MEDIUM,
        )

    # 困惑/解释需求高 -> 短反馈、分步题
    if (confusion is not None and confusion >= CONFUSION_HIGH) or \
       (explanation is not None and explanation >= EXPLANATION_HIGH):
        reason_codes.append("high_confusion_or_explanation_need")
        reason_codes.append("step_by_step_with_feedback")
        dim = "困惑风险" if confusion and confusion >= CONFUSION_HIGH else "解释需求"
        val = confusion if confusion and confusion >= CONFUSION_HIGH else explanation
        return (
            RecommendationType.PRACTICE_QUIZ,
            RecommendationPriority.MEDIUM,
            "分步练习：短反馈+解释后核验",
            f"{dim} {val:.2f}。建议分步完成题目，每步获取短反馈，解释后进行核验。",
            reason_codes,
            QuestionDifficulty.MEDIUM,
        )

    # 表现良好 -> 前进
    if perf >= PERFORMANCE_HIGH:
        reason_codes.append("good_performance")
        reason_codes.append("advance_next")
        if inquiry is not None and inquiry >= INQUIRY_HIGH:
            reason_codes.append("high_inquiry_depth_encouraged")
            return (
                RecommendationType.ADVANCE_NEXT,
                RecommendationPriority.LOW,
                "继续前进：探索更深内容",
                f"表现分 {perf:.0%}，提问深度 {inquiry:.2f}。建议探索更高级的知识点。",
                reason_codes,
                QuestionDifficulty.HARD,
            )
        return (
            RecommendationType.ADVANCE_NEXT,
            RecommendationPriority.LOW,
            "继续前进",
            f"表现分 {perf:.0%}，掌握良好。建议继续学习下一个知识点。",
            reason_codes,
            None,
        )

    # 中等表现 -> 继续练习
    reason_codes.append("medium_performance")
    reason_codes.append("continue_practice")
    return (
        RecommendationType.PRACTICE_QUIZ,
        RecommendationPriority.LOW,
        "继续练习",
        f"表现分 {perf:.0%}。建议继续练习以巩固当前知识点。",
        reason_codes,
        QuestionDifficulty.MEDIUM,
    )


def _select_question(
    session: Session,
    course_id: int,
    state: CognitiveState,
    target_difficulty: Optional[QuestionDifficulty],
) -> Optional[QuestionBankItem]:
    """从课程题库筛选推荐题目

    先查课程题库(published)；无匹配题时返回 None(由上层决定是否生成草稿)。
    不做全库向量检索。
    """
    stmt = select(QuestionBankItem).where(
        QuestionBankItem.course_id == course_id,
        QuestionBankItem.is_latest == True,
        QuestionBankItem.status == QuestionStatus.PUBLISHED,
    )

    if target_difficulty:
        stmt = stmt.where(QuestionBankItem.difficulty == target_difficulty)

    # 如果有知识点信息，优先匹配
    if state.node_id:
        # 尝试匹配包含该知识点的题目
        stmt = stmt.where(
            QuestionBankItem.knowledge_node_ids.contains([state.node_id])
        )

    stmt = stmt.limit(1)
    return session.exec(stmt).first()


def get_recommendation_history(
    session: Session,
    student_id: int,
    course_id: int,
    limit: int = 20,
) -> list[RecommendationRecord]:
    """获取学生推荐历史"""
    stmt = select(RecommendationRecord).where(
        RecommendationRecord.student_id == student_id,
        RecommendationRecord.course_id == course_id,
    ).order_by(RecommendationRecord.created_at.desc()).limit(limit)
    return list(session.exec(stmt).all())


def mark_recommendation_consumed(
    session: Session,
    recommendation_id: str,
    student_id: int,
) -> Optional[RecommendationRecord]:
    """标记推荐为已消费（学生答题/查看后）"""
    record = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == recommendation_id,
            RecommendationRecord.student_id == student_id,
        )
    ).first()
    if record:
        record.consumed = True
        record.consumed_at = utcnow_aware()
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


# ==================== 批次4：教师安全阀 - 锁定推荐项 ====================


def _find_locked_unconsumed(
    session: Session,
    student_id: int,
    course_id: int,
    node_id: Optional[int],
) -> Optional[RecommendationRecord]:
    """查找同 student+course+node 的未消费锁定推荐。

    锁定的推荐不应被 generate_recommendation 覆盖；按 node_id 精确匹配
    （NULL 与 NULL 视为同节点，对应课程级推荐）。
    """
    stmt = select(RecommendationRecord).where(
        RecommendationRecord.student_id == student_id,
        RecommendationRecord.course_id == course_id,
        RecommendationRecord.is_locked == True,  # noqa: E712 - SQLModel 需要 ==
        RecommendationRecord.consumed == False,  # noqa: E712
    )
    if node_id is None:
        stmt = stmt.where(RecommendationRecord.node_id.is_(None))
    else:
        stmt = stmt.where(RecommendationRecord.node_id == node_id)
    return session.exec(stmt).first()


def lock_recommendation(
    session: Session,
    recommendation_id: str,
    teacher_id: int,
) -> Optional[RecommendationRecord]:
    """教师锁定推荐项，防止被 generate_recommendation 覆盖。

    锁定后，generate_recommendation 在同 student+course+node 下若存在
    未消费的锁定推荐，将直接返回该锁定推荐而不重新生成。
    """
    record = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == recommendation_id,
        )
    ).first()
    if record is None:
        return None
    record.is_locked = True
    record.locked_by = teacher_id
    record.locked_at = utcnow_aware()
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def unlock_recommendation(
    session: Session,
    recommendation_id: str,
) -> Optional[RecommendationRecord]:
    """教师解锁推荐项，允许 generate_recommendation 重新生成覆盖。"""
    record = session.exec(
        select(RecommendationRecord).where(
            RecommendationRecord.recommendation_id == recommendation_id,
        )
    ).first()
    if record is None:
        return None
    record.is_locked = False
    record.locked_by = None
    record.locked_at = None
    session.add(record)
    session.commit()
    session.refresh(record)
    return record
