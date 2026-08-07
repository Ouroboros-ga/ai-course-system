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
from typing import Optional

from .cognition import CognitionPort, StudentHistoryPort, StudentModelingPort
from .experiment import ExperimentPort, VisualizationPort
from .governance import TeacherSafetyValvePort, ToolGovernancePort
from .research import QuestionBankPort, QuestionGenerationPort, WebResearchPort
from .retrieval import CourseRetrievalPort, KnowledgeGraphPort, ScopePort
from .sandbox import CodingDiagnosisPort, SandboxPort
from .teaching import ConversationContextPort, LearningEventPort, RecommendationPort, TeachingLLMPort


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
    # 出题工具：依据知识点/认知/提问信号生成草稿，教师 approve 后才进题库
    question_generation: Optional[QuestionGenerationPort] = None
    conversation_context: Optional[ConversationContextPort] = None
    # 阶段9新增可选工具治理与教师安全阀端口；未注入时 workflow 节点跳过治理与提案
    tool_governance: Optional[ToolGovernancePort] = None
    teacher_safety_valve: Optional[TeacherSafetyValvePort] = None
    experiment: Optional[ExperimentPort] = None
    visualization: Optional[VisualizationPort] = None


__all__ = ["TeachingTools"]
