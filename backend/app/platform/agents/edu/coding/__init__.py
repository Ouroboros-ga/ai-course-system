"""TeachingAgent's internal code-teaching capability.

Product callers enter through the TeachingAgent coding-challenge facade.  The
legacy ``platform.agents.coding`` package remains a compatibility delegate for
older experiment endpoints; new conversational behavior belongs here.
"""

from .decision import CodingChallengeDecisionPolicy, coding_challenge_decision_policy
from .feedback import build_teaching_feedback

__all__ = [
    "CodingChallengeDecisionPolicy",
    "build_teaching_feedback",
    "coding_challenge_decision_policy",
]
