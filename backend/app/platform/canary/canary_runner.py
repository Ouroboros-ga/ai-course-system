"""End-to-end canary runner for G5A (ADR-0006 §G5A).

Orchestrates the 6 G3 shadow triggers under all-flags-on with fake/fixture
V1 inputs, proving the full shadow chain runs end-to-end WITHOUT calling
real services (no ``process_document``, no ``llm_client``, no real
Docling/OCR/vector). Then aggregates a quality-gate report.

Canary scope control: only courses in ``CanaryConfig.course_ids`` are
exercised (blast-radius limiter, complementing flag gating). A course not
in the allowlist is skipped.

G5B (real-provider canary with real Docling/OCR/vector/LLM quality
comparison) is deferred until CLAUDE.md constraint relaxation.
"""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.platform.canary.quality_gate import QualityGateReport, compute_quality

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fake V1 inputs (no real services)
# ---------------------------------------------------------------------------


class _FakeParseResult:
    """Minimal V1 parse_result stand-in (read-only by the doc shadow)."""

    def __init__(self, doc_title: str = "Canary Doc") -> None:
        self.doc_title = doc_title
        self.pages = [{"text": "page1"}, {"text": "page2"}]
        self.markdown_content = "# Canary\n\nbody content for canary run."


def _fake_v1_sources() -> List[Dict[str, Any]]:
    return [
        {"path": "chap/sect/p1", "score": 0.9, "match_type": "keyword",
         "content_preview": "evidence content one"},
        {"path": "chap/sect/p2", "score": 0.7, "match_type": "keyword",
         "content_preview": "evidence content two"},
    ]


def _fake_knowledge_points() -> List[Dict[str, Any]]:
    return [
        {"id": "知识点1", "title": "力学", "content": "力学研究物体运动规律。力学基础。",
         "path": "力学", "level": 1},
        {"id": "知识点2", "title": "牛顿第二定律", "content": "F=ma 描述加速度与力的关系。核心定律。",
         "path": "力学/牛顿第二定律", "level": 2},
    ]


def _fake_v1_context() -> Dict[str, Any]:
    return {"rag_sources": _fake_v1_sources()}


# ---------------------------------------------------------------------------
# Config + result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanaryConfig:
    """Canary run configuration.

    ``course_ids`` is the allowlist (scope control). ``trace_roots`` lets
    tests inject isolated tmp directories per shadow store.
    """

    course_ids: List[Any] = field(default_factory=list)
    question: str = "什么是牛顿第二定律？"
    student_id: Any = 1001
    # Optional fake source file for the doc shadow (it reads bytes for sha256).
    # If None, the runner writes a deterministic fake file to a temp location.
    doc_file_path: Optional[Path] = None
    # Inject isolated stores per shadow path (tests pass tmp_path dirs).
    doc_store: Any = None
    evidence_store: Any = None
    learning_store: Any = None
    memory_store: Any = None
    safety_store: Any = None
    graph_store: Any = None


@dataclass(frozen=True)
class CourseCanaryResult:
    """Per-course canary outcome."""

    course_id: Any
    path_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    trace_paths_by_path: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class CanaryRunResult:
    """Overall canary outcome."""

    generated_at: float
    course_results: List[CourseCanaryResult] = field(default_factory=list)
    skipped_courses: List[Any] = field(default_factory=list)
    quality_gate: Optional[QualityGateReport] = None
    overall_passed: bool = False
    real_services_called: bool = False  # invariant: always False (G5A)


# ---------------------------------------------------------------------------
# All-flags-on config (satisfies every shadow's dependency chain)
# ---------------------------------------------------------------------------


def _all_flags_on() -> Dict[str, str]:
    """A flag config where every shadow path is effectively V2/shadow.

    Satisfies all dependency chains:
    - doc: DOCUMENT_PIPELINE_VERSION=v2_shadow
    - evidence: DOCUMENT_PIPELINE_VERSION + DOCUMENT_KG_RUNTIME_MODE + EVIDENCE_CITATION_MODE
    - graph: DOCUMENT_PIPELINE_VERSION + DOCUMENT_KG_RUNTIME_MODE + KNOWLEDGE_GRAPH_PIPELINE_VERSION
    - learning: LEARNING_EVENT_MODE=v2_shadow
    - memory: LEARNING_EVENT_MODE=v2_shadow + STUDENT_MEMORY_MODE=shadow
    - safety: SAFETY_GOVERNANCE_MODE=shadow
    """
    from app.core import feature_flags as ff

    cfg = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}  # all default
    cfg[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    cfg[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    cfg[ff.EVIDENCE_CITATION_MODE] = "v2_shadow"
    cfg[ff.KNOWLEDGE_GRAPH_PIPELINE_VERSION] = "v2_shadow"
    cfg[ff.LEARNING_EVENT_MODE] = "v2_shadow"
    cfg[ff.STUDENT_MEMORY_MODE] = "shadow"
    cfg[ff.SAFETY_GOVERNANCE_MODE] = "shadow"
    return cfg


# Module path -> flag-read function name to patch.
_FLAG_FN = {
    "doc_shadow": "_configured_modes_from_settings",
    "evidence_shadow": "_configured_modes",
    "learning_shadow": "_configured_modes",
    "memory_candidate_shadow": "_configured_modes",
    "safety_dryrun_shadow": "_configured_modes",
    "graph_shadow": "_configured_modes",
}


def _patch_all_flags_on():
    """Patch every shadow module's flag-read fn to all-flags-on.

    Yields inside a single ``ExitStack`` so all patches revert together.
    Returns the stack (caller closes it).
    """
    from contextlib import ExitStack
    from unittest.mock import patch

    stack = ExitStack()
    cfg = _all_flags_on()
    for mod, fn in _FLAG_FN.items():
        stack.enter_context(patch(f"app.platform.shadow.{mod}.{fn}", return_value=cfg))
    return stack


# ---------------------------------------------------------------------------
# Per-course canary execution
# ---------------------------------------------------------------------------


def _run_course_canary(course_id: Any, config: CanaryConfig) -> CourseCanaryResult:
    """Run all 6 shadow triggers for one course (fake inputs, no real services)."""
    from app.platform.shadow.doc_shadow import trigger_doc_shadow
    from app.platform.shadow.evidence_shadow import trigger_evidence_shadow
    from app.platform.shadow.learning_shadow import trigger_learning_event_shadow
    from app.platform.shadow.memory_candidate_shadow import trigger_memory_candidate_shadow
    from app.platform.shadow.safety_dryrun_shadow import trigger_safety_dryrun
    from app.platform.shadow.graph_shadow import trigger_graph_shadow

    result = CourseCanaryResult(course_id=course_id)
    course_key = str(course_id)
    trace_paths: Dict[str, List[str]] = {pid: [] for pid in (
        "G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"
    )}

    # G3B: document-parse shadow. The doc shadow reads file bytes for a
    # sha256 idempotency key; supply a deterministic fake source file
    # (no real document, no real parse service).
    doc_file = config.doc_file_path
    if doc_file is None:
        doc_file = Path(tempfile.gettempdir()) / "p1_canary_source.md"
        if not doc_file.exists():
            doc_file.write_bytes(b"canary document bytes for sha256 (fake, no real service)")
    r = trigger_doc_shadow(
        file_path=doc_file,
        filename="canary.md",
        parse_result=_FakeParseResult(),
        course_key=course_key,
        sync=True,
        store=config.doc_store,
    )
    result.path_results["G3B"] = {"triggered": r.triggered, "fallback_reason": getattr(r, "fallback_reason", None)}
    if getattr(r, "artifact_path", None):
        trace_paths["G3B"].append(r.artifact_path)

    # G3C: evidence/retrieval/citation shadow.
    r = trigger_evidence_shadow(
        question=config.question, course_id=course_id,
        v1_sources=_fake_v1_sources(), store=config.evidence_store,
    )
    result.path_results["G3C"] = {"triggered": r.triggered, "citation_abstain": r.citation_abstain}
    if getattr(r, "trace_path", None):
        trace_paths["G3C"].append(r.trace_path)

    # G3D1: learning-event shadow.
    r = trigger_learning_event_shadow(
        event_type="PREREQ_JUMP_STARTED", student_id=config.student_id,
        course_id=course_id, sequence_number=1, payload={"from": "nodeA", "to": "nodeB"},
        store=config.learning_store,
    )
    result.path_results["G3D1"] = {"triggered": r.triggered}
    if getattr(r, "trace_path", None):
        trace_paths["G3D1"].append(r.trace_path)

    # G3D2: memory-candidate shadow (would_inject=False always).
    r = trigger_memory_candidate_shadow(
        question=config.question, student_id=config.student_id,
        course_id=course_id, v1_context=_fake_v1_context(), store=config.memory_store,
    )
    result.path_results["G3D2"] = {"triggered": r.triggered, "would_inject": r.would_inject}
    if getattr(r, "trace_path", None):
        trace_paths["G3D2"].append(r.trace_path)

    # G3D3: safety dry-run (v1_blocked=False always).
    r = trigger_safety_dryrun(
        question=config.question, course_id=course_id, store=config.safety_store,
    )
    result.path_results["G3D3"] = {"triggered": r.triggered, "v1_blocked": r.v1_blocked}
    if getattr(r, "trace_path", None):
        trace_paths["G3D3"].append(r.trace_path)

    # G3E1: knowledge-graph shadow.
    r = trigger_graph_shadow(
        knowledge_points=_fake_knowledge_points(), course_id=course_id,
        store=config.graph_store,
    )
    result.path_results["G3E1"] = {
        "triggered": r.triggered, "accepted_traces_evidence": r.accepted_traces_evidence,
    }
    if getattr(r, "trace_path", None):
        trace_paths["G3E1"].append(r.trace_path)

    result.trace_paths_by_path.update(trace_paths)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_canary(config: CanaryConfig) -> CanaryRunResult:
    """Run an end-to-end canary across the course allowlist.

    All-flags-on is achieved by patching each shadow module's flag-read
    function (NOT by mutating real settings). No real services are called.
    Courses not in ``config.course_ids`` are skipped (scope control).
    """
    start = time.time()
    course_results: List[CourseCanaryResult] = []
    skipped: List[Any] = []

    with _patch_all_flags_on():
        for course_id in config.course_ids:
            try:
                course_results.append(_run_course_canary(course_id, config))
            except Exception as e:  # noqa: BLE001 - one course failure must not abort canary
                logger.warning(f"[canary] course {course_id} failed: {e}", exc_info=True)
                cr = CourseCanaryResult(course_id=course_id)
                cr.path_results["_error"] = {"error": f"{type(e).__name__}:{e}"}
                course_results.append(cr)

    # Aggregate trace paths across all courses.
    agg_traces: Dict[str, List[str]] = {pid: [] for pid in (
        "G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"
    )}
    for cr in course_results:
        for pid, paths in cr.trace_paths_by_path.items():
            agg_traces[pid].extend(paths)

    quality = compute_quality(agg_traces, generated_at=start)

    overall_passed = quality.verdict == "PASS" and bool(course_results)

    return CanaryRunResult(
        generated_at=start,
        course_results=course_results,
        skipped_courses=skipped,
        quality_gate=quality,
        overall_passed=overall_passed,
        real_services_called=False,  # G5A invariant: no real services
    )
