"""Structured state passed through the TeachingAgent LangGraph workflow.

Migrated from ``app.platform.agents.state``; the old module re-exports this
verbatim for backward compatibility.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class TeachingState(TypedDict, total=False):
    trace_id: str
    student_id: str
    course_id: str
    session_id: str
    user_message: str
    current_resource_id: str | None
    current_exercise_id: str | None
    current_code_submission_id: str | None
    intent: str
    intent_confidence: float
    concept_candidates: list[dict[str, Any]]
    current_concept_id: str | None
    concept_grounding_confidence: float
    student_concept_state: dict[str, Any]
    weak_concepts: list[dict[str, Any]]
    graph_context: dict[str, Any]
    prerequisites: list[dict[str, Any]]
    successors: list[dict[str, Any]]
    retrieved_evidence: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    sandbox_result: dict[str, Any] | None
    code_diagnosis: dict[str, Any] | None
    coding_diagnosis: dict[str, Any] | None
    learning_history: dict[str, Any] | None
    teaching_action: str
    teaching_action_reason: str
    selected_resource_ids: list[str]
    final_answer: str | None
    warnings: list[str]
    errors: list[str]
    degraded_services: list[str]
    trace: list[dict[str, Any]]
    status: NotRequired[str]
    # 批次4新增可选工具产出字段（仅在对应端口注入时填充）
    cognitive_state: dict[str, Any] | None
    cognitive_recommendation: dict[str, Any] | None
    question_bank_items: list[dict[str, Any]]
    web_research_results: dict[str, Any] | None
    session_context: dict[str, Any] | None
    # 阶段9新增：工具治理与教师安全阀产出字段
    experiment_items: list[dict[str, Any]]
    visualization_plans: list[dict[str, Any]]
    pending_proposals: list[dict[str, Any]]
    governance_skipped_tools: list[str]
