"""Recommendation port for the TeachingAgent.

接通真实的 ``app.services.recommendation_service.generate_recommendation``，
使 TeachingAgent workflow 能基于学生认知状态生成真实教学行动推荐。

与 ``cognition`` port 的区别：
- ``cognition`` port 只读最新 CognitiveState 和 RecommendationRecord（不触发副作用）；
- ``recommendation`` port 调用 ``generate_recommendation``，会生成并持久化新的
  RecommendationRecord（这是 RecommendationPort 的职责——产出下一步教学行动）。

课程作用域：``generate_recommendation`` 内部强制按 student_id + course_id 隔离，
题库选择与先修查询均限定在 course_id 内。本 port 仅做 str→int 转换与异常兜底。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping

from ...contracts import RecommendationPort


class CallableRecommendationPort:
    """Adapter that turns an awaitable callable into a ``RecommendationPort``."""

    def __init__(self, recommend: Callable[..., Any]) -> None:
        self._recommend = recommend

    async def recommend_next_action(self, **kwargs: Any) -> Mapping[str, Any]:
        return await self._recommend(**kwargs)


def make_session_scoped_recommendation_port(
    session_factory: Callable[[], Any],
) -> CallableRecommendationPort:
    """Build a port that calls the real ``generate_recommendation`` service.

    每次调用打开一个新 Session（与 cognition/question_bank port 一致）。
    ``generate_recommendation`` 是同步函数且涉及认知状态计算，用
    ``asyncio.to_thread`` 包装避免阻塞事件循环。
    """

    async def _recommend(
        *,
        student_id: str,
        course_id: str,
        concept_id: str | None = None,
        action: str = "",
        graph_context: Mapping[str, Any] | None = None,
        student_state: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        try:
            student_id_int = int(student_id)
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return {"resource_ids": [], "reason": "invalid_student_or_course_id"}

        node_id_int = _parse_node_id(concept_id)

        def _generate() -> Mapping[str, Any]:
            from app.services.recommendation_service import generate_recommendation
            with session_factory() as session:
                try:
                    record = generate_recommendation(
                        session,
                        student_id_int,
                        course_id_int,
                        node_id=node_id_int,
                        force_recompute=False,
                    )
                    return _serialize_recommendation(record)
                except Exception:  # noqa: BLE001 -- port 不应让推荐失败阻塞主流程
                    return {
                        "resource_ids": [],
                        "reason": "recommendation_generation_failed",
                    }

        return await asyncio.to_thread(_generate)

    return CallableRecommendationPort(_recommend)


def _parse_node_id(node_id: str | None) -> int | None:
    if node_id is None or node_id == "":
        return None
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return None


def _serialize_recommendation(record: Any) -> Mapping[str, Any]:
    return {
        "recommendation_id": record.recommendation_id,
        "recommendation_type": record.recommendation_type,
        "priority": record.priority,
        "title": record.title,
        "description": record.description,
        "policy_version": record.policy_version,
        "reason_codes": list(record.reason_codes or []),
        "evidence_refs": list(record.evidence_refs or []),
        "question_id": record.question_id,
        "knowledge_node_ids": list(record.knowledge_node_ids or []),
        "consumed": record.consumed,
        "is_locked": record.is_locked,
        "resource_ids": list(record.knowledge_node_ids or []),
    }
