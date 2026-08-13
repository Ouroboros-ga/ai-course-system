"""Compatibility shim: coding diagnosis and student-history ports now live in providers/sandbox/coding."""

from __future__ import annotations

from ..providers.sandbox.coding import (
    SessionScopedCodeSubmissionPort,
    SessionScopedCodingDiagnosisPort,
    SessionScopedStudentHistoryPort,
    make_session_scoped_code_submission_port,
    make_session_scoped_coding_ports,
)
