"""Isolated file store for approved KG-MEST Shadow reports.

This is the supply side that ``build_kg_mest_shadow_sidecar_runtime`` reads
from so the TeachingAgent can be enabled without an operator hand-passing a
``dict``. Reports are produced offline by the ``product1_cognition`` research
bundle (or an operator) and placed in this store; the TeachingAgent only
reads them.

Design rules (mirrors ``CourseEvidenceSidecarStore``):
- Isolated directory (default ``./p1_kg_mest_reports``, configurable via the
  ``P1_KG_MEST_REPORT_ROOT`` env var). No ORM, no V1 DB, no production tables.
- Path-traversal safe: student_id / course_id must match ``[A-Za-z0-9_-]{1,64}``.
- Atomic writes (tmp file + replace).
- Each report is keyed by ``(student_id, course_id)`` -- one report per
  student/course pair. The bound scope is enforced on write and re-checked on
  read so a report can never be served to a different student or course.
- Does NOT import any research module; the report is opaque JSON here. The
  ``KGMetShadowReportStudentModelingPort`` adapter validates the consumable
  shape (``status``/``course_key``/``states``/``recommendations``) at inject
  time.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_REPORT_ROOT = os.environ.get("P1_KG_MEST_REPORT_ROOT", "./p1_kg_mest_reports")

_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _safe_id(value: Any) -> str:
    text = str(value).strip()
    if not text or not _SAFE_ID.fullmatch(text):
        raise ValueError("student_id/course_id must be a stable, path-safe identifier")
    return text


def _filename(student_id: str, course_id: str) -> str:
    return f"report_{student_id}__{course_id}.json"


class KGMestShadowReportStore:
    """Atomic, scope-bound store for one KG-MEST Shadow report per student/course."""

    def __init__(self, root: str | Path = DEFAULT_REPORT_ROOT) -> None:
        self.root = Path(root)

    def _path(self, student_id: str, course_id: str) -> Path:
        return self.root / _filename(student_id, course_id)

    def write(self, *, student_id: Any, course_id: Any, report: dict[str, Any]) -> Path:
        """Persist one approved report. Validates status + course binding.

        Raises ``ValueError`` if the report is not an accepted read-only
        result (``status != "ok"``) or its ``course_key`` does not match the
        injected ``course_id`` (scope binding must be established at write
        time, not silently at read time).
        """
        student = _safe_id(student_id)
        course = _safe_id(course_id)
        if report.get("status") != "ok":
            raise ValueError("KG-MEST Shadow report is not an accepted read-only result (status != ok)")
        if str(report.get("course_key", "")) != course:
            raise ValueError("KG-MEST Shadow report course_key does not match the injected course_id scope")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(student, course)
        descriptor, name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(report, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            Path(name).replace(target)
        finally:
            temporary = Path(name)
            if temporary.exists():
                temporary.unlink()
        return target

    def read(self, student_id: Any, course_id: Any) -> dict[str, Any] | None:
        """Read one report for the exact (student_id, course_id) pair.

        Returns ``None`` when no report exists. Re-checks the scope binding so
        a renamed/moved file can never leak across students or courses.
        """
        student = _safe_id(student_id)
        course = _safe_id(course_id)
        path = self._path(student, course)
        if not path.is_file():
            return None
        report = json.loads(path.read_text(encoding="utf-8"))
        if str(report.get("course_key", "")) != course:
            return None
        return report

    def list_reports(self) -> list[tuple[str, str]]:
        """List every stored (student_id, course_id) pair, sorted."""
        if not self.root.exists():
            return []
        pairs: list[tuple[str, str]] = []
        for path in sorted(self.root.glob("report_*__*.json")):
            stem = path.stem  # report_<student>__<course>
            body = stem[len("report_"):]
            if "__" not in body:
                continue
            student, course = body.split("__", 1)
            if _SAFE_ID.fullmatch(student) and _SAFE_ID.fullmatch(course):
                pairs.append((student, course))
        return pairs
