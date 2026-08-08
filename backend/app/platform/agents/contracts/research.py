"""Supplementary knowledge ports used by teaching and research agents.

Both ports are read-only knowledge-acquisition ports. ``WebResearchPort``
results are always supplementary reference and must never modify mastery,
recommendations, or graph edges. ``QuestionBankPort`` reads only ``published``
questions, isolated by ``course_id``.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ResearchScopePort(Protocol):
    """Re-authorize a research run inside the agent boundary."""

    async def authorize(
        self,
        *,
        course_id: str,
        actor_user_id: str,
        permission: str,
    ) -> Mapping[str, Any]: ...


class PaperSearchPort(Protocol):
    """Search scholarly metadata without turning it into course truth.

    Implementations must return normalized paper metadata and stamp every item
    as supplementary.  A metadata hit is not a verified claim, a mastery
    signal, or a knowledge-graph edge.
    """

    async def search(
        self,
        *,
        query: str,
        limit: int = 10,
        cursor: str | None = None,
    ) -> Mapping[str, Any]: ...


class TrendAnalysisPort(Protocol):
    """Build an auditable trend projection from a frozen paper corpus."""

    async def analyze(
        self,
        *,
        course_id: str,
        paper_ids: list[str],
        dimensions: list[str] | None = None,
    ) -> Mapping[str, Any]: ...


class CodeReproductionPort(Protocol):
    """Read or request an isolated reproduction run; never execute in-process."""

    async def reproduce(
        self,
        *,
        course_id: str,
        actor_user_id: str,
        repository_url: str,
        revision: str,
        reproduction_spec: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


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


__all__ = [
    "PaperSearchPort",
    "ResearchScopePort",
    "TrendAnalysisPort",
    "CodeReproductionPort",
    "WebResearchPort",
    "QuestionBankPort",
    "QuestionGenerationPort",
]
