"""Pedagogical recommendation for a conversational coding challenge."""
from __future__ import annotations

import logging

from app.platform.agents.contracts.llm import (
    LLMOptions,
    LLMTraceContext,
    StructuredLLMPort,
)
from app.schemas.coding_challenge import CodingChallengeDecision

logger = logging.getLogger(__name__)

_EXPLICIT_MARKERS = ("练习", "做题", "代码题", "编程题", "写代码", "practice", "exercise")
_CODE_MARKERS = (
    "代码", "编程", "算法", "数据结构", "复杂度", "二分", "排序", "链表",
    "栈", "队列", "树", "图", "递归", "动态规划", "code", "algorithm",
)


class CodingChallengeDecisionPolicy:
    """LLM recommends timing; server-side services retain final authority."""

    def __init__(self, structured_llm: StructuredLLMPort | None = None) -> None:
        self._llm = structured_llm

    def configure(self, structured_llm: StructuredLLMPort | None) -> None:
        self._llm = structured_llm

    @staticmethod
    def is_explicit_request(message: str) -> bool:
        lowered = message.lower()
        return any(marker in lowered for marker in _EXPLICIT_MARKERS)

    async def decide(
        self,
        *,
        message: str,
        concept_id: str | None,
        teaching_action: str | None,
        trace_id: str,
        course_id: int,
    ) -> CodingChallengeDecision:
        explicit = self.is_explicit_request(message)
        lowered = message.lower()
        code_related = any(marker in lowered for marker in _CODE_MARKERS)
        fallback = CodingChallengeDecision(
            code_practice_fit=bool(concept_id and (explicit or code_related)),
            pedagogical_timing="now" if concept_id and (explicit or code_related) else "not_applicable",
            target_concept_id=concept_id,
            difficulty="medium",
            reason_codes=[
                "EXPLICIT_PRACTICE_REQUEST" if explicit else "CODE_CONCEPT_UNDERSTANDING_CHECK"
            ] if concept_id and (explicit or code_related) else ["NOT_CODE_PRACTICE"],
        )
        if self._llm is None or not concept_id:
            return fallback
        try:
            response = await self._llm.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Decide whether a short coding exercise is pedagogically timely. "
                            "Do not assess mastery. Use only the current turn and supplied "
                            "structured teaching context."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"concept_id={concept_id}\n"
                            f"teaching_action={teaching_action or ''}\n"
                            f"explicit_request={explicit}\n"
                            f"current_turn={message}"
                        ),
                    },
                ],
                output_schema=CodingChallengeDecision,
                options=LLMOptions(
                    temperature=0.0,
                    max_tokens=300,
                    timeout_seconds=12,
                    response_format={"type": "json_object"},
                    prompt_version="coding-challenge-decision/v1",
                ),
                trace_context=LLMTraceContext(
                    run_id=trace_id,
                    trace_id=trace_id,
                    agent_type="edu",
                    node="coding_challenge_decision",
                    purpose="coding_challenge_timing",
                    course_id=str(course_id),
                ),
            )
            if isinstance(response.parsed, CodingChallengeDecision):
                return response.parsed
        except Exception as exc:  # noqa: BLE001 - deterministic fallback is the contract
            logger.info(
                "Coding challenge timing model failed closed to deterministic policy: %s",
                type(exc).__name__,
            )
        return fallback


coding_challenge_decision_policy = CodingChallengeDecisionPolicy()


__all__ = ["CodingChallengeDecisionPolicy", "coding_challenge_decision_policy"]
