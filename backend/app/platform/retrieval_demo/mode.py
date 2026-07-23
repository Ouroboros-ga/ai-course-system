"""Fail-closed runtime gate for the user-visible retrieval demonstration."""

from __future__ import annotations

from dataclasses import dataclass


DEMO_RETRIEVAL_MODES = ("v1_only", "demo_shadow_visible", "demo_compare")
DEMO_VISIBLE_ENVIRONMENTS = ("development", "demo", "test")
# R3 was evaluated offline and did not improve R2.  It is deliberately not
# configurable in the test/production candidate path; graph visualization may
# remain available, but graph expansion may not influence retrieval.
GRAPH_EXPANSION_PRODUCTION_CANDIDATE_ENABLED = False


@dataclass(frozen=True)
class DemoModeState:
    configured_mode: str
    effective_mode: str
    enabled: bool
    reason: str | None = None


def resolve_demo_mode(*, configured_mode: str, environment: str, runtime_override: str | None = None) -> DemoModeState:
    """Resolve the demo mode without altering any V1 feature flag.

    A visible mode is deliberately unavailable outside a local development,
    demo, or test environment.  The process-local rollback override can only
    reduce the feature to ``v1_only``; it cannot promote a disabled demo.
    """
    if configured_mode not in DEMO_RETRIEVAL_MODES:
        raise ValueError(f"unsupported demo retrieval mode: {configured_mode}")
    effective = runtime_override or configured_mode
    if effective not in DEMO_RETRIEVAL_MODES:
        raise ValueError(f"unsupported demo retrieval override: {effective}")
    if effective == "v1_only":
        return DemoModeState(configured_mode, effective, False, "demo_mode_v1_only")
    if environment not in DEMO_VISIBLE_ENVIRONMENTS:
        return DemoModeState(configured_mode, "v1_only", False, "environment_not_demo_safe")
    return DemoModeState(configured_mode, effective, True)
