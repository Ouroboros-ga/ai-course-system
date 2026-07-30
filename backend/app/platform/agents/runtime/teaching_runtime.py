"""Compatibility shim: ``TeachingAgentRuntime`` now lives in ``edu/runtime``.

This module exists so that the ``runtime/`` package can keep a stable
internal path for the legacy teaching runtime. New code should import from
``app.platform.agents.edu.runtime`` directly.
"""

from __future__ import annotations

from ..edu.runtime import TeachingAgentRuntime

__all__ = ["TeachingAgentRuntime"]
