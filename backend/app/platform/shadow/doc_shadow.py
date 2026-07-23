"""Product 1 V2 document-parse shadow pipeline (G3B).

Triggered from ``document_service.process_document`` AFTER V1 parsing
has succeeded (commit-then-trigger per ADR-0006 §G3B). Writes V2 shadow
artifacts to an INDEPENDENT store (never V1 tables). V1 behavior is
unchanged: shadow failures are business-level fail-closed (recorded as
``fallback_reason``, V1 continues).

G3B scope (ADR-0006):
- Trigger only when ``DOCUMENT_PIPELINE_VERSION`` is effectively
  ``v2_shadow`` (after aggregate/module conflict resolution).
- Resource rules: single in-flight shadow per course, idempotent on
  (artifact+config), queue-full skips with fallback_reason, bounded
  timeout, abandoned on interrupt, no M7 GPU/port contention, disk
  quota + cleanup.
- No real Docling/PaddleOCR (fake/offline): the V2 shadow parse maps
  the V1 ``parse_result`` into a minimal DocumentIR-shaped shadow
  artifact to prove the chain runs and is traceable. Real provider
  quality comparison is G5 canary.
- Shadow artifact path is isolated from V1 Course/ScriptNode/
  KnowledgePageMap.

This module does NOT import or mutate V1 models. It reads only the V1
``parse_result`` (already produced) and ``file_path`` (already on disk).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.feature_flags import (
    DOCUMENT_PIPELINE_VERSION,
    EffectiveMode,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (resource rules)
# ---------------------------------------------------------------------------

# Shadow artifact store root. Isolated from V1 DB / Course tables.
DEFAULT_SHADOW_ROOT = os.environ.get(
    "P1_SHADOW_ARTIFACT_ROOT", "./p1_shadow_artifacts"
)

# Resource limits (ADR-0006 §G3B).
MAX_INFLIGHT_PER_COURSE = 1
SHADOW_TIMEOUT_SECONDS = 60.0
DISK_QUOTA_BYTES = 500 * 1024 * 1024  # 500 MB shadow artifact budget
QUEUE_FULL_SKIP = True  # skip + fallback_reason, never block V1

# Do NOT contend with M7-required resources (Duix/digital-human/TTS ports).
FORBIDDEN_M7_PORTS = {7860, 8383}  # digital_human, duix


# ---------------------------------------------------------------------------
# Shadow trigger result (trace + fallback)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowTriggerResult:
    """Outcome of a shadow trigger attempt.

    ``triggered`` is True when a V2 shadow run was actually started
    (or completed synchronously in tests). When the flag is disabled,
    conflict-downgraded, queue-full, idempotent-skip, or a runtime
    error occurred, ``triggered`` is False and ``fallback_reason``
    explains why V2 shadow did not run. V1 is never affected.
    """

    triggered: bool
    effective_mode: str
    artifact_path: Optional[str] = None
    shadow_run_id: Optional[str] = None
    fallback_reason: Optional[str] = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# In-flight tracking (process-wide, single-course concurrency)
# ---------------------------------------------------------------------------


class _InflightTracker:
    """Process-wide tracker for in-flight shadow runs per course.

    Enforces MAX_INFLIGHT_PER_COURSE. Thread-safe. A persistent/worker
    deployment would use a shared store; this in-process tracker is the
    G3B baseline (sufficient for single-process shadow; G4+ persistence
    is P1-09's later concern).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: Dict[str, set] = {}  # course_key -> set of run_ids

    def try_acquire(self, course_key: str, run_id: str) -> bool:
        with self._lock:
            current = self._inflight.setdefault(course_key, set())
            if len(current) >= MAX_INFLIGHT_PER_COURSE:
                return False
            current.add(run_id)
            return True

    def release(self, course_key: str, run_id: str) -> None:
        with self._lock:
            runs = self._inflight.get(course_key)
            if runs and run_id in runs:
                runs.discard(run_id)
                if not runs:
                    self._inflight.pop(course_key, None)


_tracker = _InflightTracker()


# ---------------------------------------------------------------------------
# Shadow artifact store (isolated from V1)
# ---------------------------------------------------------------------------


class ShadowArtifactStore:
    """Writes V2 shadow artifacts to an isolated directory.

    Path-traversal safe, checksummed, idempotent (same artifact+config
    key -> same path, overwrite-safe). Does NOT touch V1 tables, V1
    RAG registry, or V1 task state.
    """

    def __init__(self, base_dir: str | Path = DEFAULT_SHADOW_ROOT) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_rel(self, key: str) -> Path:
        # key is a hex hash; reject anything that looks path-like.
        if not all(c in "0123456789abcdef" for c in key) or not key:
            raise ValueError(f"unsafe shadow key: {key!r}")
        return self._base / f"{key}.json"

    def artifact_key(self, source_sha256: str, config_version: str) -> str:
        """Idempotent key from source checksum + config version."""
        raw = f"{source_sha256}:{config_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def write(self, key: str, payload: Dict[str, Any]) -> Path:
        path = self._safe_rel(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic
        return path

    def exists(self, key: str) -> bool:
        return self._safe_rel(key).exists()

    def read(self, key: str) -> Optional[Dict[str, Any]]:
        path = self._safe_rel(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def disk_usage_bytes(self) -> int:
        return sum(f.stat().st_size for f in self._base.glob("*.json"))

    def base_dir(self) -> Path:
        return self._base


# ---------------------------------------------------------------------------
# Minimal V2 shadow parse (fake/offline, G3B)
# ---------------------------------------------------------------------------


def _source_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_shadow_document_ir(
    file_path: Path,
    filename: str,
    parse_result: Any,
    source_sha256: str,
) -> Dict[str, Any]:
    """Build a minimal DocumentIR-shaped shadow artifact from V1 parse_result.

    This is NOT a real V2 parse (no Docling/PaddleOCR). It maps the V1
    parse_result into a DocumentIR-shaped dict to prove the shadow chain
    runs, is traceable to source bytes, and produces a comparable artifact.
    Real V2 parse quality is a G5 canary concern.
    """
    # V1 parse_result attributes (read defensively; do not assume shape).
    doc_title = getattr(parse_result, "doc_title", None) or filename
    markdown = getattr(parse_result, "markdown_content", None) or ""
    pages = getattr(parse_result, "pages", None) or []

    # Stable shadow document_id from source bytes (P1-01 stable-id spirit).
    doc_id = f"doc_{hashlib.sha256((source_sha256 + ':shadow').encode()).hexdigest()[:24]}"

    units = []
    for idx, page in enumerate(pages):
        page_text = ""
        if isinstance(page, dict):
            page_text = page.get("text") or page.get("content") or ""
        elif hasattr(page, "text"):
            page_text = page.text or ""
        block_id = f"blk_{hashlib.sha256((source_sha256 + f':{idx}').encode()).hexdigest()[:20]}"
        units.append({
            "unit_id": f"unit_{idx}",
            "page_or_slide": idx,
            "block_id": block_id,
            "text_snippet": page_text[:200],
            "char_span": [0, len(page_text)],
        })

    return {
        "schema_version": "document-ir/1.0",
        "document_id": doc_id,
        "artifact_id": f"art_{source_sha256[:24]}",
        "source_sha256": source_sha256,
        "source_filename": filename,
        "doc_title": doc_title,
        "page_count": len(pages) if pages else (markdown.count("\n## ") or 1),
        "units": units,
        "shadow_note": "G3B fake/offline shadow; not a real V2 parse",
    }


# ---------------------------------------------------------------------------
# Idempotency / conflict check
# ---------------------------------------------------------------------------


def _configured_modes_from_settings() -> Dict[str, str]:
    """Read configured flag values from Settings (cheap, no V2 import)."""
    try:
        from app.core.config import settings

        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_doc_pipeline_mode() -> EffectiveMode:
    """Resolve the EFFECTIVE DOCUMENT_PIPELINE_VERSION after conflict rules."""
    configured = _configured_modes_from_settings()
    modes = resolve_effective_modes(configured)
    return modes[DOCUMENT_PIPELINE_VERSION]


# ---------------------------------------------------------------------------
# Public trigger API (called from document_service seam)
# ---------------------------------------------------------------------------


def trigger_doc_shadow(
    file_path: Path,
    filename: str,
    parse_result: Any,
    course_key: Optional[str] = None,
    store: Optional[ShadowArtifactStore] = None,
    sidecar_store: Optional[Any] = None,
    sync: bool = True,
) -> ShadowTriggerResult:
    """Trigger a V2 document-parse shadow run after V1 success.

    Called from ``document_service.process_document`` (commit-then-
    trigger). NEVER raises into V1: all shadow errors are caught and
    returned as ``fallback_reason`` (business-level fail-closed).

    Parameters
    ----------
    file_path : Path
        V1 file already on disk (stable).
    filename : str
        Original filename.
    parse_result : Any
        V1 parse result (already produced). Read only.
    course_key : str, optional
        Course identifier for single-in-flight enforcement. Defaults to
        a key derived from the source file.
    store : ShadowArtifactStore, optional
        Inject for tests. Defaults to a store at DEFAULT_SHADOW_ROOT.
    sync : bool
        True = run synchronously (tests / small files). False = fire-
        and-forget background task (production). Either way V1 is not
        blocked: sync runs inside this call but catches all errors.

    Returns
    -------
    ShadowTriggerResult
    """
    start = time.time()
    store = store or ShadowArtifactStore()

    # 1. Flag check (conflict-aware). If not effectively v2_shadow, no-op.
    effective = _effective_doc_pipeline_mode()
    if effective.effective != "v2_shadow":
        return ShadowTriggerResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_v2_shadow",
            duration_ms=(time.time() - start) * 1000,
        )

    # 2. Source checksum (for idempotency key + artifact identity).
    try:
        source_sha = _source_sha256(file_path)
    except Exception as e:
        # V1 file unreadable is a runtime error (shouldn't happen post-V1).
        fc = shadow_runtime_fail_closed(DOCUMENT_PIPELINE_VERSION, "v2_shadow", f"source_read:{e}")
        return ShadowTriggerResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )

    config_version = "document-ir/1.0:shadow-g3b"
    artifact_key = store.artifact_key(source_sha, config_version)

    # 3. Idempotency: same artifact+config already written -> skip (not an error).
    if store.exists(artifact_key):
        return ShadowTriggerResult(
            triggered=False,
            effective_mode="v2_shadow",
            artifact_path=str(store._safe_rel(artifact_key)),
            fallback_reason="idempotent_skip:artifact_exists",
            duration_ms=(time.time() - start) * 1000,
        )

    # 4. Disk quota.
    if store.disk_usage_bytes() > DISK_QUOTA_BYTES:
        fc = shadow_runtime_fail_closed(DOCUMENT_PIPELINE_VERSION, "v2_shadow", "disk_quota_exceeded")
        return ShadowTriggerResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )

    # 5. Single-in-flight per course.
    run_id = str(uuid.uuid4())
    # ``ckey`` may be a synthetic file key for concurrency only.  It must
    # never be used as an Evidence course scope; sidecars are emitted only
    # for an explicit, real course_id supplied by the document workflow.
    sidecar_course_key = str(course_key) if course_key is not None else None
    ckey = sidecar_course_key or f"file:{source_sha[:16]}"
    if not _tracker.try_acquire(ckey, run_id):
        if QUEUE_FULL_SKIP:
            return ShadowTriggerResult(
                triggered=False,
                effective_mode="v2_shadow",
                fallback_reason="queue_full:inflight_limit",
                duration_ms=(time.time() - start) * 1000,
            )
        # If we ever disable skip, we still must not block V1: fall through
        # to fail-closed rather than wait.

    try:
        if sync:
            _run_shadow_sync(
                store, artifact_key, file_path, filename, parse_result, source_sha, run_id, sidecar_course_key, sidecar_store
            )
            artifact_path = str(store._safe_rel(artifact_key))
            triggered = True
            shadow_run_id = run_id
        else:
            # Fire-and-forget. V1 does not wait. Errors land in background.
            asyncio.get_event_loop().run_in_executor(
                None,
                _run_shadow_sync,
                store, artifact_key, file_path, filename, parse_result, source_sha, run_id,
                sidecar_course_key,
                sidecar_store,
            )
            artifact_path = None
            triggered = True
            shadow_run_id = run_id

        return ShadowTriggerResult(
            triggered=triggered,
            effective_mode="v2_shadow",
            artifact_path=artifact_path,
            shadow_run_id=shadow_run_id,
            duration_ms=(time.time() - start) * 1000,
        )
    except asyncio.TimeoutError:
        fc = shadow_runtime_fail_closed(DOCUMENT_PIPELINE_VERSION, "v2_shadow", "timeout")
        return ShadowTriggerResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        # Business-level fail-closed: any shadow error -> V1 continues.
        fc = shadow_runtime_fail_closed(DOCUMENT_PIPELINE_VERSION, "v2_shadow", f"runtime:{type(e).__name__}:{e}")
        logger.warning(f"[G3B shadow] runtime error: {e}", exc_info=True)
        return ShadowTriggerResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
    finally:
        _tracker.release(ckey, run_id)


def _run_shadow_sync(
    store: ShadowArtifactStore,
    artifact_key: str,
    file_path: Path,
    filename: str,
    parse_result: Any,
    source_sha: str,
    run_id: str,
    course_key: Optional[str] = None,
    sidecar_store: Optional[Any] = None,
) -> None:
    """Run the (fake/offline) V2 shadow parse and write the artifact.

    Bounded by SHADOW_TIMEOUT_SECONDS via a simple wall-clock check.
    No real provider call; no M7 port/GPU use.
    """
    deadline = time.time() + SHADOW_TIMEOUT_SECONDS
    ir_payload = _build_shadow_document_ir(file_path, filename, parse_result, source_sha)
    if time.time() > deadline:
        raise asyncio.TimeoutError()
    payload = {
        "shadow_run_id": run_id,
        "triggered_at": time.time(),
        "source_sha256": source_sha,
        "source_filename": filename,
        "effective_mode": "v2_shadow",
        "document_ir": ir_payload,
        "v1_diff": {
            "v1_page_count": len(getattr(parse_result, "pages", None) or []),
            "v1_doc_title": getattr(parse_result, "doc_title", None),
            # contract/integration diff (NOT a quality comparison)
        },
    }
    store.write(artifact_key, payload)

    # Test-environment retrieval consumes this independently stored sidecar,
    # never the research fixture or V1 RAG state.  A course scope is required
    # so an unscoped upload cannot become visible to course retrieval.
    if course_key:
        from app.platform.shadow.course_evidence_sidecar import (
            CourseEvidenceSidecarStore,
            build_sidecar,
        )

        sidecar = build_sidecar(
            course_id=course_key,
            document_ir=ir_payload,
            markdown=getattr(parse_result, "markdown_content", "") or "",
        )
        (sidecar_store or CourseEvidenceSidecarStore()).write(sidecar)
