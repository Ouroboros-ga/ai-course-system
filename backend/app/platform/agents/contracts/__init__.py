"""Port protocol package (facade).

Commit 3 splits the former monolithic ``contracts.py`` into domain-specific
submodules. This ``__init__`` is now a façade that re-exports every public
protocol and the ``TeachingTools`` container, so all existing imports keep
working unchanged:

    from app.platform.agents.contracts import TeachingTools
    from app.platform.agents.contracts import ScopePort, CognitionPort, ...
    from ..contracts import LearningEventPort, ToolGovernancePort, ...

Submodule layout:
    - ``retrieval``:    ScopePort, KnowledgeGraphPort, CourseRetrievalPort
    - ``cognition``:    StudentModelingPort, CognitionPort, StudentHistoryPort
    - ``sandbox``:      SandboxPort, CodingDiagnosisPort
    - ``teaching``:     RecommendationPort, LearningEventPort,
                        ConversationContextPort, TeachingLLMPort
    - ``research``:     PaperSearchPort, WebResearchPort, QuestionBankPort
    - ``writing``:      LiteratureReviewPort, PaperStructurePort
    - ``governance``:   ToolGovernancePort, TeacherSafetyValvePort
    - ``experiment``:   ExperimentPort, VisualizationPort
    - ``tools``:        TeachingTools (assembly container)
"""

from __future__ import annotations

from .cognition import CognitionPort, StudentHistoryPort, StudentModelingPort
from .constraint import ConversationHistoryPort, TeachingConstraintPort
from .experiment import ExperimentPort, VisualizationPort
from .governance import TeacherSafetyValvePort, ToolGovernancePort
from .learning_adjustment import LearningAdjustmentPort
from .research import (
    CodeReproductionPort,
    PaperSearchPort,
    QuestionBankPort,
    QuestionGenerationPort,
    ResearchScopePort,
    TrendAnalysisPort,
    WebResearchPort,
)
from .retrieval import CourseRetrievalPort, KnowledgeGraphPort, ScopePort
from .sandbox import CodingDiagnosisPort, SandboxPort
from .teaching import ConversationContextPort, LearningEventPort, RecommendationPort, TeachingLLMPort
from .tools import TeachingTools
from .writing import LiteratureReviewPort, PaperStructurePort

__all__ = [
    "ScopePort",
    "KnowledgeGraphPort",
    "CourseRetrievalPort",
    "StudentModelingPort",
    "RecommendationPort",
    "SandboxPort",
    "CodingDiagnosisPort",
    "StudentHistoryPort",
    "LearningEventPort",
    "ConversationContextPort",
    "TeachingLLMPort",
    "WebResearchPort",
    "PaperSearchPort",
    "ResearchScopePort",
    "TrendAnalysisPort",
    "CodeReproductionPort",
    "LiteratureReviewPort",
    "PaperStructurePort",
    "CognitionPort",
    "QuestionBankPort",
    "QuestionGenerationPort",
    "ToolGovernancePort",
    "TeacherSafetyValvePort",
    "ExperimentPort",
    "VisualizationPort",
    "TeachingConstraintPort",
    "ConversationHistoryPort",
    "LearningAdjustmentPort",
    "TeachingTools",
]
