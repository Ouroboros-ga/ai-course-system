"""Compatibility shim: ``TeachingAgentRuntimeRegistry`` now lives in ``edu/registry``."""

from __future__ import annotations

from .edu.registry import CACHE_TTL_SECONDS, MAX_CACHE_SIZE, TeachingAgentRuntimeRegistry

__all__ = ["TeachingAgentRuntimeRegistry", "MAX_CACHE_SIZE", "CACHE_TTL_SECONDS"]
