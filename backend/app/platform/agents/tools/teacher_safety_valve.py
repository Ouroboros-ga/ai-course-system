"""Compatibility shim: teacher safety-valve port now lives in providers/governance/teacher_safety_valve."""

from __future__ import annotations

from ..providers.governance.teacher_safety_valve import (
    make_session_scoped_teacher_safety_valve_port,
)
