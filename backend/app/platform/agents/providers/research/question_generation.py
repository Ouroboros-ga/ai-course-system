"""QuestionGeneration port for the TeachingAgent.

Wraps the LLM question generation + draft creation behind a port protocol so
the LangGraph workflow can generate practice drafts without touching the
database directly.

产物为草稿（question_generation_drafts），须经教师审核 approve 后才升级为正式
QuestionBankItem；本端口不直接发布题目。课程隔离：每次调用携带 course_id。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from ...contracts import QuestionGenerationPort


class CallableQuestionGenerationPort:
    """Adapter that turns an awaitable callable into a ``QuestionGenerationPort``."""

    def __init__(
        self,
        generate_question: Callable[..., Awaitable[Mapping[str, Any]]],
    ) -> None:
        self._generate_question = generate_question

    async def generate_question(
        self,
        *,
        course_id: str,
        node_id: str | None = None,
        student_id: str | None = None,
        purpose: str = "remediation",
        difficulty: str = "medium",
        cognitive_snapshot: Mapping[str, Any] | None = None,
        six_dimensions: Mapping[str, Any] | None = None,
        reason_codes: list | None = None,
    ) -> Mapping[str, Any]:
        return await self._generate_question(
            course_id=course_id,
            node_id=node_id,
            student_id=student_id,
            purpose=purpose,
            difficulty=difficulty,
            cognitive_snapshot=cognitive_snapshot,
            six_dimensions=six_dimensions,
            reason_codes=reason_codes,
        )


def make_session_scoped_question_generation_port(
    session_factory: Callable[[], Any],
) -> CallableQuestionGenerationPort:
    """Build a port whose callable opens a fresh Session per call.

    Reads the student's recent questioning inference signals (structured,
    no raw text) and feeds them to the LLM generator together with the
    cognitive snapshot. Writes a draft (not published); teacher approval is
    required before the question enters the bank.
    """
    from app.services.question_generation_llm import (
        GENERATION_POLICY_VERSION,
        generate_question_sync,
    )
    from app.services.practice_recommendation_service import (
        PRACTICE_POLICY_VERSION,
        question_generation_draft_service,
    )

    async def _generate_question(
        *,
        course_id: str,
        node_id: str | None = None,
        student_id: str | None = None,
        purpose: str = "remediation",
        difficulty: str = "medium",
        cognitive_snapshot: Mapping[str, Any] | None = None,
        six_dimensions: Mapping[str, Any] | None = None,
        reason_codes: list | None = None,
    ) -> Mapping[str, Any]:
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return {"draft_id": None, "status": "skipped", "question_text": None, "reason": "invalid_course_id"}
        node_id_int = _parse_int(node_id)
        student_id_int = _parse_int(student_id)

        with session_factory() as session:
            # 读取学生近期提问反推信号（结构化投影，不含原文）。
            # 失败不阻塞出题：inference 不可用时降级为不带提问信号。
            question_signals = None
            try:
                from app.services.conversation_service import (
                    derive_question_inference_signals,
                )
                inference = derive_question_inference_signals(
                    session,
                    student_id=student_id_int,
                    course_id=course_id_int,
                    concept_id=str(node_id_int) if node_id_int else None,
                    lookback_days=14,
                )
                question_signals = inference.get("signals") or None
            except Exception:
                question_signals = None

            gen = generate_question_sync(
                session,
                course_id=course_id_int,
                node_id=node_id_int,
                purpose=purpose,
                difficulty=difficulty,
                cognitive_snapshot=dict(cognitive_snapshot or {}),
                six_dimensions=dict(six_dimensions or {}),
                reason_codes=list(reason_codes or []),
                question_signals=question_signals,
            )

            # LLM 不可用或上下文不足时返回跳过信号，不写草稿
            if not gen.get("question_text"):
                return {
                    "draft_id": None,
                    "status": "skipped",
                    "question_text": None,
                    "reason": gen.get("source") or "llm_no_output",
                }

            merged_reasons = list(reason_codes or [])
            for rc in gen.get("reason_codes", []):
                if rc not in merged_reasons:
                    merged_reasons.append(rc)
            draft_confidence = float(gen.get("confidence", 0.0) or 0.0)

            draft = question_generation_draft_service.create_draft(
                session,
                course_id=course_id_int,
                node_id=node_id_int,
                question_type="short_answer",
                question_text=gen["question_text"],
                answer=gen["answer"],
                options=gen.get("options") or [],
                difficulty=gen.get("difficulty") or difficulty,
                category=gen.get("category") or "",
                generation_purpose=purpose,
                cognitive_snapshot=dict(cognitive_snapshot or {}),
                six_dimensions=dict(six_dimensions or {}),
                reason_codes=merged_reasons,
                evidence_refs=[],
                confidence=draft_confidence,
                generated_by=student_id_int,
                policy_version=PRACTICE_POLICY_VERSION,
                model_version=GENERATION_POLICY_VERSION,
            )
            session.commit()
            return _serialize_draft(draft)

    return CallableQuestionGenerationPort(_generate_question)


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_draft(draft: Any) -> Mapping[str, Any]:
    # 草稿态：answer 进入 trace 供教师审核，但不直接对学生可见
    return {
        "draft_id": draft.draft_id,
        "course_id": draft.course_id,
        "node_id": draft.node_id,
        "question_text": draft.question_text,
        "answer": draft.answer,
        "difficulty": draft.difficulty.value if draft.difficulty else None,
        "category": draft.category,
        "generation_purpose": draft.generation_purpose,
        "confidence": draft.confidence,
        "status": draft.status.value if draft.status else None,
        "reason_codes": list(draft.reason_codes or []),
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }
