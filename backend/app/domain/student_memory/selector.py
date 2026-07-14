"""
MemoryContext selector: token-budgeted context selection for QA injection.

Selects memory entries within a token budget, prioritizing by confidence,
recency, and relevance. Returns a MemoryContext ready for prompt injection.

When memory is disabled, returns an empty MemoryContext (no read).
Free-form chat summaries MUST NOT be written directly into long-term memory.

Version: 1.0 (draft)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol

from app.domain.student_memory.enums import LifecycleState, MemoryType
from app.domain.student_memory.models import (
    MemoryContext,
    MemoryEntry,
    StudentProfile,
    TeachingStrategy,
)

# Rough token estimation: ~4 chars per token for Chinese/English mixed text
_CHARS_PER_TOKEN = 4.0


def _estimate_tokens(text: str) -> int:
    """Rough token estimation for a text string."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _entry_token_cost(entry: MemoryEntry) -> int:
    """Estimate token cost of including a MemoryEntry in context."""
    cost = _estimate_tokens(entry.content)
    cost += _estimate_tokens(entry.generation_reason)
    cost += len(entry.evidence_refs) * 10  # evidence ref overhead
    cost += 50  # entry wrapper overhead
    return cost


class MemorySelector(Protocol):
    """Protocol for memory context selection."""

    def select_context(
        self,
        student_id: int,
        course_id: int,
        entries: List[MemoryEntry],
        profile: Optional[StudentProfile],
        strategies: List[TeachingStrategy],
        budget_tokens: int = 1024,
    ) -> MemoryContext:
        """Select and prioritize memory entries within a token budget.

        Parameters
        ----------
        student_id : int
            The student user ID.
        course_id : int
            The course ID.
        entries : list of MemoryEntry
            All readable memory entries for this scope.
        profile : StudentProfile or None
            The student profile (may be None).
        strategies : list of TeachingStrategy
            Teaching strategies for this scope.
        budget_tokens : int
            Maximum token budget for the context (default 1024).

        Returns
        -------
        MemoryContext
            The selected context within budget.
        """
        ...


def _priority_score(entry: MemoryEntry) -> float:
    """Compute a priority score for sorting memory entries.

    Higher score = higher priority for inclusion.

    Factors:
    - confidence (0-1)
    - lifecycle state: ACTIVE = 1.0, EXPIRING = 0.5, others = 0.0
    - memory type bonus: STRATEGY, GAP, STRENGTH get +0.2
    """
    score = entry.confidence

    if entry.lifecycle_state == LifecycleState.ACTIVE:
        score += 0.0  # baseline
    elif entry.lifecycle_state == LifecycleState.EXPIRING:
        score *= 0.5
    else:
        score = 0.0  # not selectable

    # Type-based bonus
    if entry.memory_type in (
        MemoryType.GAP,
        MemoryType.STRENGTH,
        MemoryType.STRATEGY,
    ):
        score += 0.2

    return max(0.0, min(1.5, score))


def select_context(
    student_id: int,
    course_id: int,
    entries: List[MemoryEntry],
    profile: Optional[StudentProfile],
    strategies: List[TeachingStrategy],
    budget_tokens: int = 1024,
) -> MemoryContext:
    """Default MemorySelector implementation.

    Selects entries within budget, prioritizing by priority score.
    Strategies are included if budget remains after entries and profile.
    """
    # Filter to only readable, non-expired entries
    readable = [
        e for e in entries
        if e.lifecycle_state == LifecycleState.ACTIVE
    ]

    # Sort by priority score descending
    sorted_entries = sorted(
        readable, key=_priority_score, reverse=True
    )

    selected: List[MemoryEntry] = []
    total_tokens = 0
    truncated = False

    # Reserve tokens for profile
    profile_tokens = 0
    include_profile = profile is not None
    if include_profile:
        profile_tokens = _estimate_tokens(profile.known_background or "")
        profile_tokens += len(profile.goals) * 15
        profile_tokens += len(profile.accommodations) * 10
        profile_tokens += 100  # wrapper overhead

    # Reserve tokens for strategies (one strategy intro)
    strategy_tokens = 0
    include_strategies = bool(strategies)
    if include_strategies:
        strategy_tokens = 200  # rough budget for top strategies

    remaining = budget_tokens - profile_tokens - strategy_tokens

    for entry in sorted_entries:
        cost = _entry_token_cost(entry)
        if total_tokens + cost <= remaining:
            selected.append(entry)
            total_tokens += cost
        else:
            truncated = True
            break

    total_context_tokens = total_tokens + profile_tokens + strategy_tokens
    actual_truncated = truncated or (
        len(sorted_entries) > len(selected)
    )

    return MemoryContext(
        student_id=student_id,
        course_id=course_id,
        entries=selected,
        profile=profile if include_profile else None,
        strategies=strategies if include_strategies else [],
        total_tokens=total_context_tokens,
        budget_tokens=budget_tokens,
        truncated=actual_truncated,
    )
