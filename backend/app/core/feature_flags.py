"""Product 1 V2 shadow feature flags (G3A).

Defines the 7 Product 1 feature flags, their valid G3 values, the
dependency/conflict rules between aggregate and module flags, and the
two-layer error handling mandated by ADR-0006 (Accepted-G3A-only):

1. Configuration invalid (value not in the legal set): STARTUP FAIL-FAST.
   ``app.core.config.Settings`` construction raises ``ValidationError``,
   so the application refuses to start. This is NOT a silent fallback -
   operators must fix the typo (e.g. ``v2_shdaow``) before the app runs.

2. Shadow runtime error (valid config, V2 execution fails at runtime):
   BUSINESS FAIL-CLOSED. The effective mode downgrades to ``v1_only`` /
   ``disabled`` and a ``fallback_reason`` is recorded, so V1 behavior is
   preserved while operators can see why shadow did not run.

G3 legal values: ONLY ``v1_only`` / ``v2_shadow`` for pipeline flags, and
``disabled`` / ``shadow`` for toggle flags. ``v2_preferred_with_v1_fallback``
and ``v2_only`` are NOT legal in G3 (reserved for G6); setting them is a
configuration error and fails fast.

Conflict rule (aggregate vs module)
-----------------------------------
A module flag can only run in its V2/shadow state if its upstream
aggregate (or parent module) flag is ALSO effectively in V2/shadow
state. If the upstream is ``v1_only`` / ``disabled``, the module flag is
downgraded to its V1/disabled baseline with a ``fallback_reason``,
because running V2 shadow on V1 data would be meaningless or unsafe.
Independent root flags are never downgraded by conflict (only by their
own runtime errors).

Dependency graph
----------------
::

    DOCUMENT_PIPELINE_VERSION (root aggregate: doc parse, P1-01/02)
      -> DOCUMENT_KG_RUNTIME_MODE (runtime: retrieval+graph)
           -> EVIDENCE_CITATION_MODE (P1-03)
           -> KNOWLEDGE_GRAPH_PIPELINE_VERSION (P1-05)

    LEARNING_EVENT_MODE (root independent, P1-07)
      -> STUDENT_MEMORY_MODE (P1-06)

    SAFETY_GOVERNANCE_MODE (root independent, P1-08)

Memory/learning/safety are independent of the document aggregate per
ADR-0006 §3 (not bundled with DOCUMENT_PIPELINE_VERSION).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Legal G3 values
# ---------------------------------------------------------------------------

PIPELINE_MODES: tuple = ("v1_only", "v2_shadow")
"""Legal values for pipeline flags."""

TOGGLE_MODES: tuple = ("disabled", "shadow")
"""Legal values for toggle flags."""

# Values explicitly reserved for G6 - NOT legal in G3.
G6_RESERVED: tuple = ("v2_preferred_with_v1_fallback", "v2_only")


# TeachingAgent enable flag (independent of the 7-flag Product 1 DAG).
# ADR-0006 §3: the controlled LangGraph teaching workflow is intentionally
# NOT bundled with DOCUMENT_PIPELINE_VERSION. It has its own opt-in toggle
# and is deliberately excluded from FLAG_KINDS / LEGAL_VALUES / ALL_FLAGS so
# the 7-flag dependency resolver (resolve_effective_modes) never touches it.
TEACHING_AGENT_MODE = "TEACHING_AGENT_MODE"
TEACHING_AGENT_MODES: tuple = ("disabled", "enabled")
"""Legal values for the TeachingAgent enable flag. Default ``disabled`` keeps
the ``/api/v1/teaching-agent/respond`` endpoint at 503 (runtime not injected)."""


# ---------------------------------------------------------------------------
# Flag names and kinds
# ---------------------------------------------------------------------------

DOCUMENT_PIPELINE_VERSION = "DOCUMENT_PIPELINE_VERSION"
DOCUMENT_KG_RUNTIME_MODE = "DOCUMENT_KG_RUNTIME_MODE"
EVIDENCE_CITATION_MODE = "EVIDENCE_CITATION_MODE"
KNOWLEDGE_GRAPH_PIPELINE_VERSION = "KNOWLEDGE_GRAPH_PIPELINE_VERSION"
LEARNING_EVENT_MODE = "LEARNING_EVENT_MODE"
STUDENT_MEMORY_MODE = "STUDENT_MEMORY_MODE"
SAFETY_GOVERNANCE_MODE = "SAFETY_GOVERNANCE_MODE"

# Kind: "pipeline" (v1_only/v2_shadow) or "toggle" (disabled/shadow)
FLAG_KINDS: Dict[str, str] = {
    DOCUMENT_PIPELINE_VERSION: "pipeline",
    DOCUMENT_KG_RUNTIME_MODE: "pipeline",
    EVIDENCE_CITATION_MODE: "pipeline",
    KNOWLEDGE_GRAPH_PIPELINE_VERSION: "pipeline",
    LEARNING_EVENT_MODE: "pipeline",
    STUDENT_MEMORY_MODE: "toggle",
    SAFETY_GOVERNANCE_MODE: "toggle",
}

# Legal values per flag (single source of truth; config.py imports this).
LEGAL_VALUES: Dict[str, tuple] = {
    name: (PIPELINE_MODES if kind == "pipeline" else TOGGLE_MODES)
    for name, kind in FLAG_KINDS.items()
}

ALL_FLAGS: List[str] = list(FLAG_KINDS.keys())


# ---------------------------------------------------------------------------
# Dependency graph: flag -> upstream flag (or None for roots)
# ---------------------------------------------------------------------------

UPSTREAM: Dict[str, Optional[str]] = {
    DOCUMENT_PIPELINE_VERSION: None,                       # root aggregate
    DOCUMENT_KG_RUNTIME_MODE: DOCUMENT_PIPELINE_VERSION,   # runtime needs V2 parsed data
    EVIDENCE_CITATION_MODE: DOCUMENT_KG_RUNTIME_MODE,      # evidence retrieval under runtime
    KNOWLEDGE_GRAPH_PIPELINE_VERSION: DOCUMENT_KG_RUNTIME_MODE,  # graph under runtime
    LEARNING_EVENT_MODE: None,                             # root independent
    STUDENT_MEMORY_MODE: LEARNING_EVENT_MODE,              # memory needs events
    SAFETY_GOVERNANCE_MODE: None,                          # root independent
}


# ---------------------------------------------------------------------------
# Effective mode (after conflict resolution)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveMode:
    """The effective mode of a flag after conflict-rule resolution.

    ``effective`` may differ from ``configured`` when:
    - a module flag's upstream is not V2/shadow (conflict downgrade), or
    - a shadow runtime error triggered business-level fail-closed
      (via ``shadow_runtime_fail_closed``).

    In both cases ``downgraded`` is True and ``fallback_reason`` explains
    why V1/disabled is running instead of the configured V2/shadow.
    """

    flag: str
    configured: str
    effective: str
    downgraded: bool = False
    fallback_reason: Optional[str] = None


def _is_v2(mode: str) -> bool:
    """True if mode is a V2/shadow state."""
    return mode in (PIPELINE_MODES[1], TOGGLE_MODES[1])  # v2_shadow / shadow


def _v1_baseline(flag: str) -> str:
    """The V1/disabled baseline for a flag (used when downgraded)."""
    if FLAG_KINDS[flag] == "toggle":
        return TOGGLE_MODES[0]  # disabled
    return PIPELINE_MODES[0]   # v1_only


def _topological_order() -> List[str]:
    """Return flag names upstream-first (roots before dependents)."""
    order: List[str] = []
    visited: set = set()

    def visit(flag: str) -> None:
        if flag in visited:
            return
        up = UPSTREAM[flag]
        if up is not None:
            visit(up)
        visited.add(flag)
        order.append(flag)

    for flag in ALL_FLAGS:
        visit(flag)
    return order


def resolve_effective_modes(configured: Dict[str, str]) -> Dict[str, EffectiveMode]:
    """Resolve effective modes for all flags given configured values.

    Applies the conflict rule: a module flag is downgraded to its V1/
    disabled baseline if its upstream flag is not effectively V2/shadow.

    Parameters
    ----------
    configured : dict
        Mapping flag name -> configured value. Values MUST already be
        legal (validated by ``Settings``); this function does not
        re-validate legality. Missing flags are treated as their default
        V1/disabled baseline.

    Returns
    -------
    dict
        Mapping flag name -> ``EffectiveMode``.
    """
    # Fill defaults for any missing flag.
    full: Dict[str, str] = {}
    for flag in ALL_FLAGS:
        full[flag] = configured.get(flag, _v1_baseline(flag))

    result: Dict[str, EffectiveMode] = {}
    for flag in _topological_order():
        cfg = full[flag]
        upstream_name = UPSTREAM[flag]
        if upstream_name is None:
            # Root: effective == configured (no conflict downgrade).
            result[flag] = EffectiveMode(
                flag=flag, configured=cfg, effective=cfg, downgraded=False
            )
            continue

        upstream = result.get(upstream_name)
        upstream_effective = (
            upstream.effective if upstream is not None else _v1_baseline(upstream_name)
        )
        if _is_v2(cfg) and not _is_v2(upstream_effective):
            # Conflict: module wants V2 but upstream is V1/disabled.
            result[flag] = EffectiveMode(
                flag=flag,
                configured=cfg,
                effective=_v1_baseline(flag),
                downgraded=True,
                fallback_reason=f"upstream_{upstream_name}_not_v2:{upstream_effective}",
            )
        else:
            result[flag] = EffectiveMode(
                flag=flag, configured=cfg, effective=cfg, downgraded=False
            )
    return result


# ---------------------------------------------------------------------------
# Business-level fail-closed (shadow runtime error)
# ---------------------------------------------------------------------------


def shadow_runtime_fail_closed(
    flag: str, configured: str, reason: str
) -> EffectiveMode:
    """Build a business-level fail-closed ``EffectiveMode``.

    Use when the configuration was LEGAL (passed startup fail-fast) but
    V2 shadow execution failed at runtime (timeout, exception, service
    unavailable). The effective mode downgrades to V1/disabled so V1
    behavior is preserved, and ``fallback_reason`` records why shadow did
    not run.

    This is distinct from a configuration error (which fails fast at
    startup and never reaches this function).
    """
    return EffectiveMode(
        flag=flag,
        configured=configured,
        effective=_v1_baseline(flag),
        downgraded=True,
        fallback_reason=f"shadow_runtime_error:{flag}:{reason}",
    )


def is_configured_v2(configured: Dict[str, str], flag: str) -> bool:
    """True if a flag is configured (not effective) as V2/shadow."""
    return _is_v2(configured.get(flag, _v1_baseline(flag)))


def all_default(configured: Dict[str, str]) -> bool:
    """True if every flag is at its V1/disabled default (no V2 enabled)."""
    return all(
        configured.get(flag, _v1_baseline(flag)) == _v1_baseline(flag)
        for flag in ALL_FLAGS
    )
