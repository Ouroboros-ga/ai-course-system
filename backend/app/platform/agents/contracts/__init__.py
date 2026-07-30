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
    - ``research``:     WebResearchPort, QuestionBankPort
    - ``governance``:   ToolGovernancePort, TeacherSafetyValvePort
    - ``experiment``:   ExperimentPort, VisualizationPort
    - ``tools``:        TeachingTools (assembly container)
"""

from __future__ import annotations

from .cognition import CognitionPort, StudentHistoryPort, StudentModelingPort
from .experiment import ExperimentPort, VisualizationPort
from .governance import TeacherSafetyValvePort, ToolGovernancePort
from .research import QuestionBankPort, WebResearchPort
from .retrieval import CourseRetrievalPort, KnowledgeGraphPort, ScopePort
from .sandbox import CodingDiagnosisPort, SandboxPort
from .teaching import ConversationContextPort, LearningEventPort, RecommendationPort, TeachingLLMPort
from .tools import TeachingTools

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
    "CognitionPort",
    "QuestionBankPort",
    "ToolGovernancePort",
    "TeacherSafetyValvePort",
    "ExperimentPort",
    "VisualizationPort",
    "TeachingTools",
]
