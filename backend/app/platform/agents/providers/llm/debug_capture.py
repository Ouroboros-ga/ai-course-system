"""Local, explicitly enabled raw Prep LLM capture for debugging.

This module is intentionally separate from the durable Agent diagnostics
tables: ordinary diagnostics remain metadata-only.  When a course editor
explicitly enables capture through the debug endpoint, this store keeps the
request messages and raw gateway response on the local development machine so
one failing run can be inspected exactly.  Nothing is logged, sent to a
client by default, or committed to source control.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings
from app.core.time_utils import utcnow_aware


_SAFE_PATH_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


class LocalPrepLLMDebugCaptureStore:
    """Course-scoped local capture controlled by an explicit opt-in state file."""

    def __init__(self, root: Path | None = None) -> None:
        configured = getattr(settings, "PREP_LLM_DEBUG_CAPTURE_DIR", "./temp/prep-llm-debug")
        self._root = Path(root or configured).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def is_enabled(self, course_id: str | int | None) -> bool:
        normalized = _course_id(course_id)
        if normalized is None:
            return False
        return normalized in self._enabled_course_ids()

    def set_enabled(self, *, course_id: str | int, enabled: bool) -> bool:
        normalized = _course_id(course_id)
        if normalized is None:
            raise ValueError("course_id must be a positive integer")
        enabled_courses = self._enabled_course_ids()
        if enabled:
            enabled_courses.add(normalized)
        else:
            enabled_courses.discard(normalized)
        self._write_json_atomic(
            self._state_path,
            {"enabled_course_ids": sorted(enabled_courses)},
        )
        return enabled

    def capture(
        self,
        *,
        course_id: str | int | None,
        run_id: str,
        trace_id: str,
        agent_type: str,
        stage: str,
        purpose: str,
        attempt: int,
        messages: list[Mapping[str, str]],
        response_content: str,
        model: str,
        finish_reason: str,
        usage: Mapping[str, Any] | None,
        requested_max_tokens: int | None,
        temperature: float,
        response_format: Mapping[str, Any] | None,
        provider_options: Mapping[str, Any],
        response_format_fallback: bool,
    ) -> Path | None:
        """Persist one complete request/response only when this course opted in."""
        normalized = _course_id(course_id)
        if normalized is None or not self.is_enabled(normalized):
            return None
        safe_run_id = _safe_segment(run_id or "untracked")
        safe_attempt = max(1, int(attempt or 1))
        path = self._root / f"course-{normalized}" / safe_run_id / f"attempt-{safe_attempt}.json"
        self._write_json_atomic(path, {
            "captured_at": utcnow_aware().isoformat(),
            "course_id": normalized,
            "run_id": run_id,
            "trace_id": trace_id,
            "agent_type": agent_type,
            "stage": stage,
            "purpose": purpose,
            "attempt": safe_attempt,
            "request": {
                "messages": [
                    {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
                    for item in messages
                ],
                "requested_max_tokens": requested_max_tokens,
                "temperature": temperature,
                "response_format": dict(response_format or {}),
                # These options are constructed in code and deliberately do
                # not carry credentials.  Persist them so a debug run proves
                # whether DeepSeek thinking was actually disabled.
                "provider_options": dict(provider_options),
            },
            "response": {
                "content": response_content,
                "model": model,
                "finish_reason": finish_reason,
                "usage": dict(usage or {}),
                "response_format_fallback": bool(response_format_fallback),
            },
        })
        return path

    def read_run(self, *, course_id: str | int, run_id: str) -> list[dict[str, Any]]:
        normalized = _course_id(course_id)
        if normalized is None:
            return []
        run_dir = self._root / f"course-{normalized}" / _safe_segment(run_id)
        if not run_dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(run_dir.glob("attempt-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("course_id") == normalized and payload.get("run_id") == run_id:
                records.append(payload)
        return records

    @property
    def _state_path(self) -> Path:
        return self._root / "capture-state.json"

    def _enabled_course_ids(self) -> set[int]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        raw = payload.get("enabled_course_ids", []) if isinstance(payload, Mapping) else []
        return {course_id for item in raw if (course_id := _course_id(item)) is not None}

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(temporary, path)


def _course_id(value: str | int | None) -> int | None:
    try:
        normalized = int(str(value))
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _safe_segment(value: str) -> str:
    normalized = _SAFE_PATH_SEGMENT.sub("_", str(value)).strip("._")
    return normalized[:128] or "untracked"


prep_llm_debug_capture_store = LocalPrepLLMDebugCaptureStore()


__all__ = ["LocalPrepLLMDebugCaptureStore", "prep_llm_debug_capture_store"]
