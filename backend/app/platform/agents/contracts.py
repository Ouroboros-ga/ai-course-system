"""Ports consumed by LangGraph nodes; no node may access a database directly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol


class ScopePort(Protocol):
    async def validate_scope(self, *, student_id: str, course_id: str, resource_id: str | None) -> Mapping[str, Any]: ...


class KnowledgeGraphPort(Protocol):
    async def resolve_concepts(self, *, course_id: str, message: str, candidates: list[Mapping[str, Any]], resource_id: str | None) -> list[Mapping[str, Any]]: ...
    async def get_context(self, *, course_id: str, concept_id: str) -> Mapping[str, Any]: ...


class CourseRetrievalPort(Protocol):
    async def retrieve_course_evidence(self, *, course_id: str, message: str, concept_id: str | None, resource_id: str | None) -> list[Mapping[str, Any]]: ...


class StudentModelingPort(Protocol):
    async def get_concept_state(self, *, student_id: str, course_id: str, concept_id: str) -> Mapping[str, Any]: ...
    async def get_weak_concepts(self, *, student_id: str, course_id: str) -> list[Mapping[str, Any]]: ...


class RecommendationPort(Protocol):
    async def recommend_next_action(self, *, student_id: str, course_id: str, concept_id: str | None, action: str, graph_context: Mapping[str, Any], student_state: Mapping[str, Any]) -> Mapping[str, Any]: ...


class SandboxPort(Protocol):
    async def get_execution_result(self, *, student_id: str, course_id: str, code_submission_id: str) -> Mapping[str, Any]: ...


class LearningEventPort(Protocol):
    async def record_learning_event(self, *, event: Mapping[str, Any]) -> None: ...
    async def record_agent_trace(self, *, trace: Mapping[str, Any]) -> None: ...


class TeachingLLMPort(Protocol):
    async def detect_intent(self, *, message: str, course_id: str) -> Mapping[str, Any]: ...
    async def extract_concept_candidates(self, *, message: str, course_id: str) -> list[Mapping[str, Any]]: ...
    async def generate_teaching_response(self, *, context: Mapping[str, Any]) -> Mapping[str, Any]: ...


# 批次4：可选工具端口（默认 None，未注入时 workflow 节点跳过执行）


class WebResearchPort(Protocol):
    """补充性网络检索端口。

    返回结果必须始终标记 ``is_supplementary=true``，禁止修改掌握度/推荐/图谱。
    """

    async def research(self, *, course_id: str, query: str, student_id: str | None = None) -> Mapping[str, Any]: ...


class CognitionPort(Protocol):
    """六维认知状态读取端口（只读）。"""

    async def get_state(self, *, student_id: str, course_id: str, node_id: str | None = None) -> Mapping[str, Any] | None: ...
    async def get_recommendation(self, *, student_id: str, course_id: str, node_id: str | None = None) -> Mapping[str, Any] | None: ...


class QuestionBankPort(Protocol):
    """课程题库读取端口（仅 published 题目，按 course_id 隔离）。"""

    async def list_questions(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class TeachingTools:
    scope: ScopePort
    knowledge_graph: KnowledgeGraphPort
    retrieval: CourseRetrievalPort
    student_modeling: StudentModelingPort
    recommendation: RecommendationPort
    sandbox: SandboxPort
    learning_events: LearningEventPort
    llm: TeachingLLMPort
    # 批次4新增可选工具：未注入时 workflow 节点跳过执行，不影响现有流程
    web_research: Optional[WebResearchPort] = None
    cognition: Optional[CognitionPort] = None
    question_bank: Optional[QuestionBankPort] = None
