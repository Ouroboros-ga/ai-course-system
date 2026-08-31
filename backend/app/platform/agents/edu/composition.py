"""Explicit composition roots for TeachingAgent; no import-time service activation.

Migrated from ``app.platform.agents.composition``; the old module re-exports
these functions verbatim for backward compatibility.
"""

from __future__ import annotations

from typing import Optional

from ..contracts import (
    CognitionPort,
    CodingDiagnosisPort,
    ConversationHistoryPort,
    ConversationContextPort,
    CourseRetrievalPort,
    DisciplineKnowledgePort,
    ExperimentDispatchPort,
    ExperimentPort,
    KnowledgeGraphPort,
    LearningAdjustmentPort,
    LearningEventPort,
    QuestionBankPort,
    QuestionGenerationPort,
    RecommendationPort,
    SandboxPort,
    SafetyGuardPort,
    ScopePort,
    StudentModelingPort,
    StudentHistoryPort,
    TrajectoryPort,
    TeacherSafetyValvePort,
    TeachingConstraintPort,
    TeachingLLMPort,
    TeachingTools,
    ToolGovernancePort,
    VisualizationPort,
    WebResearchPort,
)
from ..tools.integration import RetrievalDemoEvidencePort, RetrievalDemoKnowledgeGraphPort, RetrievalDemoScopePort
from ..providers.retrieval.active_bundle import (
    ActiveBundleCourseRetrievalPort,
    ActiveBundleKnowledgeGraphPort,
    ActiveBundleScopePort,
)
from ..providers.retrieval.discipline_kb import DisciplineKnowledgePortImpl
from app.core.config import settings
from ..tools.kg_mest_shadow import KGMetShadowReportStudentModelingPort
from .runtime import TeachingAgentRuntime


def _discipline_knowledge_port() -> DisciplineKnowledgePort | None:
    """R14：学科垂类知识库参考端口。

    本地只读 JSON 资源（无外部服务/密钥/成本），默认注入；教师策略
    仍可在运行时通过工具治理禁用（discipline_knowledge 工具名）。
    """
    if not getattr(settings, "TEACHING_AGENT_DISCIPLINE_KB_ENABLED", True):
        return None
    return DisciplineKnowledgePortImpl()


def build_teaching_runtime(
    *,
    scope: ScopePort,
    knowledge_graph: KnowledgeGraphPort,
    retrieval: CourseRetrievalPort,
    student_modeling: StudentModelingPort,
    recommendation: RecommendationPort,
    sandbox: SandboxPort,
    learning_events: LearningEventPort,
    llm: TeachingLLMPort,
    web_research: Optional[WebResearchPort] = None,
    cognition: Optional[CognitionPort] = None,
    question_bank: Optional[QuestionBankPort] = None,
    question_generation: Optional[QuestionGenerationPort] = None,
    conversation_context: Optional[ConversationContextPort] = None,
    tool_governance: Optional[ToolGovernancePort] = None,
    teacher_safety_valve: Optional[TeacherSafetyValvePort] = None,
    experiment: Optional[ExperimentPort] = None,
    experiment_dispatch: Optional[ExperimentDispatchPort] = None,
    visualization: Optional[VisualizationPort] = None,
    coding_diagnosis: Optional[CodingDiagnosisPort] = None,
    student_history: Optional[StudentHistoryPort] = None,
    trajectory: Optional[TrajectoryPort] = None,
    teaching_constraints: Optional[TeachingConstraintPort] = None,
    conversation_history: Optional[ConversationHistoryPort] = None,
    learning_adjustment: Optional[LearningAdjustmentPort] = None,
    safety_guard: Optional[SafetyGuardPort] = None,
    discipline_knowledge: Optional[DisciplineKnowledgePort] = None,
) -> TeachingAgentRuntime:
    """Build an enabled runtime only after the composition root supplies every Port."""
    return TeachingAgentRuntime(TeachingTools(
        scope=scope, knowledge_graph=knowledge_graph, retrieval=retrieval,
        student_modeling=student_modeling, recommendation=recommendation,
        sandbox=sandbox, learning_events=learning_events, llm=llm,
        web_research=web_research, cognition=cognition, question_bank=question_bank, question_generation=question_generation,
        conversation_context=conversation_context,
        tool_governance=tool_governance, teacher_safety_valve=teacher_safety_valve,
        experiment=experiment, experiment_dispatch=experiment_dispatch, visualization=visualization,
        coding_diagnosis=coding_diagnosis, student_history=student_history,
        trajectory=trajectory,
        teaching_constraints=teaching_constraints, conversation_history=conversation_history,
        learning_adjustment=learning_adjustment,
        safety_guard=safety_guard,
        discipline_knowledge=discipline_knowledge,
    ))


def build_course_sidecar_runtime(
    *,
    demo_service: object,
    student_modeling: StudentModelingPort,
    recommendation: RecommendationPort,
    sandbox: SandboxPort,
    learning_events: LearningEventPort,
    llm: TeachingLLMPort,
    web_research: Optional[WebResearchPort] = None,
    cognition: Optional[CognitionPort] = None,
    question_bank: Optional[QuestionBankPort] = None,
    question_generation: Optional[QuestionGenerationPort] = None,
    conversation_context: Optional[ConversationContextPort] = None,
    tool_governance: Optional[ToolGovernancePort] = None,
    teacher_safety_valve: Optional[TeacherSafetyValvePort] = None,
    experiment: Optional[ExperimentPort] = None,
    experiment_dispatch: Optional[ExperimentDispatchPort] = None,
    visualization: Optional[VisualizationPort] = None,
    coding_diagnosis: Optional[CodingDiagnosisPort] = None,
    student_history: Optional[StudentHistoryPort] = None,
    trajectory: Optional[TrajectoryPort] = None,
    teaching_constraints: Optional[TeachingConstraintPort] = None,
    conversation_history: Optional[ConversationHistoryPort] = None,
    learning_adjustment: Optional[LearningAdjustmentPort] = None,
    safety_guard: Optional[SafetyGuardPort] = None,
) -> TeachingAgentRuntime:
    """Use the existing isolated course-sidecar R2 provider for KG/evidence only.

    The caller must still supply scope-checked read-only student, recommendation,
    sandbox, event and LLM ports. This function does not register an API route,
    start a service, access a database, or make the sidecar visible by itself.
    """
    use_active_bundle = (
        getattr(settings, "TEACHING_AGENT_KNOWLEDGE_PROVIDER", "demo")
        == "active_bundle"
    )
    return build_teaching_runtime(
        scope=(ActiveBundleScopePort() if use_active_bundle else RetrievalDemoScopePort(demo_service)),
        knowledge_graph=(
            ActiveBundleKnowledgeGraphPort()
            if use_active_bundle else RetrievalDemoKnowledgeGraphPort(demo_service)
        ),
        retrieval=(
            ActiveBundleCourseRetrievalPort()
            if use_active_bundle else RetrievalDemoEvidencePort(demo_service)
        ),
        student_modeling=student_modeling,
        recommendation=recommendation,
        sandbox=sandbox,
        learning_events=learning_events,
        llm=llm,
        web_research=web_research, cognition=cognition, question_bank=question_bank, question_generation=question_generation,
        conversation_context=conversation_context,
        tool_governance=tool_governance, teacher_safety_valve=teacher_safety_valve,
        experiment=experiment, experiment_dispatch=experiment_dispatch, visualization=visualization,
        coding_diagnosis=coding_diagnosis, student_history=student_history,
        trajectory=trajectory,
        teaching_constraints=teaching_constraints, conversation_history=conversation_history,
        learning_adjustment=learning_adjustment,
        safety_guard=safety_guard,
        discipline_knowledge=_discipline_knowledge_port(),
    )


def build_kg_mest_shadow_sidecar_runtime(
    *,
    demo_service: object,
    shadow_report: dict,
    expected_student_id: str,
    expected_course_id: str,
    recommendation: RecommendationPort,
    sandbox: SandboxPort,
    learning_events: LearningEventPort,
    llm: TeachingLLMPort,
    web_research: Optional[WebResearchPort] = None,
    cognition: Optional[CognitionPort] = None,
    question_bank: Optional[QuestionBankPort] = None,
    question_generation: Optional[QuestionGenerationPort] = None,
    conversation_context: Optional[ConversationContextPort] = None,
    tool_governance: Optional[ToolGovernancePort] = None,
    teacher_safety_valve: Optional[TeacherSafetyValvePort] = None,
    experiment: Optional[ExperimentPort] = None,
    experiment_dispatch: Optional[ExperimentDispatchPort] = None,
    visualization: Optional[VisualizationPort] = None,
    coding_diagnosis: Optional[CodingDiagnosisPort] = None,
    student_history: Optional[StudentHistoryPort] = None,
    trajectory: Optional[TrajectoryPort] = None,
    teaching_constraints: Optional[TeachingConstraintPort] = None,
    conversation_history: Optional[ConversationHistoryPort] = None,
    learning_adjustment: Optional[LearningAdjustmentPort] = None,
    safety_guard: Optional[SafetyGuardPort] = None,
) -> TeachingAgentRuntime:
    """Explicitly inject one approved KG-MEST Shadow report into TeachingAgent."""
    return build_course_sidecar_runtime(
        demo_service=demo_service,
        student_modeling=KGMetShadowReportStudentModelingPort.from_report(
            expected_student_id=expected_student_id,
            expected_course_id=expected_course_id,
            report=shadow_report,
        ),
        recommendation=recommendation,
        sandbox=sandbox,
        learning_events=learning_events,
        llm=llm,
        web_research=web_research, cognition=cognition, question_bank=question_bank, question_generation=question_generation,
        conversation_context=conversation_context,
        tool_governance=tool_governance, teacher_safety_valve=teacher_safety_valve,
        experiment=experiment, experiment_dispatch=experiment_dispatch, visualization=visualization,
        coding_diagnosis=coding_diagnosis, student_history=student_history,
        trajectory=trajectory,
        teaching_constraints=teaching_constraints, conversation_history=conversation_history,
        learning_adjustment=learning_adjustment,
        safety_guard=safety_guard,
    )
