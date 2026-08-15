"""Sandbox and code-diagnosis ports: code execution results and diagnoses.

These ports read code-execution artifacts. ``CodingDiagnosisPort`` is strictly
read-only and its diagnoses are NOT formal ``LearningEvidence``.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class SandboxPort(Protocol):
    async def get_execution_result(self, *, student_id: str, course_id: str, code_submission_id: str) -> Mapping[str, Any]: ...


class CodingDiagnosisPort(Protocol):
    """只读代码诊断；诊断不是正式 LearningEvidence。"""

    async def get_latest_diagnosis(
        self, *, student_id: str, course_id: str, run_id: str | None = None,
    ) -> Mapping[str, Any] | None: ...


class CodeSubmissionPort(Protocol):
    """Return source only to CodingAgent for one explicitly scoped submission.

    Implementations must validate student, course, and run identity themselves.
    The returned source is ephemeral teaching context: callers must not persist
    it in graph state, diagnosis records, audit traces, or cross-agent payloads.
    """

    async def get_submission_for_diagnosis(
        self, *, student_id: str, course_id: str, run_id: str,
    ) -> Mapping[str, Any] | None: ...


__all__ = ["SandboxPort", "CodingDiagnosisPort", "CodeSubmissionPort"]
