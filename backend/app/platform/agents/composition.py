"""Explicit composition roots for TeachingAgent; no import-time service activation."""

from __future__ import annotations

from typing import Optional

from .contracts import (
    CognitionPort,
    ConversationContextPort,
    CourseRetrievalPort,
    KnowledgeGraphPort,
    LearningEventPort,
    QuestionBankPort,
    RecommendationPort,
    SandboxPort,
    ScopePort,
    StudentModelingPort,
    TeachingLLMPort,
    TeachingTools,
    WebResearchPort,
)
from .runtime import TeachingAgentRuntime
from .tools.integration import RetrievalDemoEvidencePort, RetrievalDemoKnowledgeGraphPort, RetrievalDemoScopePort
from .tools.kg_mest_shadow import KGMetShadowReportStudentModelingPort


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
    conversation_context: Optional[ConversationContextPort] = None,
) -> TeachingAgentRuntime:
    """Build an enabled runtime only after the composition root supplies every Port."""
    return TeachingAgentRuntime(TeachingTools(
        scope=scope, knowledge_graph=knowledge_graph, retrieval=retrieval,
        student_modeling=student_modeling, recommendation=recommendation,
        sandbox=sandbox, learning_events=learning_events, llm=llm,
        web_research=web_research, cognition=cognition, question_bank=question_bank,
        conversation_context=conversation_context,
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
    conversation_context: Optional[ConversationContextPort] = None,
) -> TeachingAgentRuntime:
    """Use the existing isolated course-sidecar R2 provider for KG/evidence only.

    The caller must still supply scope-checked read-only student, recommendation,
    sandbox, event and LLM ports. This function does not register an API route,
    start a service, access a database, or make the sidecar visible by itself.
    """
    return build_teaching_runtime(
        scope=RetrievalDemoScopePort(demo_service),
        knowledge_graph=RetrievalDemoKnowledgeGraphPort(demo_service),
        retrieval=RetrievalDemoEvidencePort(demo_service),
        student_modeling=student_modeling,
        recommendation=recommendation,
        sandbox=sandbox,
        learning_events=learning_events,
        llm=llm,
        web_research=web_research,
        cognition=cognition,
        question_bank=question_bank,
        conversation_context=conversation_context,
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
    conversation_context: Optional[ConversationContextPort] = None,
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
        web_research=web_research,
        cognition=cognition,
        question_bank=question_bank,
        conversation_context=conversation_context,
    )
