"""Shared workflow helpers (trace, degrade, governance, audit).

These helpers were originally private to ``workflows/teaching.py``. They are
extracted here so any agent workflow can reuse the same trace/degradation/
governance shape. The helpers are decoupled from ``TeachingTools``: they
accept the governance port directly, which lets non-Teaching agents reuse
them without constructing a full ``TeachingTools`` instance.

The signatures intentionally match the original private helpers so the
TeachingAgent workflow can switch to these with a one-line import change in
Commit 2.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..contracts import ToolGovernancePort


def trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    """Append a trace entry to ``state["trace"]`` and return the new list."""
    return [*state.get("trace", []), {"node": node, **detail}]


def degrade(state: Mapping[str, Any], service: str, code: str) -> dict[str, Any]:
    """Return a partial update marking ``service`` as degraded with ``code``."""
    return {
        "warnings": [*state.get("warnings", []), code],
        "degraded_services": [*state.get("degraded_services", []), service],
    }


async def governance_check(
    governance: ToolGovernancePort | None,
    state: Mapping[str, Any],
    *,
    course_id: str,
    tool_name: str,
) -> tuple[bool, dict[str, Any]]:
    """Check whether ``tool_name`` is enabled by teacher policy.

    Returns ``(allowed, meta)``. When ``governance`` is ``None`` the tool is
    allowed (default-open). When the governance call itself raises, the tool
    is still allowed (fail-open) so a governance outage never blocks Q&A.
    The skipped-tool list is returned in ``meta["skipped"]`` only when the
    tool is explicitly disabled.
    """
    if governance is None:
        return True, {}
    try:
        allowed = await governance.is_tool_enabled(
            course_id=course_id, tool_name=tool_name,
        )
        meta: dict[str, Any] = {"allowed": allowed}
        if not allowed:
            meta["skipped"] = [*state.get("governance_skipped_tools", []), tool_name]
        return allowed, meta
    except Exception:  # noqa: BLE001 -- 治理失败不阻断主流程
        return True, {}


async def record_invocation(
    governance: ToolGovernancePort | None,
    state: Mapping[str, Any],
    *,
    course_id: str,
    student_id: str,
    trace_id: str,
    tool_name: str,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    duration_ms: int | None = None,
    degraded: bool = False,
    degraded_reason: str = "",
    allowed_by_policy: bool = True,
) -> None:
    """Record a tool invocation audit row; failures never block the workflow."""
    if governance is None:
        return
    try:
        await governance.record_invocation(
            course_id=course_id, student_id=student_id,
            trace_id=trace_id, tool_name=tool_name,
            input_summary=input_summary, output_summary=output_summary,
            duration_ms=duration_ms, degraded=degraded,
            degraded_reason=degraded_reason, allowed_by_policy=allowed_by_policy,
        )
    except Exception:  # noqa: BLE001
        pass
