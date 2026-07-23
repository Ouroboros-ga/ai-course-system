"""Explicit promotion gate from cognition research to read-only Shadow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ShadowGateInput:
    research_tests_passed: bool
    contract_ablation_passed: bool
    graph_snapshot_status: str
    graph_course_isolation_verified: bool
    interaction_gold_status: str
    privacy_review_status: str
    provider_contract_tests_passed: bool
    append_only_audit_verified: bool
    no_production_write_verified: bool


REQUIRED = {
    "graph_snapshot_status": "accepted",
    "interaction_gold_status": "approved_protected_gold",
    "privacy_review_status": "approved",
}


def evaluate_shadow_gate(inputs: ShadowGateInput) -> Mapping[str, object]:
    failures: list[str] = []
    for field, expected in REQUIRED.items():
        if getattr(inputs, field) != expected:
            failures.append(f"{field.upper()}_REQUIRED")
    for field in (
        "research_tests_passed",
        "contract_ablation_passed",
        "graph_course_isolation_verified",
        "provider_contract_tests_passed",
        "append_only_audit_verified",
        "no_production_write_verified",
    ):
        if not getattr(inputs, field):
            failures.append(f"{field.upper()}_REQUIRED")
    return {
        "status": "ready_for_shadow" if not failures else "not_ready",
        "error_codes": tuple(sorted(failures)),
        "promotion": "read_only_shadow" if not failures else None,
    }
