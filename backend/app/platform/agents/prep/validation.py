"""Prep plan validation ports.

Defines ``PrepPlanValidatorPort`` (Protocol) and a first-version
``PrepPlanValidator`` implementation. The first version keeps the existing
Service-internal validation as the source of truth and wraps it so the
agent runtime can invoke validation through a stable port.

    - ``validate_initial_output``: delegates to
      ``ControlledPrepWorkflow._assert_evidence_ids`` (the Initial
      pipeline's evidence-ID hard gate).
    - ``validate_incremental_plan``: rejects operations that reference IDs
      outside ``allowed_ids``. It raises on the first illegal reference
      rather than silently filtering, so the caller can surface the
      rejection as a user-facing error.

Design notes:
    - ``ControlledPrepWorkflow`` is imported lazily inside
      ``validate_initial_output`` to avoid a circular import with the
      Service layer at module load time.
    - The Incremental check is implemented directly here because the
      existing Service path silently filters illegal operations; the agent
      runtime requires a hard rejection (raise) so rejections are auditable
      and never dropped.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, Sequence, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class PrepPlanValidatorPort(Protocol):
    """Validate Prep Agent plan outputs.

    Implementations must raise on the first validation failure; they must
    NOT silently filter or repair illegal content.
    """

    def validate_initial_output(self, output: Any, evidence: Sequence[Any]) -> None:
        """Validate an Initial-pipeline structured output.

        Raises if the output references evidence IDs not present in
        ``evidence``.
        """
        ...

    def validate_incremental_plan(
        self,
        operations: Sequence[Any],
        allowed_ids: Sequence[str],
    ) -> None:
        """Validate an Incremental-pipeline plan.

        Raises if any operation references a ``target_id`` outside
        ``allowed_ids``. Does NOT silently filter illegal operations.
        """
        ...


class PrepPlanValidator:
    """First-version validator that delegates to / complements existing checks.

    The Initial pipeline's evidence-ID hard gate already lives in
    ``ControlledPrepWorkflow._assert_evidence_ids``; this wrapper invokes it
    via a lazy import to avoid a circular dependency with the Service layer.

    The Incremental pipeline's ID-allow-list check is implemented here
    directly because the Service currently filters silently; the agent
    runtime requires a hard rejection (raise) so the rejection is
    auditable.
    """

    def validate_initial_output(self, output: Any, evidence: Sequence[Any]) -> None:
        """Delegate to ``ControlledPrepWorkflow._assert_evidence_ids``.

        ``output`` must be a pydantic ``BaseModel`` (the structured Initial
        result) and ``evidence`` a sequence of ``EvidenceReference``. The
        static method raises ``StructuredOutputError`` on unknown IDs.
        """
        from app.services.controlled_prep_workflow import ControlledPrepWorkflow

        ControlledPrepWorkflow._assert_evidence_ids(output, list(evidence))

    def validate_incremental_plan(
        self,
        operations: Sequence[Any],
        allowed_ids: Sequence[str],
    ) -> None:
        """Reject operations whose ``target_id`` is outside ``allowed_ids``.

        Each operation may be a pydantic model, a Mapping, or any object
        exposing a ``target_id`` attribute. The first illegal or missing
        reference raises ``ValueError``; no operations are silently dropped.
        """
        allowed = set(allowed_ids)
        for index, operation in enumerate(operations):
            target_id = _extract_target_id(operation)
            if target_id is None:
                # Malformed operation (no target_id) — reject rather than guess.
                raise ValueError(
                    f"incremental plan operation[{index}] has no target_id"
                )
            if target_id not in allowed:
                raise ValueError(
                    f"incremental plan operation[{index}] references unknown "
                    f"target_id={target_id!r}; not in allowed_ids"
                )


def _extract_target_id(operation: Any) -> str | None:
    """Read ``target_id`` from a pydantic model, Mapping, or plain object."""
    if operation is None:
        return None
    # Pydantic v2 model / dataclass / plain object: attribute access first.
    target = getattr(operation, "target_id", None)
    if target is not None:
        return str(target)
    # Mapping (dict-like): fall back to key lookup.
    if isinstance(operation, dict):
        value = operation.get("target_id")
        return str(value) if value is not None else None
    return None


__all__ = ["PrepPlanValidatorPort", "PrepPlanValidator"]
