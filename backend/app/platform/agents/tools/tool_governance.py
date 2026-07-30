"""Compatibility shim: tool-governance port now lives in providers/governance/tool_governance."""

from __future__ import annotations

from ..providers.governance.tool_governance import (
    HIGH_RISK_TOOLS,
    make_session_scoped_tool_governance_port,
)
