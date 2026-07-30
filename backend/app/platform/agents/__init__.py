"""Controlled, multi-agent workflow orchestration.

The TeachingAgent-specific artifacts (state, workflow, policy, prompts,
composition, registry, runtime) have been migrated to the ``edu/`` subpackage.
This top-level package re-exports the public API for backward compatibility.

The ``AgentPlatform`` (Commit 5) provides a unified registry for all three
integrated agents (EDU, PREP, CODING). It wraps the legacy
``TeachingAgentRuntimeRegistry`` for EDU and supports generic
``LangGraphAgentRuntime`` registration for PREP and CODING.
"""

from .composition import build_course_sidecar_runtime, build_kg_mest_shadow_sidecar_runtime, build_teaching_runtime
from .platform import AgentPlatform
from .runtime import TeachingAgentRuntime

__all__ = [
    "TeachingAgentRuntime",
    "AgentPlatform",
    "build_teaching_runtime",
    "build_course_sidecar_runtime",
    "build_kg_mest_shadow_sidecar_runtime",
]
