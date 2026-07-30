"""CommonPrepDependencies: shared dependency container for Prep pipelines.

A frozen dataclass carrying the cross-cutting dependencies every Prep
pipeline needs: the structured LLM port, the run store, and the event port.
Pipeline-specific dependencies (Service singletons, session factories) are
assembled in the agent composition root and are not part of this common
container.

``run_store`` and ``event_port`` are typed as ``Any`` to avoid importing
the runtime event ports at module load time, which would create a circular
import with the runtime layer for some bootstrap orderings. Callers should
pass concrete ``AgentRunStorePort`` / ``AgentRunEventPort`` implementations
(see ``runtime/events.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...contracts.llm import StructuredLLMPort


@dataclass(frozen=True)
class CommonPrepDependencies:
    """Shared dependencies injected into every Prep pipeline.

    Attributes:
        structured_llm: Low-level structured LLM port (``contracts/llm.py``).
            Business adapters (e.g. ``PrepLLMAdapter``) wrap this port.
        run_store: ``AgentRunStorePort`` implementation for run persistence.
            Typed ``Any`` to avoid a runtime circular import with the runtime
            event module.
        event_port: ``AgentRunEventPort`` implementation for lifecycle event
            emission. Typed ``Any`` for the same reason as ``run_store``.
    """

    structured_llm: StructuredLLMPort
    run_store: Any
    event_port: Any


__all__ = ["CommonPrepDependencies"]
