from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticContext:
    run_id: str = ""
    trace_id: str = ""
    course_id: str = ""


current_diagnostic_context: ContextVar[DiagnosticContext] = ContextVar(
    "agent_diagnostic_context", default=DiagnosticContext()
)

__all__ = ["DiagnosticContext", "current_diagnostic_context"]
