"""Course-scoped DocumentIR -> Evidence sidecar for test-environment shadow retrieval.

The store is deliberately independent from the production ORM.  It receives
only the already-parsed markdown and the DocumentIR identity emitted by the
document shadow, then writes one immutable, course-scoped JSON snapshot.  No
research fixture, qrels, LLM, vector service, or V1 retrieval state is read.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SIDECAR_SCHEMA_VERSION = "test-course-evidence-sidecar/1.0"
DEFAULT_SIDECAR_ROOT = os.environ.get("P1_TEST_COURSE_EVIDENCE_ROOT", "./p1_shadow_course_evidence")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_course_id(course_id: Any) -> str:
    value = str(course_id).strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("course_id must be a stable, path-safe identifier")
    return value


def _citation_key(*, artifact_id: str, block_id: str, char_start: int, char_end: int) -> str:
    return "cite_" + _sha256(f"{artifact_id}:{block_id}:{char_start}:{char_end}")[:24]


def _page_blocks(markdown: str, *, document_id: str, artifact_id: str) -> list[dict[str, Any]]:
    """Split parsed markdown into deterministic page/slide blocks.

    The V1 parser marks slide content with ``第 N 页`` headings.  Non-slide
    material remains a single page-1 block, which is still explicitly
    traceable rather than pretending a page coordinate exists.
    """
    page_heading = re.compile(r"^#{1,6}\s*第\s*(\d+)\s*页.*$", re.MULTILINE)
    matches = list(page_heading.finditer(markdown))
    sections: list[tuple[int, str]] = []
    if matches:
        for index, match in enumerate(matches):
            page = int(match.group(1))
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            text = markdown[match.end():end].strip()
            if text:
                sections.append((page, text))
    elif markdown.strip():
        sections.append((1, markdown.strip()))

    blocks: list[dict[str, Any]] = []
    for ordinal, (page, text) in enumerate(sections, 1):
        block_id = "blk_" + _sha256(f"{document_id}:{page}:{ordinal}:{_sha256(text)}")[:24]
        unit_id = f"unit_{page:04d}_{ordinal:02d}"
        blocks.append({
            "unit_id": unit_id,
            "block_id": block_id,
            "page_or_slide": page,
            "text": text,
            "text_sha256": _sha256(text),
            "artifact_id": artifact_id,
            "document_id": document_id,
        })
    return blocks


def build_sidecar(*, course_id: Any, document_ir: dict[str, Any], markdown: str) -> dict[str, Any]:
    """Create a closed Evidence/corpus snapshot from one parsed course document."""
    course = _safe_course_id(course_id)
    document_id = str(document_ir.get("document_id") or "").strip()
    artifact_id = str(document_ir.get("artifact_id") or "").strip()
    if not document_id or not artifact_id:
        raise ValueError("DocumentIR must provide document_id and artifact_id")
    blocks = _page_blocks(markdown, document_id=document_id, artifact_id=artifact_id)
    evidence: list[dict[str, Any]] = []
    corpus: list[dict[str, Any]] = []
    for block in blocks:
        evidence_id = "ev_" + _sha256(f"{course}:{block['block_id']}:0:{len(block['text'])}")[:24]
        citation_key = _citation_key(
            artifact_id=artifact_id,
            block_id=block["block_id"],
            char_start=0,
            char_end=len(block["text"]),
        )
        evidence_row = {
            "evidence_id": evidence_id,
            "course_id": course,
            "artifact_id": artifact_id,
            "document_id": document_id,
            "unit_id": block["unit_id"],
            "block_id": block["block_id"],
            "page_or_slide": block["page_or_slide"],
            "char_start": 0,
            "char_end": len(block["text"]),
            "text_snippet": block["text"],
            "text_sha256": block["text_sha256"],
            "citation_key": citation_key,
            "status": "active",
        }
        evidence.append(evidence_row)
        corpus.append({
            "chunk_id": "chk_" + _sha256(f"{course}:{block['block_id']}:{evidence_id}")[:24],
            "course_id": course,
            "artifact_id": artifact_id,
            "document_id": document_id,
            "unit_id": block["unit_id"],
            "block_id": block["block_id"],
            "page_or_slide": block["page_or_slide"],
            "text": block["text"],
            "text_sha256": block["text_sha256"],
            "evidence_ids": [evidence_id],
        })
    snapshot = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "source_kind": "document_ir_shadow_parse_result",
        "course_id": course,
        "document_id": document_id,
        "artifact_id": artifact_id,
        "document_ir_schema_version": document_ir.get("schema_version"),
        "source_sha256": document_ir.get("source_sha256"),
        "evidence": evidence,
        "corpus": corpus,
    }
    snapshot["content_sha256"] = _sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return snapshot


class CourseEvidenceSidecarStore:
    """Atomic course-scoped sidecar storage with no ORM dependency."""

    def __init__(self, root: str | Path = DEFAULT_SIDECAR_ROOT) -> None:
        self.root = Path(root)

    def _path(self, course_id: Any) -> Path:
        return self.root / f"course_{_safe_course_id(course_id)}.json"

    def write(self, snapshot: dict[str, Any]) -> Path:
        course = _safe_course_id(snapshot.get("course_id"))
        if snapshot.get("schema_version") != SIDECAR_SCHEMA_VERSION:
            raise ValueError("unsupported sidecar schema")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(course)
        descriptor, name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            Path(name).replace(target)
        finally:
            temporary = Path(name)
            if temporary.exists():
                temporary.unlink()
        return target

    def read_course(self, course_id: Any) -> dict[str, Any] | None:
        path = self._path(course_id)
        if not path.is_file():
            return None
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if snapshot.get("schema_version") != SIDECAR_SCHEMA_VERSION:
            raise ValueError("unsupported sidecar schema")
        if snapshot.get("course_id") != _safe_course_id(course_id):
            raise ValueError("sidecar course scope mismatch")
        return snapshot

    def find_document(self, document_id: str) -> dict[str, Any] | None:
        for path in sorted(self.root.glob("course_*.json")) if self.root.exists() else []:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if snapshot.get("document_id") == document_id:
                return snapshot
        return None

    def course_ids(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(sorted(
            path.stem.removeprefix("course_") for path in self.root.glob("course_*.json")
        ))
