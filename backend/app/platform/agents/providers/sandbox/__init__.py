"""Sandbox-domain providers: coding diagnosis and student-history adapters."""

from .coding import (
    SessionScopedCodingDiagnosisPort,
    SessionScopedStudentHistoryPort,
    make_session_scoped_coding_ports,
)

__all__ = [
    "SessionScopedCodingDiagnosisPort",
    "SessionScopedStudentHistoryPort",
    "make_session_scoped_coding_ports",
]
