"""Supplementary knowledge ports: web research and course question bank.

Both ports are read-only knowledge-acquisition ports. ``WebResearchPort``
results are always supplementary reference and must never modify mastery,
recommendations, or graph edges. ``QuestionBankPort`` reads only ``published``
questions, isolated by ``course_id``.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class WebResearchPort(Protocol):
    """补充性网络检索端口。

    返回结果必须始终标记 ``is_supplementary=true``，禁止修改掌握度/推荐/图谱。
    """

    async def research(self, *, course_id: str, query: str, student_id: str | None = None) -> Mapping[str, Any]: ...


class QuestionBankPort(Protocol):
    """课程题库读取端口（仅 published 题目，按 course_id 隔离）。"""

    async def list_questions(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...


class QuestionGenerationPort(Protocol):
    """题目生成端口：依据知识点/认知/提问信号调用 LLM 生成题目草稿。

    产物为草稿（question_generation_drafts），须经教师审核 approve 后才升级为
    正式 QuestionBankItem；本端口不直接发布题目。
    """

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
    ) -> Mapping[str, Any]: ...


__all__ = ["WebResearchPort", "QuestionBankPort", "QuestionGenerationPort"]
