"""Conversation Domain service: persist, resume and infer from learner questions.

This service owns the **product-experience** conversation transcript
(``ConversationMessage``). It is intentionally separate from the Agent Runtime
Context / Audit layer (``agent_log.py`` + the sanitize white-lists), which
keeps applying data-minimization and never persists raw messages, answers,
prompts or full traces -- see AGENTS.md §5.1.

Boundary rules (AGENTS.md §5.1):
- Agent Runtime Context / Audit data must not persist full raw messages, full
  model output, prompts or full LLM traces.
- The Conversation Domain (this service) may persist full user and
  teaching-agent messages, with its own data policy, retention and deletion.
- Learning analysis must not depend on the full Conversation directly; it
  consumes ``derive_question_inference_signals`` -- a structured, traceable
  projection (counts, depth, weak flags, trace references), never raw text.

Persistence is best-effort and non-blocking: a conversation write failure must
never break the teaching response (mirrors ``record_question_depth``).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.conversation_model import (
    CONVERSATION_DATA_POLICY_VERSION,
    DEFAULT_CONVERSATION_RETENTION_DAYS,
    ConversationMessage,
)

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

# 提问反推：单概念采样上限（避免长尾概念占用过多 token）。
INFERENCE_SAMPLE_LIMIT = 5
# 提问反推：判定为「可能薄弱」的提问深度阈值（低于则记 weak=True）。
INFERENCE_WEAK_DEPTH_THRESHOLD = 0.4
# 提问反推：默认回看窗口。
INFERENCE_DEFAULT_LOOKBACK_DAYS = 14


def _retention_until(now: Optional[Any] = None, days: int = DEFAULT_CONVERSATION_RETENTION_DAYS):
    base = now or utcnow_aware()
    return base + timedelta(days=days)


def persist_conversation_turn(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    session_id: str,
    trace_id: str,
    user_message: str,
    assistant_answer: Optional[str],
    concept_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    citations: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Persist a question/answer turn (user message + assistant answer).

    Writes the learner question first, then the teaching-agent answer. Both
    share ``trace_id`` so a turn can be reconstructed. Failure is logged and
    swallowed: conversation persistence is a product-experience concern and
    must never block the teaching response.
    """
    try:
        now = utcnow_aware()
        retention = _retention_until(now)
        rows = [
            ConversationMessage(
                student_id=student_id, course_id=course_id, session_id=session_id,
                trace_id=trace_id, role=ROLE_USER, content=str(user_message),
                concept_id=str(concept_id) if concept_id is not None else None,
                resource_id=str(resource_id) if resource_id is not None else None,
                citations=[], retention_until=retention, data_policy_version=CONVERSATION_DATA_POLICY_VERSION,
            ),
        ]
        if assistant_answer:
            rows.append(ConversationMessage(
                student_id=student_id, course_id=course_id, session_id=session_id,
                trace_id=trace_id, role=ROLE_ASSISTANT, content=str(assistant_answer),
                concept_id=str(concept_id) if concept_id is not None else None,
                resource_id=str(resource_id) if resource_id is not None else None,
                citations=list(citations or []), retention_until=retention,
                data_policy_version=CONVERSATION_DATA_POLICY_VERSION,
            ))
        for row in rows:
            session.add(row)
        session.commit()
    except Exception as err:  # noqa: BLE001 -- 非阻塞：记录失败不得影响回答主流程
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("persist_conversation_turn failed (non-blocking): %s: %s", type(err).__name__, err)


def list_conversation_messages(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    session_id: Optional[str] = None,
    limit: int = 200,
) -> list[ConversationMessage]:
    """Return a learner's conversation history within a course, oldest first.

    When ``session_id`` is provided, scope to that learning session; otherwise
    return the most recent messages across sessions for the learner+course.
    Expired rows (past ``retention_until``) are excluded.
    """
    now = utcnow_aware()
    stmt = select(ConversationMessage).where(
        ConversationMessage.student_id == student_id,
        ConversationMessage.course_id == course_id,
    )
    if session_id:
        stmt = stmt.where(ConversationMessage.session_id == str(session_id))
    stmt = stmt.where(
        (ConversationMessage.retention_until.is_(None)) | (ConversationMessage.retention_until >= now)
    )
    stmt = stmt.order_by(ConversationMessage.created_at.asc()).limit(max(1, min(int(limit), 500)))
    return list(session.exec(stmt).all())


def prune_expired_conversations(session: Session) -> int:
    """Delete conversation rows past their retention window. Returns deleted count."""
    now = utcnow_aware()
    stmt = select(ConversationMessage).where(
        ConversationMessage.retention_until.is_not(None),
        ConversationMessage.retention_until < now,
    )
    expired = list(session.exec(stmt).all())
    for row in expired:
        session.delete(row)
    if expired:
        session.commit()
    return len(expired)


def derive_question_inference_signals(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    concept_id: Optional[str] = None,
    lookback_days: int = INFERENCE_DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """提问反推：聚合近期学生提问为结构化学习证据信号。

    读取 Conversation Domain 中该学生+课程近 ``lookback_days`` 天的 user 提问，
    按 concept_id 聚合并关联 ``question_depth_records`` 的提问深度，产出
    **结构化信号**（计数、平均深度、薄弱标记、trace 引用），供学习分析消费。

    严格遵循 AGENTS.md §5.1：学习分析不得直接依赖完整 Conversation，只能消费
    此结构化投影。本函数不返回原始问题全文，只返回可追溯的 trace_id 列表。
    """
    from app.models.cognitive_state_model import QuestionDepthRecord

    now = utcnow_aware()
    since = now - timedelta(days=max(1, int(lookback_days)))

    stmt = select(ConversationMessage).where(
        ConversationMessage.student_id == student_id,
        ConversationMessage.course_id == course_id,
        ConversationMessage.role == ROLE_USER,
        ConversationMessage.created_at >= since,
    )
    if concept_id is not None:
        stmt = stmt.where(ConversationMessage.concept_id == str(concept_id))
    messages = list(session.exec(stmt).all())

    if not messages:
        return {
            "student_id": student_id,
            "course_id": course_id,
            "concept_id": concept_id,
            "lookback_days": lookback_days,
            "signals": [],
            "total_questions": 0,
        }

    # 按概念分组（concept_id 为空归入 "course_level"）。
    groups: dict[str, list[ConversationMessage]] = {}
    for msg in messages:
        key = msg.concept_id or "course_level"
        groups.setdefault(key, []).append(msg)

    trace_ids = [msg.trace_id for msg in messages if msg.trace_id]
    depth_by_trace: dict[str, float] = {}
    depth_label_by_trace: dict[str, str] = {}
    if trace_ids:
        depth_stmt = select(QuestionDepthRecord).where(
            QuestionDepthRecord.student_id == student_id,
            QuestionDepthRecord.course_id == course_id,
            QuestionDepthRecord.trace_id.in_(trace_ids),
        )
        for rec in session.exec(depth_stmt).all():
            depth_by_trace[rec.trace_id] = float(rec.depth_score)
            depth_label_by_trace[rec.trace_id] = rec.depth_label or ""

    signals: list[dict[str, Any]] = []
    for concept_key, group in groups.items():
        group_trace_ids = [m.trace_id for m in group if m.trace_id]
        depths = [depth_by_trace[t] for t in group_trace_ids if t in depth_by_trace]
        avg_depth = round(sum(depths) / len(depths), 3) if depths else None
        label_counts = Counter(depth_label_by_trace.get(t, "") for t in group_trace_ids)
        label_counts.pop("", None)
        mode_label = label_counts.most_common(1)[0][0] if label_counts else None
        inferred_weak = bool(avg_depth is not None and avg_depth < INFERENCE_WEAK_DEPTH_THRESHOLD)
        first_seen = min(m.created_at for m in group)
        last_seen = max(m.created_at for m in group)
        signals.append({
            "concept_id": None if concept_key == "course_level" else concept_key,
            "question_count": len(group),
            "avg_inquiry_depth": avg_depth,
            "depth_label_mode": mode_label,
            "inferred_weak": inferred_weak,
            "first_seen": first_seen.isoformat() if first_seen else None,
            "last_seen": last_seen.isoformat() if last_seen else None,
            # 可追溯引用：学习分析据此回溯到审计 trace，而非直接读原文。
            "trace_ids": group_trace_ids[:INFERENCE_SAMPLE_LIMIT],
        })

    signals.sort(key=lambda s: (s["question_count"], s["last_seen"] or ""), reverse=True)
    return {
        "student_id": student_id,
        "course_id": course_id,
        "concept_id": concept_id,
        "lookback_days": lookback_days,
        "total_questions": len(messages),
        "signals": signals,
    }
