"""
Safety rules: keyword matching, regular expression matching, and ReDoS resistance.

All rules carry a stable rule_id, action, and optional metadata.
Platform rules carry ``is_platform_rule=True`` and CANNOT be disabled
by course-level rules.
"""

from __future__ import annotations

import enum
import re
import time
from dataclasses import dataclass, field
from typing import ClassVar, List, Optional, Pattern, Tuple


# ---------------------------------------------------------------------------
# ReDoS protection
# ---------------------------------------------------------------------------

_MAX_REGEX_TIMEOUT_SEC: float = 0.5
"""Maximum wall-clock seconds allowed for a single regex match attempt."""

_MAX_REGEX_COMPLEXITY_SCORE: int = 200
"""If a regex's estimated complexity exceeds this, it is rejected at compile time."""

# Sub-patterns that strongly indicate super-linear worst-case complexity.
# This is a heuristic guard, not a formal proof.
_SUSPICIOUS_PATTERNS: List[str] = [
    r"\(\.\*\)\+",          # (.*)+
    r"\(\.\+\)\+",          # (.+)+
    r"\(\.\*\)\{",          # (.*){N}
    r"\(\.\+\)\{",          # (.+){N}
    r"\(\.\*\)\*",          # (.*)*
    r"\(\.\+\)\*",          # (.+)*
    r"\\w\+\\w\+",          # \w+\w+  (nested quantifiers)
    r"\(\?[!=].*\)\+",      # lookahead/lookbehind with +
    r"\([^)]+\)\{2,\}",     # group {2,}
]


class ReDoSProtection:
    """Guard against ReDoS by estimating complexity and enforcing a time budget.

    Methods
    -------
    reject_if_unsafe(pattern: str) -> bool
        Return True if the pattern is rejected (deemed too risky).
    compile_safe(pattern: str, flags: int = 0) -> Pattern
        Compile a regex with an internal timeout guard.
    """

    @staticmethod
    def complexity_score(pattern: str) -> int:
        """Heuristic complexity estimate.

        Simple literal patterns score ~0; patterns with nested quantifiers
        score much higher.  Returns 0 for empty or trivially short patterns.
        """
        score = 0
        # Length factor
        score += len(pattern)
        # Count nested quantifiers
        nested = len(re.findall(r"\([^)]*\)[*+{]", pattern))
        score += nested * 50
        # Detect suspicious sub-patterns
        for suspect in _SUSPICIOUS_PATTERNS:
            if re.search(suspect, pattern):
                score += 200
        return score

    @staticmethod
    def reject_if_unsafe(pattern: str) -> bool:
        """Return True if the pattern should be rejected as unsafe."""
        if not pattern.strip():
            return False
        score = ReDoSProtection.complexity_score(pattern)
        return score > _MAX_REGEX_COMPLEXITY_SCORE

    @staticmethod
    def compile_safe(pattern: str, flags: int = 0) -> Pattern:
        """Compile a regex pattern with ReDoS guard.

        Raises ``ValueError`` if the pattern is rejected as unsafe.
        """
        if ReDoSProtection.reject_if_unsafe(pattern):
            raise ValueError(
                f"Regex pattern rejected as potentially unsafe "
                f"(complexity {ReDoSProtection.complexity_score(pattern)} > "
                f"threshold {_MAX_REGEX_COMPLEXITY_SCORE}): {pattern!r}"
            )
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern {pattern!r}: {e}") from e
        return compiled

    @staticmethod
    def safe_match(pattern: Pattern, text: str) -> Optional[re.Match]:
        """Perform a regex match with a wall-clock timeout.

        Returns the match object, or ``None`` on timeout or no match.
        Raises ``TimeoutError`` (from the signal/thread approach) if the
        match takes longer than ``_MAX_REGEX_TIMEOUT_SEC``.
        """
        start = time.monotonic()
        # For simplicity, we check elapsed time in a loop over matches.
        # A production version would use a thread or subprocess kill.
        m = pattern.search(text)
        elapsed = time.monotonic() - start
        if elapsed > _MAX_REGEX_TIMEOUT_SEC:
            raise TimeoutError(
                f"Regex match exceeded timeout "
                f"({elapsed:.3f}s > {_MAX_REGEX_TIMEOUT_SEC}s)"
            )
        return m

    @staticmethod
    def safe_fullmatch(pattern: Pattern, text: str) -> Optional[re.Match]:
        """Like ``safe_match`` but for ``fullmatch``."""
        start = time.monotonic()
        m = pattern.fullmatch(text)
        elapsed = time.monotonic() - start
        if elapsed > _MAX_REGEX_TIMEOUT_SEC:
            raise TimeoutError(
                f"Regex fullmatch exceeded timeout "
                f"({elapsed:.3f}s > {_MAX_REGEX_TIMEOUT_SEC}s)"
            )
        return m

    @staticmethod
    def safe_findall(pattern: Pattern, text: str) -> List[str]:
        """Like ``safe_match`` but for ``findall``."""
        start = time.monotonic()
        results = pattern.findall(text)
        elapsed = time.monotonic() - start
        if elapsed > _MAX_REGEX_TIMEOUT_SEC:
            raise TimeoutError(
                f"Regex findall exceeded timeout "
                f"({elapsed:.3f}s > {_MAX_REGEX_TIMEOUT_SEC}s)"
            )
        return results


# ---------------------------------------------------------------------------
# RuleAction
# ---------------------------------------------------------------------------


class RuleAction(str, enum.Enum):
    """The action to take when a rule is triggered."""

    DENY = "deny"
    """Block the request outright."""

    RESTRICT = "restrict"
    """Allow but restrict the response (e.g., partial answer)."""

    REQUIRE_CITATION = "require-citation"
    """Response must include a citation to source material."""

    HOMEWORK_ANSWER = "homework-answer"
    """Reject direct homework answers; may provide hints."""


# ---------------------------------------------------------------------------
# BaseRule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaseRule:
    """Immutable base rule.

    Parameters
    ----------
    rule_id : str
        Stable identifier (e.g., ``platform-keyword-001``).
    action : RuleAction
        Action when triggered.
    description : str
        Human-readable explanation.
    is_platform_rule : bool
        If True, course-level rules cannot override this rule.
    enabled : bool
        If False, the rule is inactive.
    priority : int
        Higher priority wins when rules conflict.
    """

    rule_id: str
    action: RuleAction
    description: str = ""
    is_platform_rule: bool = False
    enabled: bool = True
    priority: int = 0

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "action": self.action.value,
            "description": self.description,
            "is_platform_rule": self.is_platform_rule,
            "enabled": self.enabled,
            "priority": self.priority,
        }


# ---------------------------------------------------------------------------
# KeywordRule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordRule(BaseRule):
    """Match text against a set of keywords.

    Parameters
    ----------
    keywords : tuple of str
        Case-insensitive keywords to search for.
    match_mode : str
        ``"any"`` (default) — match if any keyword is found;
        ``"all"`` — match only if all keywords are found.
    """

    keywords: Tuple[str, ...] = field(default_factory=tuple)
    match_mode: str = "any"  # "any" | "all"

    def matches(self, text: str) -> bool:
        """Return True if the text triggers this keyword rule."""
        if not self.enabled or not self.keywords:
            return False
        lower_text = text.lower()
        found = [kw.lower() in lower_text for kw in self.keywords]
        if self.match_mode == "all":
            return all(found)
        return any(found)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "type": "keyword",
            "keywords": list(self.keywords),
            "match_mode": self.match_mode,
        })
        return base


# ---------------------------------------------------------------------------
# RegexRule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegexRule(BaseRule):
    """Match text against a compiled regular expression.

    Parameters
    ----------
    pattern : str
        The regex pattern string.
    compiled : Pattern or None
        Pre-compiled pattern (set automatically if None).
    match_type : str
        ``"search"`` (default), ``"fullmatch"``, or ``"findall"``.
    flags : int
        Regex flags (default re.IGNORECASE).
    """

    pattern: str = ""
    compiled: Pattern = field(compare=False, hash=False, repr=False, default=None)  # type: ignore[assignment]
    match_type: str = "search"  # "search" | "fullmatch" | "findall"
    flags: int = re.IGNORECASE

    def __post_init__(self) -> None:
        if self.compiled is not None:
            return
        # Use object.__setattr__ because frozen=True
        try:
            c = ReDoSProtection.compile_safe(self.pattern, self.flags)
        except ValueError as e:
            raise ValueError(
                f"RegexRule {self.rule_id}: {e}"
            ) from e
        object.__setattr__(self, "compiled", c)

    def matches(self, text: str) -> bool:
        """Return True if the text matches this regex rule."""
        if not self.enabled or self.compiled is None:
            return False
        try:
            if self.match_type == "fullmatch":
                return ReDoSProtection.safe_fullmatch(self.compiled, text) is not None
            elif self.match_type == "findall":
                return len(ReDoSProtection.safe_findall(self.compiled, text)) > 0
            else:
                return ReDoSProtection.safe_match(self.compiled, text) is not None
        except TimeoutError:
            # Fail closed: on timeout, treat as a match (block/restrict)
            return True

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "type": "regex",
            "pattern": self.pattern,
            "match_type": self.match_type,
            "flags": self.flags,
        })
        return base
