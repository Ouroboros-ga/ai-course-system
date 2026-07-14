"""
SafetyDecision, SourceAccessDecision, and stable ReasonCode definitions.

Contract version: safety/1.0

Reason codes are guaranteed stable across versions: once assigned, a reason
code's semantics never change. New codes may be added (minor), but existing
codes are never removed or redefined (major change).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Canonical contract version registered with the safety registry.
SAFETY_VERSION: str = "safety/1.0"

# ---------------------------------------------------------------------------
# DecisionStage
# ---------------------------------------------------------------------------


class DecisionStage(str, enum.Enum):
    """The stage at which a decision was made."""

    INPUT = "input"
    """Before processing the user's question/request."""

    SOURCE = "source"
    """When checking access to source materials."""

    OUTPUT = "output"
    """Before returning the final answer to the user."""


# ---------------------------------------------------------------------------
# DecisionOutcome
# ---------------------------------------------------------------------------


class DecisionOutcome(str, enum.Enum):
    """The outcome of a safety evaluation."""

    PASS = "pass"
    """Content passed all safety checks."""

    BLOCK = "block"
    """Content was blocked (DENY action)."""

    RESTRICT = "restrict"
    """Content was restricted (RESTRICT action)."""

    REQUIRE_CITATION = "require_citation"
    """Citation required (REQUIRE_CITATION action)."""

    HOMEWORK_HINT = "homework_hint"
    """Homework answer rejected; hint provided instead (HOMEWORK_ANSWER action)."""

    ERROR = "error"
    """Evaluation failed unexpectedly; fail-closed."""


# ---------------------------------------------------------------------------
# ReasonCode - STABLE codes
# ---------------------------------------------------------------------------


class ReasonCode(str, enum.Enum):
    """Stable reason codes for safety decisions.

    Naming convention: ``SAFETY_<STAGE>_<NNN>``.

    These codes are guaranteed stable across versions:
    - Existing codes will NOT be removed or redefined.
    - New codes may be added (minor version bump).
    - Removing or changing semantics requires a major version change.
    """

    # -- Input stage --
    SAFETY_INPUT_001 = "SAFETY_INPUT_001"
    """PII pattern detected in user input."""

    SAFETY_INPUT_002 = "SAFETY_INPUT_002"
    """Prohibited keyword detected in user input."""

    SAFETY_INPUT_003 = "SAFETY_INPUT_003"
    """Prohibited regex pattern detected in user input."""

    SAFETY_INPUT_004 = "SAFETY_INPUT_004"
    """Homework-direct-answer pattern detected in user input."""

    SAFETY_INPUT_005 = "SAFETY_INPUT_005"
    """Regex evaluation timeout; fail-closed block."""

    # -- Source stage --
    SAFETY_SOURCE_001 = "SAFETY_SOURCE_001"
    """Source material is not in the allowed access list."""

    SAFETY_SOURCE_002 = "SAFETY_SOURCE_002"
    """Source material access denied by platform rule."""

    SAFETY_SOURCE_003 = "SAFETY_SOURCE_003"
    """Source material access denied by course rule."""

    SAFETY_SOURCE_004 = "SAFETY_SOURCE_004"
    """Required citation could not be verified."""

    # -- Output stage --
    SAFETY_OUTPUT_001 = "SAFETY_OUTPUT_001"
    """Output contains prohibited content (PII)."""

    SAFETY_OUTPUT_002 = "SAFETY_OUTPUT_002"
    """Output contains prohibited keyword."""

    SAFETY_OUTPUT_003 = "SAFETY_OUTPUT_003"
    """Output contains prohibited regex pattern."""

    SAFETY_OUTPUT_004 = "SAFETY_OUTPUT_004"
    """Output flagged as homework answer; must be restricted."""

    SAFETY_OUTPUT_005 = "SAFETY_OUTPUT_005"
    """Output lacks required citation."""

    SAFETY_OUTPUT_006 = "SAFETY_OUTPUT_006"
    """Output contains prohibited source material."""

    # -- Error --
    SAFETY_ERROR_001 = "SAFETY_ERROR_001"
    """Safety evaluation failed due to internal error; fail-closed."""

    # -- Pass --
    SAFETY_PASS_001 = "SAFETY_PASS_001"
    """Content passed all safety checks."""


# ---------------------------------------------------------------------------
# SafetyDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyDecision:
    """The result of a safety evaluation at a given stage.

    Parameters
    ----------
    decision_id : str
        Unique decision identifier.
    stage : DecisionStage
        Which stage produced this decision.
    outcome : DecisionOutcome
        The decision outcome.
    reason_code : ReasonCode
        Stable reason code for this decision.
    reason_detail : str
        Human-readable explanation.
    matched_rule_ids : list of str
        The rule IDs that triggered this decision.
    timestamp : str
        ISO 8601 timestamp.
    metadata : dict
        Additional context (must not contain secrets/tokens/full user content).
    """

    decision_id: str
    stage: DecisionStage
    outcome: DecisionOutcome
    reason_code: ReasonCode
    reason_detail: str = ""
    matched_rule_ids: List[str] = field(default_factory=list)
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(
                self,
                "timestamp",
                datetime.now(timezone.utc).isoformat(),
            )

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code.value,
            "reason_detail": self.reason_detail,
            "matched_rule_ids": list(self.matched_rule_ids),
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def pass_decision(
        stage: DecisionStage,
        decision_id: Optional[str] = None,
    ) -> "SafetyDecision":
        """Create a pass decision."""
        import uuid
        return SafetyDecision(
            decision_id=decision_id or f"dec-{uuid.uuid4().hex[:12]}",
            stage=stage,
            outcome=DecisionOutcome.PASS,
            reason_code=ReasonCode.SAFETY_PASS_001,
            reason_detail=f"{stage.value.capitalize()} checks passed",
        )

    @staticmethod
    def block_decision(
        stage: DecisionStage,
        reason_code: ReasonCode,
        reason_detail: str = "",
        matched_rule_ids: Optional[List[str]] = None,
        decision_id: Optional[str] = None,
    ) -> "SafetyDecision":
        """Create a block decision."""
        import uuid
        return SafetyDecision(
            decision_id=decision_id or f"dec-{uuid.uuid4().hex[:12]}",
            stage=stage,
            outcome=DecisionOutcome.BLOCK,
            reason_code=reason_code,
            reason_detail=reason_detail,
            matched_rule_ids=matched_rule_ids or [],
        )

    @staticmethod
    def error_decision(
        stage: DecisionStage,
        reason_detail: str = "",
        decision_id: Optional[str] = None,
    ) -> "SafetyDecision":
        """Create an error (fail-closed) decision."""
        import uuid
        return SafetyDecision(
            decision_id=decision_id or f"dec-{uuid.uuid4().hex[:12]}",
            stage=stage,
            outcome=DecisionOutcome.ERROR,
            reason_code=ReasonCode.SAFETY_ERROR_001,
            reason_detail=reason_detail or "Safety evaluation failed",
        )


# ---------------------------------------------------------------------------
# SourceAccessDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceAccessDecision:
    """Decision about whether a source material is accessible.

    Parameters
    ----------
    source_id : str
        The source material identifier.
    source_name : str
        Human-readable source name.
    allowed : bool
        Whether access is permitted.
    reason_code : ReasonCode
        Stable reason code.
    reason_detail : str
        Explanation of the decision.
    course_id : str or None
        The course context.
    metadata : dict
        Additional context (minimized).
    """

    source_id: str
    source_name: str
    allowed: bool
    reason_code: ReasonCode
    reason_detail: str = ""
    course_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "allowed": self.allowed,
            "reason_code": self.reason_code.value,
            "reason_detail": self.reason_detail,
            "course_id": self.course_id,
            "metadata": dict(self.metadata),
        }
