"""
P1-07 Learning Events and Explainable Cognition Domain.

Provides append-only LearningEvents, derived LearningEvidence,
MasteryState, MisconceptionState, Recommendation, evidence
aggregation rules, and existing-data compatibility mappers.

Ownership: P1-07 only.
"""

from .event import (
    LearningEvent,
    EventType,
    EventCorrection,
    EVENT_VERSION,
)
from .evidence import (
    LearningEvidence,
    EvidenceType,
    EvidenceAggregationRule,
)
from .mastery_state import (
    MasteryState,
    MasteryLevel,
    MasterySource,
)
from .misconception import (
    MisconceptionState,
    MisconceptionType,
    MisconceptionSeverity,
)
from .recommendation import (
    Recommendation,
    RecommendationType,
    RecommendationPriority,
)
from .compat_mappers import (
    map_progress_to_events,
    map_quiz_to_events,
    map_chat_to_events,
    map_jump_to_events,
    ExistingDataMapper,
)
from .aggregation import (
    aggregate_evidence,
    EvidenceAggregator,
)

__all__ = [
    # event
    "LearningEvent", "EventType", "EventCorrection", "EVENT_VERSION",
    # evidence
    "LearningEvidence", "EvidenceType", "EvidenceAggregationRule",
    # mastery
    "MasteryState", "MasteryLevel", "MasterySource",
    # misconception
    "MisconceptionState", "MisconceptionType", "MisconceptionSeverity",
    # recommendation
    "Recommendation", "RecommendationType", "RecommendationPriority",
    # compat
    "map_progress_to_events", "map_quiz_to_events",
    "map_chat_to_events", "map_jump_to_events", "ExistingDataMapper",
    # aggregation
    "aggregate_evidence", "EvidenceAggregator",
]
