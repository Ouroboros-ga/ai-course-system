"""Pure TeachingAgent constraint resolution and immutable platform floors.

This module deliberately has no database, request or runtime dependencies.  It
turns a versioned teacher policy snapshot into the single envelope that all
downstream nodes must consume for the duration of one run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from app.schemas.teaching_constraint import (
    TeachingConstraintEnvelope,
    TeachingConstraintParameterOverrides,
    TeachingConstraintParameters,
    TeachingConstraintProfile,
    TeachingConstraintRule,
    TeachingConstraintSnapshot,
)


ALL_SCOPES = ("evidence", "response", "context", "tools", "actions")

_LEVEL_ORDER = {"flexible": 0, "balanced": 1, "strict": 2, "locked": 3}
_EVIDENCE_ORDER = {"best_effort": 0, "course_grounded": 1, "course_only": 2}
_GUIDANCE_ORDER = {"direct_guided": 0, "guided": 1, "socratic": 2}
_CONFIRMATION_ORDER = {"high_risk": 0, "medium_and_high": 1, "all_actions": 2}

_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "flexible": {
        "max_context_chars": 16_000,
        "max_answer_chars": 2_400,
        "max_evidence": 12,
        "min_course_evidence": 0,
        "evidence_mode": "best_effort",
        "guidance_mode": "direct_guided",
        "confirmation_mode": "high_risk",
        "external_research": "tool_policy",
        "require_citations": True,
    },
    "balanced": {
        "max_context_chars": 12_000,
        "max_answer_chars": 1_800,
        "max_evidence": 8,
        "min_course_evidence": 1,
        "evidence_mode": "course_grounded",
        "guidance_mode": "guided",
        "confirmation_mode": "high_risk",
        "external_research": "tool_policy",
        "require_citations": True,
    },
    "strict": {
        "max_context_chars": 8_000,
        "max_answer_chars": 1_200,
        "max_evidence": 6,
        "min_course_evidence": 1,
        "evidence_mode": "course_grounded",
        "guidance_mode": "guided",
        "confirmation_mode": "medium_and_high",
        "external_research": "disabled",
        "require_citations": True,
    },
    "locked": {
        "max_context_chars": 6_000,
        "max_answer_chars": 900,
        "max_evidence": 4,
        "min_course_evidence": 1,
        "evidence_mode": "course_only",
        "guidance_mode": "socratic",
        "confirmation_mode": "all_actions",
        "external_research": "disabled",
        "require_citations": True,
    },
}


@dataclass(frozen=True, slots=True)
class ConstraintSubject:
    """Server-derived selectors; callers must not trust student-supplied groups."""

    student_id: str
    group_ids: tuple[str, ...] = ()
    intent: str | None = None
    concept_id: str | None = None


def _merge_parameters(
    level: str,
    overrides: TeachingConstraintParameterOverrides | Mapping[str, Any] | None,
) -> TeachingConstraintParameters:
    values = dict(_PROFILE_DEFAULTS[level])
    if overrides is not None:
        if isinstance(overrides, TeachingConstraintParameterOverrides):
            override_values = overrides.model_dump(exclude_none=True)
        else:
            override_values = {key: value for key, value in overrides.items() if value is not None}
        values.update(override_values)
    return TeachingConstraintParameters.model_validate(values)


def _canonical_profile(profile: TeachingConstraintProfile) -> TeachingConstraintProfile:
    # Keep the stored shape sparse but round-trip every value through the bounded
    # full contract so malformed overrides cannot reach the resolver.
    bounded = _merge_parameters(profile.level, profile.parameters)
    return TeachingConstraintProfile(
        level=profile.level,
        scopes=profile.scopes,
        parameters=TeachingConstraintParameterOverrides.model_validate(
            bounded.model_dump()
        ),
    )


def canonicalize_snapshot(
    payload: TeachingConstraintSnapshot | Mapping[str, Any],
) -> TeachingConstraintSnapshot:
    """Normalize shorthand editor payloads into the versioned snapshot contract."""

    if isinstance(payload, TeachingConstraintSnapshot):
        parsed = payload
    else:
        raw = dict(payload)
        if "baseline" not in raw:
            allowed = {"level", "scopes", "parameters", "rules"}
            unknown = set(raw) - allowed
            if unknown:
                # Reuse Pydantic's fail-closed extra-field reporting.
                TeachingConstraintSnapshot.model_validate(raw)
            raw = {
                "baseline": {
                    "level": raw.get("level", "balanced"),
                    "scopes": raw.get("scopes", ALL_SCOPES),
                    "parameters": raw.get("parameters", {}),
                },
                "rules": raw.get("rules", ()),
            }
        parsed = TeachingConstraintSnapshot.model_validate(raw)

    baseline = _canonical_profile(parsed.baseline)
    canonical_rules: list[TeachingConstraintRule] = []
    for rule in parsed.rules:
        bounded = _merge_parameters(rule.level, rule.parameters)
        canonical_rules.append(
            rule.model_copy(
                update={
                    "scopes": rule.scopes or baseline.scopes,
                    "parameters": TeachingConstraintParameterOverrides.model_validate(
                        bounded.model_dump()
                    ),
                }
            )
        )
    return parsed.model_copy(update={"baseline": baseline, "rules": tuple(canonical_rules)})


def _stricter(current: str, floor: str, order: Mapping[str, int]) -> str:
    return current if order[current] >= order[floor] else floor


def apply_platform_floor(
    *,
    level: str,
    scopes: tuple[str, ...],
    parameters: TeachingConstraintParameters,
    matched_rule_ids: tuple[str, ...] = (),
) -> TeachingConstraintEnvelope:
    """Enforce safety invariants that teacher policy is never allowed to relax."""

    values = parameters.model_dump()
    disabled_tools: set[str] = set()
    decisions = ["PLATFORM_FLOOR_APPLIED"]

    # Every level preserves course-fact provenance and confirmation for risky
    # actions; stricter levels additionally reduce open-ended agent behavior.
    values["confirmation_mode"] = _stricter(
        values["confirmation_mode"], "high_risk", _CONFIRMATION_ORDER
    )
    values["require_citations"] = True

    if level in {"strict", "locked"}:
        values["external_research"] = "disabled"
        values["evidence_mode"] = _stricter(
            values["evidence_mode"], "course_grounded", _EVIDENCE_ORDER
        )
        values["guidance_mode"] = _stricter(
            values["guidance_mode"], "guided", _GUIDANCE_ORDER
        )
        values["min_course_evidence"] = max(values["min_course_evidence"], 1)
        disabled_tools.add("web_research")
    if level == "locked":
        values["evidence_mode"] = "course_only"
        values["guidance_mode"] = "socratic"
        values["confirmation_mode"] = "all_actions"
        disabled_tools.update({"question_generation", "web_research"})

    return TeachingConstraintEnvelope(
        level=level,
        scopes=scopes,
        parameters=TeachingConstraintParameters.model_validate(values),
        disabled_tools=tuple(sorted(disabled_tools)),
        matched_rule_ids=matched_rule_ids,
        decision_codes=tuple(decisions),
    )


def _is_active(rule: TeachingConstraintRule, now: datetime) -> bool:
    if rule.effective_from is not None and now < rule.effective_from:
        return False
    if rule.effective_until is not None and now >= rule.effective_until:
        return False
    return True


def _matches(rule: TeachingConstraintRule, subject: ConstraintSubject, now: datetime) -> bool:
    if not _is_active(rule, now):
        return False
    if rule.target_type == "student" and rule.target_id != subject.student_id:
        return False
    if rule.target_type == "group" and rule.target_id not in subject.group_ids:
        return False
    if rule.intent is not None and rule.intent != subject.intent:
        return False
    if rule.concept_id is not None and rule.concept_id != subject.concept_id:
        return False
    return True


def _specificity(rule: TeachingConstraintRule) -> tuple[int, int, int]:
    return (
        1 if rule.target_type == "student" else 0,
        1 if rule.concept_id is not None else 0,
        1 if rule.intent is not None else 0,
    )


def resolve_effective_constraint(
    *,
    snapshot: TeachingConstraintSnapshot | Mapping[str, Any],
    subject: ConstraintSubject,
    now: datetime | None = None,
) -> TeachingConstraintEnvelope:
    """Resolve one deterministic envelope using priority and stable tie-breaks."""

    canonical = canonicalize_snapshot(snapshot)
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.utcoffset() is None:
        raise ValueError("constraint resolution time must be timezone-aware")

    candidates = [rule for rule in canonical.rules if _matches(rule, subject, resolved_now)]
    candidates.sort(
        key=lambda rule: (
            -rule.priority,
            tuple(-value for value in _specificity(rule)),
            -_LEVEL_ORDER[rule.level],
            rule.rule_id,
        )
    )

    if candidates:
        selected = candidates[0]
        level = selected.level
        scopes = selected.scopes or canonical.baseline.scopes
        parameters = _merge_parameters(level, selected.parameters)
        matched = (selected.rule_id,)
    else:
        level = canonical.baseline.level
        scopes = canonical.baseline.scopes
        parameters = _merge_parameters(level, canonical.baseline.parameters)
        matched = ()

    return apply_platform_floor(
        level=level,
        scopes=tuple(scopes),
        parameters=parameters,
        matched_rule_ids=matched,
    )


__all__ = [
    "ALL_SCOPES",
    "ConstraintSubject",
    "apply_platform_floor",
    "canonicalize_snapshot",
    "resolve_effective_constraint",
]
