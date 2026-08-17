"""``TeachingTools``: the assembly container for the TeachingAgent's ports.

This dataclass is the only place that knows the full set of ports a
``TeachingAgentRuntime`` needs. Optional ports default to ``None``; the
workflow nodes skip execution when the corresponding port is not injected.

The container is retained for backward compatibility. New agents (Prep,
Coding) do NOT use this container; they wire their own tools via their
composition roots.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cognition import (
    CognitionPort,
    StudentHistoryPort,
    StudentModelingPort,
    TrajectoryPort,
)
from .constraint import ConversationHistoryPort, TeachingConstraintPort
from .experiment import ExperimentDispatchPort, ExperimentPort, VisualizationPort
from .governance import TeacherSafetyValvePort, ToolGovernancePort
from .learning_adjustment import LearningAdjustmentPort
from .research import QuestionBankPort, QuestionGenerationPort, WebResearchPort
from .retrieval import CourseRetrievalPort, KnowledgeGraphPort, ScopePort
from .safety import SafetyGuardPort
from .sandbox import CodingDiagnosisPort, SandboxPort
from .teaching import (
    ConversationContextPort,
    LearningEventPort,
    RecommendationPort,
    TeachingLLMPort,
)


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
    coding_diagnosis: CodingDiagnosisPort | None = None
    student_history: StudentHistoryPort | None = None
    # 批次4新增可选工具：未注入时 workflow 节点跳过执行，不影响现有流程
    web_research: WebResearchPort | None = None
    cognition: CognitionPort | None = None
    question_bank: QuestionBankPort | None = None
    # 出题工具：依据知识点/认知/提问信号生成草稿，教师 approve 后才进题库
    question_generation: QuestionGenerationPort | None = None
    conversation_context: ConversationContextPort | None = None
    # 阶段9新增可选工具治理与教师安全阀端口；未注入时 workflow 节点跳过治理与提案
    tool_governance: ToolGovernancePort | None = None
    teacher_safety_valve: TeacherSafetyValvePort | None = None
    experiment: ExperimentPort | None = None
    # This port can create a teacher-confirmation proposal only.  The current
    # teaching workflow deliberately does not invoke it until a governed
    # recommendation node is introduced.
    experiment_dispatch: ExperimentDispatchPort | None = None
    visualization: VisualizationPort | None = None
    teaching_constraints: TeachingConstraintPort | None = None
    conversation_history: ConversationHistoryPort | None = None
    learning_adjustment: LearningAdjustmentPort | None = None
    # 2026-08-16：内容安全闸门端口。在 validate_request 后执行课程安全围栏评估；
    # 未注入时安全节点 no-op 放行，不影响现有流程。
    safety_guard: SafetyGuardPort | None = None
    # 2026-08-17：学习轨迹端口（M7）。load_learning_history 优先读该端口；
    # record_event 以 trace_id 幂等追加轨迹事件。未注入时回退 student_history。
    trajectory: TrajectoryPort | None = None


__all__ = ["TeachingTools"]
