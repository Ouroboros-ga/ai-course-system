"""Startup-time configuration validation for agent profiles.

This module enforces hard gates that prevent an agent from declaring a
capability (e.g. ``supports_checkpoint=True``) without backing infrastructure
(e.g. a real ``CheckpointPort``). Without these checks, the system would
silently run with null implementations, producing "decorative capabilities"
that appear enabled but do nothing.

These checks are called from bootstrap AFTER all providers are registered.
They raise ``AgentConfigurationError`` on violation; bootstrap catches the
error and either fails fast or logs a warning depending on the environment.

Design rules:
    - Checks are pure functions of (profile, providers); they do NOT
      inspect runtime state.
    - Checks are additive: new capabilities add new checks here.
    - Checks do NOT replace runtime guards; they complement them. A
      profile that passes validation may still fail at run time (e.g.
      checkpoint port raises). The difference is that validation catches
      *configuration* errors before any run starts.
"""

from __future__ import annotations

from typing import Any, Mapping

from .errors import AgentConfigurationError
from .profile import AgentProfile, ExecutionMode


def validate_agent_configuration(
    profile: AgentProfile,
    *,
    checkpoint_port: Any | None = None,
    queue_provider: Any | None = None,
    tool_invoker: Any | None = None,
    concurrency_limiter: Any | None = None,
) -> None:
    """Validate that a profile's declared capabilities have backing infrastructure.

    Raises ``AgentConfigurationError`` on the first violation. Called from
    bootstrap after all providers are registered.

    Args:
        profile: The agent profile to validate.
        checkpoint_port: The checkpoint port (None or NullCheckpointPort
            means "not configured").
        queue_provider: The queue provider for QUEUED execution mode.
        tool_invoker: The tool invoker for allowed_tool_names enforcement.
        concurrency_limiter: The concurrency limiter for max_concurrency.

    Checks:
        1. ``supports_checkpoint=True`` requires a real CheckpointPort
           (not None, not NullCheckpointPort).
        2. ``execution_mode=QUEUED`` requires a queue_provider.
        3. ``allowed_tool_names`` non-empty requires a tool_invoker.
        4. ``max_concurrency`` set requires a concurrency_limiter.
    """
    agent_type = profile.agent_type.value

    # Check 1: checkpoint capability requires a real checkpoint port.
    if profile.supports_checkpoint:
        if checkpoint_port is None or _is_null_implementation(checkpoint_port):
            raise AgentConfigurationError(
                f"Agent '{agent_type}' declares supports_checkpoint=True but no "
                f"CheckpointPort is configured. Either register a real CheckpointPort "
                f"or set supports_checkpoint=False in the profile.",
            )

    # Check 2: queued execution requires a queue provider.
    if profile.execution_mode == ExecutionMode.QUEUED:
        if queue_provider is None:
            raise AgentConfigurationError(
                f"Agent '{agent_type}' declares execution_mode=QUEUED but no "
                f"queue_provider is configured. Either register a queue provider "
                f"or set execution_mode=INLINE.",
            )

    # Check 3: allowed_tool_names requires a tool invoker to enforce it.
    if profile.allowed_tool_names:
        if tool_invoker is None:
            raise AgentConfigurationError(
                f"Agent '{agent_type}' declares allowed_tool_names but no "
                f"ToolInvoker is configured. The whitelist would not be enforced.",
            )

    # Check 4: max_concurrency requires a concurrency limiter.
    if profile.max_concurrency is not None:
        if concurrency_limiter is None:
            raise AgentConfigurationError(
                f"Agent '{agent_type}' declares max_concurrency={profile.max_concurrency} "
                f"but no concurrency_limiter is configured.",
            )

    # Check 5: EDU agent must NOT share runtime across actors until KG-MEST
    # is stateless (Phase 2b). This prevents the specific cross-contamination
    # where student A's KG-MEST report is bound at construction and reused
    # by student B.
    #
    # The check uses agent_type value rather than the enum to avoid import
    # cycles; "edu" is the stable string identifier.
    if agent_type == "edu" and profile.share_runtime_across_actors:
        raise AgentConfigurationError(
            f"Agent 'edu' must not set share_runtime_across_actors=True until KG-MEST "
            f"reads are moved to call time (Phase 2b). Sharing the EDU runtime across "
            f"students would cross-contaminate their cognitive state.",
        )


def _is_null_implementation(obj: Any) -> bool:
    """Check if an object is a Null* implementation.

    Null implementations have "Null" in their class name and provide no-op
    behavior. They are valid for testing but dangerous in production when
    a profile claims to need them.
    """
    return "Null" in type(obj).__name__


def validate_platform_configuration(
    platform: Any,
    *,
    profiles: Mapping[str, AgentProfile] | None = None,
) -> list[str]:
    """Validate all profiles registered on a platform.

    Returns a list of warnings (empty if all valid). Raises
    ``AgentConfigurationError`` on the first hard violation.

    This is a convenience wrapper that calls ``validate_agent_configuration``
    for each profile, pulling the relevant providers from the platform.
    Profiles that are None (not yet registered) are skipped.
    """
    warnings: list[str] = []

    if profiles is None:
        return warnings

    checkpoint_port = getattr(platform, "_checkpoint_port", None)
    queue_provider = getattr(platform, "_queue_provider", None)
    tool_invoker = getattr(platform, "_tool_invoker", None)
    concurrency_limiter = getattr(platform, "_concurrency_limiter", None)

    for name, profile in profiles.items():
        if profile is None:
            warnings.append(f"Profile '{name}' is None; skipped validation.")
            continue
        try:
            validate_agent_configuration(
                profile,
                checkpoint_port=checkpoint_port,
                queue_provider=queue_provider,
                tool_invoker=tool_invoker,
                concurrency_limiter=concurrency_limiter,
            )
        except AgentConfigurationError as error:
            raise

    return warnings


__all__ = [
    "validate_agent_configuration",
    "validate_platform_configuration",
]
