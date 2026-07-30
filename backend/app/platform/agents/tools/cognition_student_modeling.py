"""Compatibility shim: student-modeling adapter now lives in providers/cognition/student_model."""

from __future__ import annotations

from ..providers.cognition.student_model import (
    CognitionStudentModelingPort,
    UnknownStudentModelingPort,
)
