"""Controlled, single-agent teaching workflow orchestration."""

from .runtime import TeachingAgentRuntime
from .composition import build_course_sidecar_runtime, build_kg_mest_shadow_sidecar_runtime, build_teaching_runtime

__all__ = ["TeachingAgentRuntime", "build_teaching_runtime", "build_course_sidecar_runtime", "build_kg_mest_shadow_sidecar_runtime"]
