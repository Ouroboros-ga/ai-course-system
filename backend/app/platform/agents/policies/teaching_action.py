"""Compatibility shim: the teaching-action policy now lives in ``edu/policy``."""

from __future__ import annotations

from ..edu.policy import decide_teaching_action

__all__ = ["decide_teaching_action"]
