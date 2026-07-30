"""Compatibility shim: the teaching workflow now lives in ``edu/workflow``."""

from __future__ import annotations

from ..edu.workflow import build_teaching_workflow

__all__ = ["build_teaching_workflow"]
