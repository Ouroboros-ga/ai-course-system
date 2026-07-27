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


class CodingDiagnosisPort(Protocol):
    """只读代码诊断；诊断不是正式 LearningEvidence。"""

    async def get_latest_diagnosis(
        self, *, student_id: str, course_id: str, run_id: str | None = None,
    ) -> Mapping[str, Any] | None: ...


class StudentHistoryPort(Protocol):
    """返回有界、去原文的学习历史快照。"""

    async def get_history(
        self, *, student_id: str, course_id: str, concept_id: str | None = None,
    ) -> Mapping[str, Any]: ...


class LearningEventPort(Protocol):
    async def record_learning_event(self, *, event: Mapping[str, Any]) -> None: ...
    async def record_agent_trace(self, *, trace: Mapping[str, Any]) -> None: ...


class ConversationContextPort(Protocol):
    """Read/write bounded structured continuity state, never a transcript."""

    async def load_context(self, *, student_id: str, course_id: str, session_id: str) -> Mapping[str, Any] | None: ...
    async def save_context(self, *, student_id: str, course_id: str, session_id: str, context: Mapping[str, Any]) -> None: ...


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


# 阶段9：工具治理与教师安全阀端口


class ToolGovernancePort(Protocol):
    """工具治理端口：在每个工具节点前查询教师策略，被禁用则跳过。

    - is_tool_enabled(course_id, tool_name) → bool：工具是否启用
    - requires_confirmation(course_id, tool_name) → (bool, threshold)：是否需要教师确认
    - record_invocation(...) → None：记录工具调用审计
    - 端口实现按 course_id 严格隔离；课程 A 的策略不影响课程 B
    """

    async def is_tool_enabled(self, *, course_id: str, tool_name: str) -> bool: ...
    async def requires_confirmation(self, *, course_id: str, tool_name: str) -> Mapping[str, Any]: ...
    async def record_invocation(self, *, course_id: str, student_id: str, trace_id: str, tool_name: str, input_summary: Mapping[str, Any], output_summary: Mapping[str, Any], duration_ms: int | None = None, degraded: bool = False, degraded_reason: str = "", allowed_by_policy: bool = True) -> None: ...


class TeacherSafetyValvePort(Protocol):
    """教师安全阀端口：高风险动作生成提案，等待教师决策。

    - create_proposal(...) → proposal_id：创建提案，状态 pending
    - list_pending_proposals(course_id) → list[Mapping]：教师待办列表
    - decide_proposal(course_id, proposal_id, decision, decided_by, reason) → Mapping：决策状态机
    - 高风险动作（trigger_experiment/web_research/change_topic）默认需要确认
    - 教师锁定项 AI 重跑不可覆盖
    """

    async def create_proposal(self, *, course_id: str, student_id: str, trace_id: str, session_id: str, proposal_type: str, tool_name: str, proposed_action: Mapping[str, Any], requires_confirmation: bool | None = None) -> Mapping[str, Any]: ...
    async def list_pending_proposals(self, *, course_id: str, limit: int = 50) -> list[Mapping[str, Any]]: ...
    async def decide_proposal(self, *, course_id: str, proposal_id: str, decision: str, decided_by: str, decision_reason: str = "") -> Mapping[str, Any]: ...
    async def get_proposal(self, *, course_id: str, proposal_id: str) -> Mapping[str, Any] | None: ...


class ExperimentPort(Protocol):
    """课程实验只读端口：按 course_id 隔离查询实验定义与最近提交。"""

    async def list_experiments(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...
    async def get_latest_attempt(self, *, course_id: str, student_id: str, experiment_id: str) -> Mapping[str, Any] | None: ...


class VisualizationPort(Protocol):
    """算法可视化只读端口：按 course_id 隔离查询已发布可视化计划。"""

    async def list_published_plans(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...
    async def get_plan(self, *, course_id: str, plan_id: str) -> Mapping[str, Any] | None: ...


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
    coding_diagnosis: Optional[CodingDiagnosisPort] = None
    student_history: Optional[StudentHistoryPort] = None
    # 批次4新增可选工具：未注入时 workflow 节点跳过执行，不影响现有流程
    web_research: Optional[WebResearchPort] = None
    cognition: Optional[CognitionPort] = None
    question_bank: Optional[QuestionBankPort] = None
    conversation_context: Optional[ConversationContextPort] = None
    # 阶段9新增可选工具治理与教师安全阀端口；未注入时 workflow 节点跳过治理与提案
    tool_governance: Optional[ToolGovernancePort] = None
    teacher_safety_valve: Optional[TeacherSafetyValvePort] = None
    experiment: Optional[ExperimentPort] = None
    visualization: Optional[VisualizationPort] = None
