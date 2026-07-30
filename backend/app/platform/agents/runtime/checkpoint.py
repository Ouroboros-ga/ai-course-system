"""Checkpoint protocol for durable agent run resumption.

This module defines the checkpoint protocol that agents MAY use for
interrupt/resume semantics. Phase 1 provides the protocol only; no
implementation is wired.

Design rules (per migration plan):
    - Checkpoint does NOT replace ``ConversationContextPort``. They serve
      different purposes: checkpoint is execution recovery (node position,
      intermediate state); conversation context is domain memory (visible
      dialogue, session summary).
    - Not all agents need checkpointing:
        - Edu: not needed (stateless Q&A, uses ConversationContext)
        - Prep: needed (long-running initial build, teacher interrupt/resume)
        - Coding (read-only diagnosis): not needed
        - Coding (verification loop): needed (future Phase 6)
    - The current project has NO LangGraph Checkpointer configured. Adding
      ``thread_id`` alone does NOT enable recovery; a real Checkpointer
      implementation is required.

Phase 1 status: protocol only, no implementation. Agents that set
``supports_checkpoint=True`` in their profile are declaring intent; the
runtime will reject checkpoint-dependent operations until an implementation
is registered.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class CheckpointPort(Protocol):
    """Durable checkpoint store for agent run resumption.

    A checkpoint captures:
        - The current LangGraph node position
        - A reference to the intermediate state
        - The run_id and thread_id for correlation

    On resume, the runtime loads the latest checkpoint and re-enters the
    graph at the saved node position.
    """

    async def save(
        self,
        *,
        run_id: str,
        thread_id: str,
        node_id: str,
        state: Mapping[str, Any],
    ) -> None:
        """Persist a checkpoint. Overwrites any previous checkpoint for the same run_id."""
        ...

    async def load(self, *, run_id: str) -> Mapping[str, Any] | None:
        """Load the latest checkpoint for run_id. Returns None if none exists."""
        ...

    async def delete(self, *, run_id: str) -> None:
        """Delete all checkpoints for run_id (called after successful completion)."""
        ...


class CheckpointNotConfiguredError(Exception):
    """Raised when an agent requests checkpoint operations but no CheckpointPort is registered.

    This is a programming error: the agent profile declares ``supports_checkpoint=True``
    but the bootstrap did not register a ``CheckpointPort`` implementation.
    """


class NullCheckpointPort:
    """No-op checkpoint port.

    ``save`` and ``delete`` are silent no-ops. ``load`` always returns None,
    meaning the runtime will start from the beginning as if no checkpoint
    exists. This is the safe default: it never produces stale state.
    """

    async def save(self, **kwargs: Any) -> None:
        pass

    async def load(self, *, run_id: str) -> Mapping[str, Any] | None:
        return None

    async def delete(self, *, run_id: str) -> None:
        pass


__all__ = [
    "CheckpointPort",
    "CheckpointNotConfiguredError",
    "NullCheckpointPort",
]
