"""Compatibility shim: ``TeachingState`` now lives in ``edu/state``.

This module re-exports ``TeachingState`` from its new home so existing
imports ``from app.platform.agents.state import TeachingState`` continue to
work without modification.
"""

from __future__ import annotations

from .edu.state import TeachingState

__all__ = ["TeachingState"]
