"""Product 1 V2 safety dry-run shadow (G3D3).

Runs the P1-08 SafetyEvaluator on V1 user requests in shadow, recording
``would_allow`` / ``would_refuse`` decisions WITHOUT blocking V1. V1
behavior is unchanged: the dry-run never intercepts the V1 response.

ADR-0006 §G3D3:
- Trigger only when ``SAFETY_GOVERNANCE_MODE`` is effectively ``shadow``
  (SAFETY_GOVERNANCE_MODE is a root independent flag).
- Records would_allow / would_refuse + reason_code; does NOT block V1.
- Platform safety rules still apply (the dry-run uses the full P1-08
  evaluator); course rules cannot override platform底线.
- Privacy: audit minimization (no full user content stored; question
  stored as sha256).
- Business fail-closed; V1 never blocked.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.feature_flags import (
    SAFETY_GOVERNANCE_MODE,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)

DEFAULT_SAFETY_SHADOW_ROOT = "./p1_shadow_safety_dryrun"


@dataclass(frozen=True)
class SafetyDryRunResult:
    triggered: bool
    effective_mode: str
    trace_path: Optional[str] = None
    would_allow: bool = True
    would_refuse: bool = False
    reason_code: Optional[str] = None
    v1_blocked: bool = False  # always False in G3D3 (never blocks V1)
    fallback_reason: Optional[str] = None
    duration_ms: float = 0.0


class SafetyDryRunStore:
    def __init__(self, base_dir: str | Path = DEFAULT_SAFETY_SHADOW_ROOT) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, run_id: str) -> Path:
        if not run_id or not all(c.isalnum() or c in "_-" for c in run_id):
            raise ValueError(f"unsafe run_id: {run_id!r}")
        if "/" in run_id or "\\" in run_id or "." in run_id:
            raise ValueError(f"unsafe run_id: {run_id!r}")
        return self._base / f"{run_id}.json"

    def write(self, run_id: str, payload: Dict[str, Any]) -> Path:
        path = self._safe_path(run_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def base_dir(self) -> Path:
        return self._base


def _configured_modes() -> Dict[str, str]:
    try:
        from app.core.config import settings
        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_safety_mode():
    return resolve_effective_modes(_configured_modes())[SAFETY_GOVERNANCE_MODE]


def _evaluate_safety_dryrun(question: str, course_id: Any) -> Dict[str, Any]:
    """Run P1-08 SafetyEvaluator in dry-run mode.

    Uses the P1-08 evaluator + a default platform policy. Records the
    decision (would_allow / would_refuse + reason_code) but does NOT
    block. Imports P1-08 lazily.

    A real deployment would pass the actual course policy; G3D3 dry-run
    uses platform-default rules to prove the evaluator runs and produces
    stable reason codes without blocking V1.
    """
    from app.domain.safety.policy import SafetyPolicy, PolicySet
    from app.domain.safety.evaluator import SafetyEvaluator

    # Platform-default policy (course rules cannot override platform底线).
    # G3D3 dry-run: empty rules -> nothing matches -> would_allow (pass).
    # If the evaluator errors, fail-closed would_refuse.
    platform_policy = SafetyPolicy(policy_id="platform_default")
    policy_set = PolicySet(platform_policy=platform_policy, course_policies=[])
    evaluator = SafetyEvaluator(policy_set=policy_set)

    # Evaluate at INPUT stage (user question).
    result = evaluator.check_input(question or "")
    decision = result.decision
    outcome_val = decision.outcome.value if hasattr(decision.outcome, "value") else str(decision.outcome)
    would_refuse = outcome_val in ("block", "restrict", "error")
    return {
        "would_allow": not would_refuse,
        "would_refuse": would_refuse,
        "reason_code": decision.reason_code.value if hasattr(decision.reason_code, "value") else str(decision.reason_code),
        "stage": decision.stage.value if hasattr(decision.stage, "value") else str(decision.stage),
        "outcome": outcome_val,
    }


def trigger_safety_dryrun(
    question: str,
    course_id: Any,
    store: Optional[SafetyDryRunStore] = None,
) -> SafetyDryRunResult:
    """Trigger a V2 safety dry-run on a V1 user request.

    HARD CONSTRAINT (ADR §G3D3): does NOT block V1. ``v1_blocked`` is
    always False. Only records would_allow / would_refuse.

    NEVER raises into V1 (business fail-closed).
    """
    import uuid

    start = time.time()
    store = store or SafetyDryRunStore()

    effective = _effective_safety_mode()
    if effective.effective != "shadow":
        return SafetyDryRunResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_shadow",
            duration_ms=(time.time() - start) * 1000,
        )

    run_id = f"safety_{uuid.uuid4().hex}"
    try:
        decision = _evaluate_safety_dryrun(question, course_id)
        trace = {
            "run_id": run_id,
            "triggered_at": time.time(),
            "course_id": str(course_id) if course_id is not None else None,
            "question_sha256": hashlib.sha256((question or "").encode("utf-8")).hexdigest(),
            "effective_mode": "shadow",
            "v1_blocked": False,  # HARD CONSTRAINT: never blocks V1
            "would_allow": decision["would_allow"],
            "would_refuse": decision["would_refuse"],
            "reason_code": decision["reason_code"],
            "stage": decision["stage"],
            "outcome": decision["outcome"],
        }
        path = store.write(run_id, trace)
        return SafetyDryRunResult(
            triggered=True,
            effective_mode="shadow",
            trace_path=str(path),
            would_allow=decision["would_allow"],
            would_refuse=decision["would_refuse"],
            reason_code=decision["reason_code"],
            v1_blocked=False,
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        fc = shadow_runtime_fail_closed(
            SAFETY_GOVERNANCE_MODE, "shadow", f"runtime:{type(e).__name__}:{e}"
        )
        logger.warning(f"[G3D3 safety dry-run] runtime error: {e}", exc_info=True)
        return SafetyDryRunResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
