"""Teaching-action ports: recommendation, learning-event recording, conversation context, LLM.

These ports drive the teaching workflow's action selection and side-effect
recording. ``LearningEventPort`` and ``ConversationContextPort`` are the only
ports in this subpackage that record state (audit/context), per the
``ToolRisk.MEDIUM`` classification in ``tools/catalog.py``.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class RecommendationPort(Protocol):
    async def recommend_next_action(self, *, student_id: str, course_id: str, concept_id: str | None, action: str, graph_context: Mapping[str, Any], student_state: Mapping[str, Any]) -> Mapping[str, Any]: ...


class LearningEventPort(Protocol):
    async def record_learning_event(self, *, event: Mapping[str, Any]) -> None: ...
    async def record_agent_trace(self, *, trace: Mapping[str, Any]) -> None: ...


class ConversationContextPort(Protocol):
    """Read/write bounded structured continuity state (Audit domain), never a transcript.

    Full chat messages are persisted in the separate Conversation Domain
    (``conversation_service``); this port only carries the few scalars the
    agent needs to resume within-session context.
    """

    async def load_context(self, *, student_id: str, course_id: str, session_id: str) -> Mapping[str, Any] | None: ...
    async def save_context(self, *, student_id: str, course_id: str, session_id: str, context: Mapping[str, Any]) -> None: ...


class TeachingLLMPort(Protocol):
    async def detect_intent(self, *, message: str, course_id: str) -> Mapping[str, Any]: ...
    async def extract_concept_candidates(self, *, message: str, course_id: str) -> list[Mapping[str, Any]]: ...
    async def generate_teaching_response(self, *, context: Mapping[str, Any]) -> Mapping[str, Any]: ...


__all__ = [
    "RecommendationPort",
    "LearningEventPort",
    "ConversationContextPort",
    "TeachingLLMPort",
]
