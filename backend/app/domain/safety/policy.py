"""
SafetyPolicy and PolicySet: platform-level and course-level policy containers.

Platform policies cannot be overridden by course-level policies.
Rule conflict resolution uses priority and a configurable strategy.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .rules import BaseRule, KeywordRule, RegexRule, RuleAction


class RuleConflictStrategy(str, enum.Enum):
    """How to resolve when multiple rules match the same content."""

    MOST_RESTRICTIVE = "most_restrictive"
    """Pick the most restrictive action (DENY > RESTRICT > REQUIRE_CITATION > HOMEWORK_ANSWER)."""

    HIGHEST_PRIORITY = "highest_priority"
    """Pick the rule with the highest priority value."""

    PLATFORM_OVERRIDES = "platform_overrides"
    """Platform rules always win; course rules only apply if no platform rule matches."""


# Severity ordering: higher index = more restrictive
_ACTION_SEVERITY: Dict[RuleAction, int] = {
    RuleAction.DENY: 4,
    RuleAction.RESTRICT: 3,
    RuleAction.REQUIRE_CITATION: 2,
    RuleAction.HOMEWORK_ANSWER: 1,
}


@dataclass(frozen=True)
class SafetyPolicy:
    """A named collection of safety rules.

    Parameters
    ----------
    policy_id : str
        Stable identifier (e.g., ``platform-input-policy``).
    rules : list of BaseRule
        The rules in this policy.
    conflict_strategy : RuleConflictStrategy
        How to resolve conflicts within this policy.
    description : str
        Human-readable description.
    """

    policy_id: str
    rules: List[BaseRule] = field(default_factory=list)
    conflict_strategy: RuleConflictStrategy = RuleConflictStrategy.PLATFORM_OVERRIDES
    description: str = ""

    def evaluate(self, text: str) -> List[BaseRule]:
        """Evaluate all enabled rules against text, return matching rules."""
        return [r for r in self.rules if r.enabled and r.matches(text)]

    def resolve(self, matched_rules: List[BaseRule]) -> Optional[RuleAction]:
        """Resolve a set of matched rules to a single action.

        Returns ``None`` if no rules matched.
        """
        if not matched_rules:
            return None

        if self.conflict_strategy == RuleConflictStrategy.HIGHEST_PRIORITY:
            best = max(matched_rules, key=lambda r: r.priority)
            return best.action

        if self.conflict_strategy == RuleConflictStrategy.MOST_RESTRICTIVE:
            actions = {r.action for r in matched_rules}
            best_action = max(actions, key=lambda a: _ACTION_SEVERITY.get(a, 0))
            return best_action

        # PLATFORM_OVERRIDES: platform rules first
        platform = [r for r in matched_rules if r.is_platform_rule]
        if platform:
            return max(
                platform, key=lambda r: _ACTION_SEVERITY.get(r.action, 0)
            ).action
        course = [r for r in matched_rules if not r.is_platform_rule]
        if course:
            return max(
                course, key=lambda r: _ACTION_SEVERITY.get(r.action, 0)
            ).action
        return None

    def to_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "rules": [r.to_dict() for r in self.rules],
            "conflict_strategy": self.conflict_strategy.value,
            "description": self.description,
        }


@dataclass
class PolicySet:
    """A complete set of policies for a course context.

    Contains one platform policy and zero or more course-level policies.
    Platform policy rules always take precedence over course-level rules.

    Parameters
    ----------
    platform_policy : SafetyPolicy
        The immutable platform-level policy.
    course_policies : list of SafetyPolicy
        Course-level policies that can be enabled/disabled by the teacher.
    """

    platform_policy: SafetyPolicy
    course_policies: List[SafetyPolicy] = field(default_factory=list)

    def get_all_rules(self) -> List[BaseRule]:
        """Return all enabled rules across all policies.

        Platform rules are returned first; course rules follow.
        """
        rules: List[BaseRule] = list(self.platform_policy.rules)
        for cp in self.course_policies:
            rules.extend(cp.rules)
        return rules

    def evaluate_all(self, text: str) -> List[BaseRule]:
        """Evaluate text against all policies and return matched rules.

        If a platform rule matches, course rules for the same input are
        still evaluated but the platform rule's action dominates in
        PLATFORM_OVERRIDES strategy.
        """
        matched: List[BaseRule] = []

        # Always evaluate platform rules
        platform_matched = self.platform_policy.evaluate(text)
        matched.extend(platform_matched)

        # Evaluate course rules
        for cp in self.course_policies:
            matched.extend(cp.evaluate(text))

        return matched

    def resolve_all(self, matched_rules: List[BaseRule]) -> Optional[RuleAction]:
        """Resolve matched rules using platform-overrides strategy.

        Platform rules always win regardless of course-level rules.
        """
        if not matched_rules:
            return None

        platform = [r for r in matched_rules if r.is_platform_rule]
        if platform:
            return max(
                platform, key=lambda r: _ACTION_SEVERITY.get(r.action, 0)
            ).action

        course = [r for r in matched_rules if not r.is_platform_rule]
        if course:
            return max(
                course, key=lambda r: _ACTION_SEVERITY.get(r.action, 0)
            ).action
        return None

    def to_dict(self) -> dict:
        return {
            "platform_policy": self.platform_policy.to_dict(),
            "course_policies": [cp.to_dict() for cp in self.course_policies],
        }


def PlatformPolicy() -> SafetyPolicy:
    """Create the default platform-level safety policy.

    This policy cannot be disabled by course-level rules.
    """
    rules: List[BaseRule] = [
        KeywordRule(
            rule_id="platform-keyword-block-001",
            action=RuleAction.DENY,
            description="Block requests containing personally identifiable information patterns",
            is_platform_rule=True,
            priority=100,
            keywords=(
                "身份证号", "手机号码", "银行卡号",
                "id_number", "phone_number", "bank_card",
            ),
        ),
        KeywordRule(
            rule_id="platform-keyword-homework-001",
            action=RuleAction.HOMEWORK_ANSWER,
            description="Flag known homework-direct-answer keywords",
            is_platform_rule=True,
            priority=90,
            keywords=(
                "直接给答案", "直接告诉我答案", "作业答案",
                "give me the answer", "homework answer",
            ),
        ),
        RegexRule(
            rule_id="platform-regex-pii-001",
            action=RuleAction.DENY,
            description="Block patterns matching common PII (phone, email, ID)",
            is_platform_rule=True,
            priority=95,
            pattern=r"\b1[3-9]\d{9}\b",  # Chinese mobile
            match_type="search",
        ),
    ]
    return SafetyPolicy(
        policy_id="platform-default",
        rules=rules,
        conflict_strategy=RuleConflictStrategy.PLATFORM_OVERRIDES,
        description="Platform-mandated safety policy that cannot be overridden",
    )
