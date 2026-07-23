"""KG-MEST research baseline.

This package is deliberately isolated from ``backend/app``.  It consumes
synthetic, pseudonymised input records only and is not a production Provider.
"""

from .kg_mest import (
    ConceptState,
    Dimension,
    GraphSnapshot,
    GraphEvidenceGrounder,
    KG_MEST_POLICY_VERSION,
    KG_MEST_VERSION,
    LearningEvent,
    LearningPathRecommender,
    MultiSourceEvidenceEngine,
)
from .teaching_adapter import SyntheticKGMetStudentModelingPort, state_to_teaching_view
from .graph_adapter import GraphAdaptationResult, adapt_cognition_graph
from .legacy_prerequisite_candidates import (
    LegacyCandidateBuildResult,
    LegacyPrerequisiteCandidate,
    build_legacy_prerequisite_candidates,
)
from .education_graph_release_adapter import EducationGraphReleaseResult, adapt_education_graph_release
from .learning_event_release_adapter import LearningEventReleaseResult, adapt_learning_event_release
from .shadow_pipeline import ReadOnlyShadowResult, run_read_only_shadow
from .shadow_bundle import BUNDLE_SCHEMA_VERSION, ShadowBundleRunResult, artifact_sha256, run_shadow_bundle

__all__ = [
    "ConceptState",
    "Dimension",
    "GraphSnapshot",
    "GraphEvidenceGrounder",
    "KG_MEST_POLICY_VERSION",
    "KG_MEST_VERSION",
    "LearningEvent",
    "LearningPathRecommender",
    "MultiSourceEvidenceEngine",
    "SyntheticKGMetStudentModelingPort",
    "state_to_teaching_view",
    "GraphAdaptationResult",
    "adapt_cognition_graph",
    "LegacyCandidateBuildResult",
    "LegacyPrerequisiteCandidate",
    "build_legacy_prerequisite_candidates",
    "EducationGraphReleaseResult",
    "adapt_education_graph_release",
    "LearningEventReleaseResult",
    "adapt_learning_event_release",
    "ReadOnlyShadowResult",
    "run_read_only_shadow",
    "BUNDLE_SCHEMA_VERSION",
    "ShadowBundleRunResult",
    "artifact_sha256",
    "run_shadow_bundle",
]
