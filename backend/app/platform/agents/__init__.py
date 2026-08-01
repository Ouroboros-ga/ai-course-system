"""Controlled, multi-agent workflow orchestration.

The TeachingAgent-specific artifacts (state, workflow, policy, prompts,
composition, registry, runtime) have been migrated to the ``edu/`` subpackage.
This top-level package re-exports the public API for backward compatibility.

The ``AgentPlatform`` (Commit 5) provides a unified registry for all three
integrated agents (EDU, PREP, CODING). It wraps the legacy
``TeachingAgentRuntimeRegistry`` for EDU and supports generic
``LangGraphAgentRuntime`` registration for PREP and CODING.
"""

__all__ = [
    "TeachingAgentRuntime",
    "AgentPlatform",
    "build_teaching_runtime",
    "build_course_sidecar_runtime",
    "build_kg_mest_shadow_sidecar_runtime",
]


def __getattr__(name: str):
    """Load public compatibility exports only when a caller actually needs them.

    Importing a narrow Prep submodule must not eagerly build the EDU composition
    chain, because that chain may include optional GraphRAG dependencies.  The
    package remains backwards compatible for callers that import its public
    exports directly.
    """
    if name in {
        "build_teaching_runtime",
        "build_course_sidecar_runtime",
        "build_kg_mest_shadow_sidecar_runtime",
    }:
        from .composition import (
            build_course_sidecar_runtime,
            build_kg_mest_shadow_sidecar_runtime,
            build_teaching_runtime,
        )

        return {
            "build_teaching_runtime": build_teaching_runtime,
            "build_course_sidecar_runtime": build_course_sidecar_runtime,
            "build_kg_mest_shadow_sidecar_runtime": build_kg_mest_shadow_sidecar_runtime,
        }[name]
    if name == "AgentPlatform":
        from .platform import AgentPlatform

        return AgentPlatform
    if name == "TeachingAgentRuntime":
        from .runtime import TeachingAgentRuntime

        return TeachingAgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
