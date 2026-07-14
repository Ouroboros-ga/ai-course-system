"""
RuleBased mastery baseline: deterministic, explainable, gold-comparable.

This is the baseline mastery provider that uses declarative rules to
assess student mastery from LearningEvidence. Every result lists its
evidence references. No evidence => no strong conclusion.

Version: 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .contracts import MasteryProviderResult
from .provider import AbstractMasteryProvider, ProviderCapability


@dataclass(frozen=True)
class MasteryRule:
    """A single rule used in the rule-based mastery assessment.

    Parameters
    ----------
    rule_id : str
        Stable rule identifier.
    name : str
        Human-readable rule name.
    description : str
        What this rule evaluates.
    weight : float
        Weight for this rule in the overall score (0.0-1.0).
    """

    rule_id: str
    name: str
    description: str
    weight: float = 1.0


@dataclass(frozen=True)
class MasteryRuleResult:
    """Result of applying a single mastery rule.

    Parameters
    ----------
    rule_id : str
        The rule that was applied.
    score : float
        The score contribution from this rule (0.0-1.0).
    weight : float
        The weight of this rule.
    evidence_refs : list of str
        Evidence IDs used by this rule.
    description : str
        Explanation of the rule's contribution.
    """

    rule_id: str
    score: float
    weight: float
    evidence_refs: List[str]
    description: str = ""


@dataclass(frozen=True)
class MasteryRuleSet:
    """A named set of mastery rules for a specific scope."""

    name: str
    rules: List[MasteryRule] = field(default_factory=list)
    description: str = ""


# =========================================================================
# Default rule sets
# =========================================================================

DEFAULT_COURSE_RULES = MasteryRuleSet(
    name="course_mastery_default",
    description="Default course-level mastery rules",
    rules=[
        MasteryRule(
            rule_id="completion-rate",
            name="Course completion rate",
            description="Based on node completion ratio",
            weight=0.3,
        ),
        MasteryRule(
            rule_id="quiz-accuracy",
            name="Quiz accuracy",
            description="Based on quiz correct/incorrect ratio",
            weight=0.4,
        ),
        MasteryRule(
            rule_id="engagement",
            name="Engagement level",
            description="Based on access frequency and questioning",
            weight=0.2,
        ),
        MasteryRule(
            rule_id="prereq-recovery",
            name="Prerequisite recovery",
            description="Based on successful gap recovery",
            weight=0.1,
        ),
    ],
)

DEFAULT_NODE_RULES = MasteryRuleSet(
    name="node_mastery_default",
    description="Default node-level mastery rules",
    rules=[
        MasteryRule(
            rule_id="node-completion",
            name="Node completion",
            description="Based on whether the node was completed",
            weight=0.3,
        ),
        MasteryRule(
            rule_id="node-quiz-accuracy",
            name="Node quiz accuracy",
            description="Based on quiz performance on this node",
            weight=0.5,
        ),
        MasteryRule(
            rule_id="node-questioning",
            name="Node questioning activity",
            description="Based on questions asked about this node",
            weight=0.2,
        ),
    ],
)


def _score_to_level(score: float) -> str:
    """Map a numeric score to a mastery level label."""
    if score >= 0.9:
        return "advanced"
    elif score >= 0.75:
        return "proficient"
    elif score >= 0.5:
        return "developing"
    elif score >= 0.25:
        return "beginner"
    else:
        return "unknown"


def _compute_course_mastery(
    evidence_dict: Dict[str, List[Dict[str, Any]]],
    rules: MasteryRuleSet,
) -> MasteryProviderResult:
    """Compute course-level mastery from evidence dict.

    Parameters
    ----------
    evidence_dict : dict
        Dict mapping evidence_type (str) to list of evidence dicts.
    rules : MasteryRuleSet
        The rule set to apply.

    Returns
    -------
    MasteryProviderResult
    """
    rule_results: List[MasteryRuleResult] = []
    all_evidence_refs: List[str] = []

    for rule in rules.rules:
        score, refs = _evaluate_rule(rule, evidence_dict)
        rule_results.append(
            MasteryRuleResult(
                rule_id=rule.rule_id,
                score=score,
                weight=rule.weight,
                evidence_refs=refs,
                description=_describe_rule_result(rule, score, refs),
            )
        )
        all_evidence_refs.extend(refs)

    # Weighted average over rules that actually have supporting evidence.
    # Rules with no evidence (empty evidence_refs) do not participate in
    # the weighted average: per the contract "no evidence => no strong
    # conclusion", a rule with no evidence must neither inflate nor
    # deflate the mastery score.  This prevents a single high-quality
    # evidence source (e.g. quiz_accuracy=0.95) from being dragged down
    # by unrelated rules that simply have no data yet.
    contributing = [r for r in rule_results if r.evidence_refs]
    total_weight = sum(r.weight for r in contributing)
    if total_weight == 0:
        weighted_score = 0.0
        confidence = 0.0
    else:
        weighted_score = (
            sum(r.score * r.weight for r in contributing) / total_weight
        )
        # Confidence based on evidence coverage
        evidence_count = len(set(all_evidence_refs))
        confidence = min(1.0, evidence_count / 10.0)

    level = _score_to_level(weighted_score)

    return MasteryProviderResult(
        provider_name="rule_based",
        provider_version="1.0.0",
        student_id=0,  # Filled by caller
        course_id=0,  # Filled by caller
        mastery_score=round(weighted_score, 4),
        mastery_level=level,
        confidence=confidence,
        evidence_refs=list(set(all_evidence_refs)),
        metadata={
            "rule_set": rules.name,
            "rule_results": [
                {
                    "rule_id": rr.rule_id,
                    "score": rr.score,
                    "weight": rr.weight,
                    "evidence_count": len(rr.evidence_refs),
                    "description": rr.description,
                }
                for rr in rule_results
            ],
        },
    )


def _compute_node_mastery(
    evidence_dict: Dict[str, List[Dict[str, Any]]],
    rules: MasteryRuleSet,
    node_id: int,
) -> MasteryProviderResult:
    """Compute node-level mastery from evidence dict.

    Filters evidence to node-specific entries before evaluation.
    """
    # Filter to node-specific evidence
    node_evidence: Dict[str, List[Dict[str, Any]]] = {}
    for ev_type, ev_list in evidence_dict.items():
        filtered = [ev for ev in ev_list if ev.get("node_id") == node_id]
        if filtered:
            node_evidence[ev_type] = filtered

    return _compute_course_mastery(node_evidence, rules)


def _evaluate_rule(
    rule: MasteryRule,
    evidence_dict: Dict[str, List[Dict[str, Any]]],
) -> tuple:
    """Evaluate a single mastery rule against available evidence.

    Returns (score, evidence_refs).
    """
    refs: List[str] = []

    if rule.rule_id == "completion-rate":
        completion_evidence = evidence_dict.get("node_completion", [])
        refs = [ev["evidence_id"] for ev in completion_evidence]
        if not completion_evidence:
            return 0.0, []
        scores = [ev.get("value", 0.0) or 0.0 for ev in completion_evidence]
        return sum(scores) / len(scores), refs

    elif rule.rule_id == "quiz-accuracy" or rule.rule_id == "node-quiz-accuracy":
        accuracy_evidence = evidence_dict.get("quiz_accuracy", [])
        refs = [ev["evidence_id"] for ev in accuracy_evidence]
        if not accuracy_evidence:
            return 0.0, []
        scores = [ev.get("value", 0.0) or 0.0 for ev in accuracy_evidence]
        return sum(scores) / len(scores), refs

    elif rule.rule_id == "engagement" or rule.rule_id == "node-questioning":
        engagement_evidence = evidence_dict.get("engagement", []) + evidence_dict.get(
            "questioning", []
        )
        pattern_evidence = evidence_dict.get("quiz_pattern", [])
        refs = [ev["evidence_id"] for ev in engagement_evidence + pattern_evidence]
        if not engagement_evidence and not pattern_evidence:
            return 0.0, []
        # Engagement score: more events = higher score, capped
        total_events = sum(ev.get("value", 0) or 0 for ev in engagement_evidence)
        pattern_penalty = len(pattern_evidence) * 0.1  # patterns reduce score
        score = max(0.0, min(1.0, total_events / 20.0 - pattern_penalty))
        return score, refs

    elif rule.rule_id == "prereq-recovery":
        recovery_evidence = evidence_dict.get("prereq_recovery", [])
        gap_evidence = evidence_dict.get("prereq_gap", [])
        refs = [ev["evidence_id"] for ev in recovery_evidence + gap_evidence]
        if not gap_evidence:
            return 1.0, []  # No gaps = full score
        if not recovery_evidence:
            return 0.0, refs  # Gaps but no recovery = low score
        recovery_rate = len(recovery_evidence) / len(gap_evidence)
        return min(1.0, recovery_rate), refs

    elif rule.rule_id == "node-completion":
        completion_evidence = evidence_dict.get("node_completion", [])
        refs = [ev["evidence_id"] for ev in completion_evidence]
        if not completion_evidence:
            return 0.0, []
        # If any completion evidence exists with value >= 1.0, node is completed
        completed = any(
            (ev.get("value") or 0) >= 1.0 for ev in completion_evidence
        )
        return (1.0 if completed else 0.0), refs

    # Default: unknown rule, return neutral
    return 0.5, refs


def _describe_rule_result(rule: MasteryRule, score: float, refs: List[str]) -> str:
    """Generate a human-readable description of a rule result."""
    if not refs:
        return f"Rule '{rule.name}': no evidence available, score=0.0"
    return (
        f"Rule '{rule.name}': score={score:.2f} from {len(refs)} evidence "
        f"item(s) ({rule.description})"
    )


class RuleBasedMasteryProvider(AbstractMasteryProvider):
    """Deterministic, explainable rule-based mastery assessment.

    Uses declarative rules to assess mastery from LearningEvidence.
    Every result includes evidence references and rule-level explanations.

    This is the GOLD-COMPARABLE baseline: its results can be compared
    against advanced providers (BKT, IRT, DKT) to validate improvements.
    """

    def __init__(
        self,
        name: str = "rule_based",
        version: str = "1.0.0",
        course_rule_set: Optional[MasteryRuleSet] = None,
        node_rule_set: Optional[MasteryRuleSet] = None,
    ):
        super().__init__(name=name, version=version)
        self._course_rule_set = course_rule_set or DEFAULT_COURSE_RULES
        self._node_rule_set = node_rule_set or DEFAULT_NODE_RULES

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self._name,
            version=self._version,
            supports_course_level=True,
            supports_node_level=True,
            requires_evidence=True,
            requires_historical_data=False,
            timeout_seconds=5.0,
        )

    def compute(
        self,
        student_id: int,
        course_id: int,
        node_id: Optional[int] = None,
        evidence_refs: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Compute mastery using the rule-based approach.

        Parameters
        ----------
        student_id : int
            The student user ID.
        course_id : int
            The course ID.
        node_id : int or None
            Optional node-level scope.
        evidence_refs : list of str or None
            Not used directly by rule-based (it reads from evidence_dict
            in metadata). Included for protocol compatibility.
        metadata : dict or None
            Must contain ``evidence_dict`` mapping evidence type strings
            to lists of evidence dicts.

        Returns
        -------
        MasteryProviderResult
        """
        meta = metadata or {}
        evidence_dict: Dict[str, List[Dict[str, Any]]] = meta.get(
            "evidence_dict", {}
        )

        # Check for no-evidence case
        all_evidence = [
            ev
            for ev_list in evidence_dict.values()
            for ev in ev_list
        ]
        if not all_evidence:
            return MasteryProviderResult.business_failure_result(
                provider_name=self._name,
                student_id=student_id,
                course_id=course_id,
                code="NO_EVIDENCE",
                message="No evidence available to compute mastery",
                details={"node_id": node_id},
            )

        if node_id is not None:
            result = _compute_node_mastery(evidence_dict, self._node_rule_set, node_id)
        else:
            result = _compute_course_mastery(evidence_dict, self._course_rule_set)

        # Patch student_id and course_id
        result_dict = result.to_dict()
        result_dict["student_id"] = student_id
        result_dict["course_id"] = course_id
        result_dict["node_id"] = node_id

        return MasteryProviderResult(
            provider_name=result_dict["provider_name"],
            provider_version=result_dict["provider_version"],
            student_id=result_dict["student_id"],
            course_id=result_dict["course_id"],
            node_id=result_dict["node_id"],
            mastery_score=result_dict["mastery_score"],
            mastery_level=result_dict["mastery_level"],
            confidence=result_dict["confidence"],
            evidence_refs=result_dict["evidence_refs"],
            error=None,
            is_timeout=False,
            is_malformed=False,
            is_business_failure=False,
            metadata=result_dict["metadata"],
        )
