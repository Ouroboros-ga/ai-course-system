"""WebResearch port for the TeachingAgent.

Wraps ``app.services.web_research_service.execute_research`` behind a port
protocol so the LangGraph workflow can call it without touching the database.

Hard contract:
- Results are ALWAYS marked ``is_supplementary=True``.
- The port must NEVER modify mastery, recommendation, or knowledge graph.
- The callable adapter exists so the workflow never imports the service
  directly; the composition root supplies the session-scoped callable.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from ...contracts import WebResearchPort


class CallableWebResearchPort:
    """Adapter that turns an awaitable callable into a ``WebResearchPort``.

    The callable is supplied by the composition root so that session lifecycle,
    user identity, and provider configuration are owned outside the workflow.
    The port always stamps the supplementary markers on the returned mapping
    regardless of what the callable returns, so the workflow cannot leak
    supplementary content into mastery / recommendation / graph writes.
    """

    def __init__(
        self,
        research: Callable[..., Awaitable[Mapping[str, Any]]],
    ) -> None:
        self._research = research

    async def research(
        self,
        *,
        course_id: str,
        query: str,
        student_id: str | None = None,
    ) -> Mapping[str, Any]:
        result = await self._research(
            course_id=course_id, query=query, student_id=student_id,
        )
        if not isinstance(result, Mapping):  # defensive: never trust the callable shape
            return {
                "status": "invalid_result_shape",
                "results": [],
                "is_supplementary": True,
                "cannot_modify_mastery": True,
                "cannot_modify_recommendation": True,
                "cannot_modify_graph": True,
            }
        # Always stamp the supplementary contract markers; the workflow node
        # and downstream services rely on these flags to refuse any write.
        return {
            **dict(result),
            "is_supplementary": True,
            "cannot_modify_mastery": True,
            "cannot_modify_recommendation": True,
            "cannot_modify_graph": True,
        }


def make_session_scoped_web_research_port(
    session_factory: Callable[[], Any],
) -> CallableWebResearchPort:
    """Build a port whose callable opens a fresh Session per call.

    ``session_factory`` must return a context manager that yields a SQLModel
    Session (e.g. ``Session(engine)``). The port never holds a long-lived
    session, so it is safe to reuse across requests.
    """
    from app.services.web_research_service import (
        execute_research,
        serialize_result,
    )

    async def _research(
        *,
        course_id: str,
        query: str,
        student_id: str | None = None,
    ) -> Mapping[str, Any]:
        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return {
                "status": "invalid_course_id",
                "results": [],
                "failure_reason": "course_id must be numeric",
            }
        user_id: int | None
        try:
            user_id = int(student_id) if student_id else None
        except (TypeError, ValueError):
            user_id = None
        with session_factory() as session:
            result = execute_research(
                session, course_id_int, query, user_id=user_id,
            )
            return serialize_result(result)

    return CallableWebResearchPort(_research)
