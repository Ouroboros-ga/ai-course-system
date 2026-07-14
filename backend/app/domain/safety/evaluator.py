"""
SafetyEvaluator: three-stage safety evaluation (input, source, output).

Each stage produces a result containing the decision and any matched rules.
The evaluator fails closed: on any unexpected error, it returns an ERROR
decision rather than allowing potentially unsafe content through.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .decision import (
    DecisionOutcome,
    DecisionStage,
    ReasonCode,
    SafetyDecision,
    SourceAccessDecision,
)
from .policy import PolicySet
from .rules import BaseRule, RuleAction


# ---------------------------------------------------------------------------
# Stage-specific result containers
# ---------------------------------------------------------------------------


@dataclass
class InputCheckResult:
    """Result of input-stage safety checks.

    Parameters
    ----------
    decision : SafetyDecision
        The overall decision for this stage.
    matched_rules : list of BaseRule
        Rules that matched during evaluation.
    """

    decision: SafetyDecision
    matched_rules: List[BaseRule] = field(default_factory=list)

    @property
    def is_allowed(self) -> bool:
        """Return True if the input may proceed to the next stage."""
        return self.decision.outcome in (
            DecisionOutcome.PASS,
            DecisionOutcome.REQUIRE_CITATION,
        )


@dataclass
class SourceCheckResult:
    """Result of source-stage safety checks.

    Parameters
    ----------
    source_decisions : list of SourceAccessDecision
        Per-source access decisions.
    overall_decision : SafetyDecision
        Overall decision for this stage.
    """

    source_decisions: List[SourceAccessDecision] = field(default_factory=list)
    overall_decision: SafetyDecision = field(default_factory=lambda: SafetyDecision.pass_decision(DecisionStage.SOURCE))  # noqa: E501

    @property
    def all_sources_allowed(self) -> bool:
        """Return True if every checked source is allowed."""
        return all(sd.allowed for sd in self.source_decisions)


@dataclass
class OutputCheckResult:
    """Result of output-stage safety checks.

    Parameters
    ----------
    decision : SafetyDecision
        The overall decision for this stage.
    matched_rules : list of BaseRule
        Rules that matched during evaluation.
    """

    decision: SafetyDecision
    matched_rules: List[BaseRule] = field(default_factory=list)

    @property
    def is_allowed(self) -> bool:
        """Return True if the output may be returned to the user."""
        return self.decision.outcome == DecisionOutcome.PASS


# ---------------------------------------------------------------------------
# SafetyEvaluator
# ---------------------------------------------------------------------------


class SafetyEvaluator:
    """Three-stage safety evaluator.

    Stages:
    1. Input: evaluate user input against keyword/regex rules.
    2. Source: evaluate source material access permissions.
    3. Output: evaluate generated output before returning to user.

    On any unexpected error, the evaluator returns an ERROR decision
    (fail-closed).  It never silently allows content through on error.
    """

    def __init__(self, policy_set: PolicySet) -> None:
        self._policy_set = policy_set

    @property
    def policy_set(self) -> PolicySet:
        return self._policy_set

    # ------------------------------------------------------------------
    # Stage 1: Input checks
    # ------------------------------------------------------------------

    def check_input(self, text: str, context: Optional[Dict[str, Any]] = None) -> InputCheckResult:
        """Evaluate user input against all safety rules.

        Returns an ``InputCheckResult`` containing the decision and
        matched rules.  Fail-closed: if evaluation fails unexpectedly,
        returns an ERROR decision.
        """
        try:
            matched = self._policy_set.evaluate_all(text)
            action = self._policy_set.resolve_all(matched)

            if action is None:
                return InputCheckResult(
                    decision=SafetyDecision.pass_decision(DecisionStage.INPUT),
                    matched_rules=[],
                )

            outcome, reason_code, detail = self._action_to_outcome(
                action, DecisionStage.INPUT, matched
            )

            decision = SafetyDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                stage=DecisionStage.INPUT,
                outcome=outcome,
                reason_code=reason_code,
                reason_detail=detail,
                matched_rule_ids=[r.rule_id for r in matched],
                metadata=context or {},
            )
            return InputCheckResult(decision=decision, matched_rules=matched)

        except Exception as e:
            return InputCheckResult(
                decision=SafetyDecision.error_decision(
                    DecisionStage.INPUT,
                    reason_detail=f"Input check failed: {e}",
                ),
                matched_rules=[],
            )

    # ------------------------------------------------------------------
    # Stage 2: Source checks
    # ------------------------------------------------------------------

    def check_source(
        self,
        source_id: str,
        source_name: str,
        course_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SourceAccessDecision:
        """Check whether a source material is accessible.

        This checks platform-level source access rules.  Currently
        returns ALLOW for all sources; course-level source restrictions
        are defined by course policies.

        Returns a ``SourceAccessDecision``.  Fail-closed.
        """
        try:
            # Evaluate platform rules against the source name
            matched = self._policy_set.platform_policy.evaluate(source_name)
            if matched:
                action = self._policy_set.platform_policy.resolve(matched)
                if action in (RuleAction.DENY, RuleAction.HOMEWORK_ANSWER):
                    return SourceAccessDecision(
                        source_id=source_id,
                        source_name=source_name,
                        allowed=False,
                        reason_code=ReasonCode.SAFETY_SOURCE_002,
                        reason_detail=f"Platform rule blocked access to source: {source_name}",
                        course_id=course_id,
                        metadata=context or {},
                    )

            # Also check course-level policies
            for cp in self._policy_set.course_policies:
                course_matched = cp.evaluate(source_name)
                if course_matched:
                    action = cp.resolve(course_matched)
                    if action == RuleAction.DENY:
                        return SourceAccessDecision(
                            source_id=source_id,
                            source_name=source_name,
                            allowed=False,
                            reason_code=ReasonCode.SAFETY_SOURCE_003,
                            reason_detail=f"Course rule blocked access to source: {source_name}",
                            course_id=course_id,
                            metadata=context or {},
                        )

            # Default: allow
            return SourceAccessDecision(
                source_id=source_id,
                source_name=source_name,
                allowed=True,
                reason_code=ReasonCode.SAFETY_PASS_001,
                reason_detail="Source access permitted",
                course_id=course_id,
                metadata=context or {},
            )

        except Exception as e:
            # Fail closed
            return SourceAccessDecision(
                source_id=source_id,
                source_name=source_name,
                allowed=False,
                reason_code=ReasonCode.SAFETY_ERROR_001,
                reason_detail=f"Source check failed: {e}",
                course_id=course_id,
                metadata=context or {},
            )

    def check_sources(
        self,
        sources: List[Dict[str, Any]],
        course_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SourceCheckResult:
        """Check multiple source materials.

        Each source dict must have at least ``source_id`` and ``source_name``.
        Returns a ``SourceCheckResult`` with per-source decisions.
        """
        decisions = []
        all_allowed = True

        for src in sources:
            sd = self.check_source(
                source_id=src.get("source_id", ""),
                source_name=src.get("source_name", ""),
                course_id=course_id or src.get("course_id"),
                context=context,
            )
            decisions.append(sd)
            if not sd.allowed:
                all_allowed = False

        if all_allowed:
            overall = SafetyDecision.pass_decision(DecisionStage.SOURCE)
        else:
            blocked = [d for d in decisions if not d.allowed]
            overall = SafetyDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                stage=DecisionStage.SOURCE,
                outcome=DecisionOutcome.BLOCK,
                reason_code=ReasonCode.SAFETY_SOURCE_001,
                reason_detail=f"{len(blocked)} source(s) not in allowed access list",
                matched_rule_ids=[],
                metadata=context or {},
            )

        return SourceCheckResult(
            source_decisions=decisions,
            overall_decision=overall,
        )

    # ------------------------------------------------------------------
    # Stage 3: Output checks
    # ------------------------------------------------------------------

    def check_output(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> OutputCheckResult:
        """Evaluate generated output before returning to the user.

        Returns an ``OutputCheckResult``.  Fail-closed.
        """
        try:
            matched = self._policy_set.evaluate_all(text)
            action = self._policy_set.resolve_all(matched)

            if action is None:
                return OutputCheckResult(
                    decision=SafetyDecision.pass_decision(DecisionStage.OUTPUT),
                    matched_rules=[],
                )

            outcome, reason_code, detail = self._action_to_outcome(
                action, DecisionStage.OUTPUT, matched
            )

            decision = SafetyDecision(
                decision_id=f"dec-{uuid.uuid4().hex[:12]}",
                stage=DecisionStage.OUTPUT,
                outcome=outcome,
                reason_code=reason_code,
                reason_detail=detail,
                matched_rule_ids=[r.rule_id for r in matched],
                metadata=context or {},
            )
            return OutputCheckResult(decision=decision, matched_rules=matched)

        except Exception as e:
            return OutputCheckResult(
                decision=SafetyDecision.error_decision(
                    DecisionStage.OUTPUT,
                    reason_detail=f"Output check failed: {e}",
                ),
                matched_rules=[],
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _action_to_outcome(
        action: RuleAction,
        stage: DecisionStage,
        matched: List[BaseRule],
    ) -> tuple:
        """Map a RuleAction to (DecisionOutcome, ReasonCode, detail string)."""
        rule_ids = ", ".join(r.rule_id for r in matched)

        if action == RuleAction.DENY:
            if stage == DecisionStage.INPUT:
                return (DecisionOutcome.BLOCK, ReasonCode.SAFETY_INPUT_001,
                        f"Input blocked by rules: {rule_ids}")
            elif stage == DecisionStage.OUTPUT:
                return (DecisionOutcome.BLOCK, ReasonCode.SAFETY_OUTPUT_001,
                        f"Output blocked by rules: {rule_ids}")
            return (DecisionOutcome.BLOCK, ReasonCode.SAFETY_ERROR_001,
                    f"Blocked by rules: {rule_ids}")

        if action == RuleAction.RESTRICT:
            if stage == DecisionStage.INPUT:
                return (DecisionOutcome.RESTRICT, ReasonCode.SAFETY_INPUT_002,
                        f"Input restricted by rules: {rule_ids}")
            elif stage == DecisionStage.OUTPUT:
                return (DecisionOutcome.RESTRICT, ReasonCode.SAFETY_OUTPUT_002,
                        f"Output restricted by rules: {rule_ids}")
            return (DecisionOutcome.RESTRICT, ReasonCode.SAFETY_ERROR_001,
                    f"Restricted by rules: {rule_ids}")

        if action == RuleAction.REQUIRE_CITATION:
            if stage == DecisionStage.OUTPUT:
                return (DecisionOutcome.REQUIRE_CITATION, ReasonCode.SAFETY_OUTPUT_005,
                        f"Citation required by rules: {rule_ids}")
            # For input/source, pass through with a note
            return (DecisionOutcome.PASS, ReasonCode.SAFETY_PASS_001,
                    f"Pass (citation check noted): {rule_ids}")

        if action == RuleAction.HOMEWORK_ANSWER:
            if stage == DecisionStage.INPUT:
                return (DecisionOutcome.HOMEWORK_HINT, ReasonCode.SAFETY_INPUT_004,
                        f"Homework-answer pattern detected: {rule_ids}")
            elif stage == DecisionStage.OUTPUT:
                return (DecisionOutcome.HOMEWORK_HINT, ReasonCode.SAFETY_OUTPUT_004,
                        f"Output flagged as homework answer: {rule_ids}")
            return (DecisionOutcome.HOMEWORK_HINT, ReasonCode.SAFETY_ERROR_001,
                    f"Homework-answer flagged: {rule_ids}")

        return (DecisionOutcome.PASS, ReasonCode.SAFETY_PASS_001, "Pass")
