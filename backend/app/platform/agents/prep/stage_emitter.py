"""StageEmitter: bridge ControlledPrepWorkflow stage callbacks to runtime events.

``ControlledPrepWorkflow.run`` accepts an ``on_stage`` callback with the
signature ``Callable[[str, int, Any], Awaitable[None] | None]`` that fires
``(stage, progress, value)`` tuples as the Initial pipeline advances.
``StageEmitter`` adapts that callback shape to the Agent Runtime event
system (``AgentRunEventPort``) so that stage progress surfaces as run
lifecycle events.

Event type mapping:
    - First observation of a stage (progress == 0)  -> ``stage.started``
    - Subsequent progress within the same stage      -> ``stage.progress``
    - Stage transition (new stage begins)            -> ``stage.completed``
      for the previous stage, then ``stage.started`` for the new one.

The ``stage.*`` event types follow the dot-notation convention of
``RunEventType`` (``run.started``, ``node.entered``, ...) but are NOT yet
members of that enum. Adding them would require modifying the existing
``runtime/events.py`` port, which the migration constraints forbid at this
phase. ``AgentRunEventPort.emit`` accepts these string values at runtime
because ``RunEventType`` subclasses ``str``; a future phase may promote
``stage.*`` to first-class enum members without changing emitter callers.

Note: the last stage of a run does not receive an explicit
``stage.completed`` event through this callback (there is no subsequent
stage transition to trigger it). The runtime's terminal ``run.completed``
/ ``run.failed`` event covers overall run termination.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from ..runtime.events import AgentRunEventPort, AgentRunStorePort

logger = logging.getLogger(__name__)

# Stage event type literals. Forward-compatible with RunEventType's dot
# notation; intentionally NOT added to the enum to avoid modifying the
# existing runtime/events.py port at this phase.
STAGE_STARTED = "stage.started"
STAGE_PROGRESS = "stage.progress"
STAGE_COMPLETED = "stage.completed"


class StageEmitter:
    """Adapt ``ControlledPrepWorkflow.on_stage`` to runtime events.

    A single ``StageEmitter`` is bound to one agent run (``run_id`` /
    ``trace_id``). ``make_callback()`` returns the callable to pass as
    ``on_stage`` to ``ControlledPrepWorkflow.run``.

    The ``run_store`` is held for run-status correlation; stage progress
    does not change terminal run status (the run stays ``RUNNING``), so the
    emitter only emits events through ``event_port`` and does not write the
    store on every stage tick. The store remains available for future
    checkpoint/progress-persistence extensions.
    """

    def __init__(
        self,
        *,
        run_store: AgentRunStorePort,
        event_port: AgentRunEventPort,
        run_id: str,
        trace_id: str,
    ) -> None:
        self._run_store = run_store
        self._event_port = event_port
        self._run_id = run_id
        self._trace_id = trace_id
        self._current_stage: str | None = None
        self._seen_stages: set[str] = set()

    # -- public API ------------------------------------------------------

    def make_callback(self) -> Callable[[str, int, Any], Awaitable[None] | None]:
        """Build the ``on_stage`` callback for ``ControlledPrepWorkflow.run``."""

        async def on_stage(stage: str, progress: int, value: Any) -> None:
            await self._handle(stage, progress, value)

        return on_stage

    # -- internals -------------------------------------------------------

    def _resolve_event_type(self, stage: str, progress: int) -> str:
        """Resolve the event type for the current ``(stage, progress)`` tuple.

        - A stage never seen before, or ``progress <= 0``, marks a start.
        - Any subsequent update within the same stage is progress.

        This method is read-only; stage bookkeeping is updated by ``_handle``
        so the resolver stays side-effect free and predictable.
        """
        if stage not in self._seen_stages or progress <= 0:
            return STAGE_STARTED
        return STAGE_PROGRESS

    async def _handle(self, stage: str, progress: int, value: Any) -> None:
        """Process one ``on_stage`` invocation, emitting events as needed."""
        # On a stage transition, close out the previous stage first.
        if self._current_stage is not None and stage != self._current_stage:
            await self._emit(
                STAGE_COMPLETED,
                stage=self._current_stage,
                progress=100,
                value=None,
            )
            self._seen_stages.discard(self._current_stage)

        event_type = self._resolve_event_type(stage, progress)
        self._current_stage = stage
        self._seen_stages.add(stage)
        await self._emit(event_type, stage=stage, progress=progress, value=value)

    async def _emit(
        self,
        event_type: str,
        *,
        stage: str,
        progress: int,
        value: Any,
    ) -> None:
        """Emit one stage event through ``AgentRunEventPort``.

        Event emission is fail-open: a failure here must NOT abort the agent
        run (per the ``AgentRunEventPort`` contract). The error is logged
        and swallowed.
        """
        payload: dict[str, Any] = {
            "stage": stage,
            "progress": progress,
        }
        # Carry only a presence flag for the value to keep event payloads
        # small and avoid serialising large structured results into storage.
        if value is not None:
            payload["has_value"] = True
        try:
            await self._event_port.emit(
                run_id=self._run_id,
                trace_id=self._trace_id,
                event_type=event_type,  # type: ignore[arg-type]  # stage.* extends RunEventType vocabulary
                payload=payload,
            )
        except Exception as error:  # noqa: BLE001 - fail-open for events
            logger.warning(
                "StageEmitter: event emission failed for %s/%s: %s: %s",
                stage, event_type, type(error).__name__, error,
            )


__all__ = ["StageEmitter", "STAGE_STARTED", "STAGE_PROGRESS", "STAGE_COMPLETED"]
