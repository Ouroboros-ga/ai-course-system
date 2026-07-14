"""
P1-08 Teacher Safety Policy and Audit Governance.

Provides platform-level and course-level safety policies, keyword/regex rules
with ReDoS protection, three-stage evaluation (input, source, output),
stable reason codes, and audited decision logging with data minimization.

Ownership: P1-08 only.
"""

from .rules import (
    BaseRule,
    KeywordRule,
    RegexRule,
    RuleAction,
    ReDoSProtection,
)
from .policy import (
    SafetyPolicy,
    PolicySet,
    RuleConflictStrategy,
    PlatformPolicy,
)
from .decision import (
    SafetyDecision,
    SourceAccessDecision,
    ReasonCode,
    DecisionStage,
    DecisionOutcome,
)
from .evaluator import (
    SafetyEvaluator,
    InputCheckResult,
    SourceCheckResult,
    OutputCheckResult,
)
from .audit import (
    AuditEvent,
    AuditSink,
    ConsoleAuditSink,
    NoOpAuditSink,
    AuditLevel,
)

__all__ = [
    # rules
    "BaseRule", "KeywordRule", "RegexRule", "RuleAction", "ReDoSProtection",
    # policy
    "SafetyPolicy", "PolicySet", "RuleConflictStrategy", "PlatformPolicy",
    # decision
    "SafetyDecision", "SourceAccessDecision", "ReasonCode",
    "DecisionStage", "DecisionOutcome",
    # evaluator
    "SafetyEvaluator", "InputCheckResult", "SourceCheckResult",
    "OutputCheckResult",
    # audit
    "AuditEvent", "AuditSink", "ConsoleAuditSink", "NoOpAuditSink",
    "AuditLevel",
]
