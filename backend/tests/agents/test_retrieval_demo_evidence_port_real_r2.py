"""Real R2 integration test for RetrievalDemoEvidencePort field mapping.

Locks the contract between the R2 sidecar provider's hit shape and the
CourseRetrievalPort expected by the LangGraph TeachingAgent. The existing
agents tests use FakeRetrieval (which fabricates the expected fields); this
test wires the REAL ``CourseSidecarR2Provider`` through ``DemoService`` and
``RetrievalDemoEvidencePort`` to prove the adapter no longer returns an empty
list (the prior bug: it read ``evidence_id``/``resource_id``/``page_start``/
``page_end`` from the hit top level, where those names do not exist).
"""
from __future__ import annotations

from pathlib import Path

from app.platform.agents.tools.integration import RetrievalDemoEvidencePort
from app.platform.retrieval_demo.course_provider import CourseSidecarR2Provider
from app.platform.retrieval_demo.service import DemoService
from app.platform.retrieval_demo.store import DemoRunStore
from app.platform.shadow.course_evidence_sidecar import (
    CourseEvidenceSidecarStore,
    build_sidecar,
)


def _document_ir(document_id: str, artifact_id: str) -> dict:
    return {
        "schema_version": "document-ir/1.0",
        "document_id": document_id,
        "artifact_id": artifact_id,
        "source_sha256": "a" * 64,
    }


def _service(tmp_path: Path, *, course_id: str = "101") -> DemoService:
    store = CourseEvidenceSidecarStore(tmp_path / "sidecars")
    store.write(build_sidecar(
        course_id=course_id,
        document_ir=_document_ir(f"doc_{course_id}", f"art_{course_id}"),
        markdown=(
            "# 数据结构\n\n## 第 1 页\n\n二叉树的高度是从根节点到最远叶子节点的路径长度。\n"
            "\n## 第 2 页\n\n数据库事务的隔离级别与二叉树没有关系。"
        ),
    ))
    provider = CourseSidecarR2Provider(store=store, cache_dir=tmp_path / "cache")
    return DemoService(
        configured_mode="demo_compare",
        environment="test",
        provider=provider,
        store=DemoRunStore(tmp_path / "runs"),
    )


def test_real_r2_evidence_port_returns_nonempty_with_contract_fields(tmp_path):
    """The adapter must surface real R2 hits as CourseRetrievalPort evidence."""
    import asyncio
    service = _service(tmp_path)
    port = RetrievalDemoEvidencePort(service)
    evidence = asyncio.run(port.retrieve_course_evidence(
        course_id="101", message="二叉树的高度是什么", concept_id=None, resource_id=None,
    ))
    assert evidence, "real R2 sidecar must yield non-empty evidence (regression: was always [])"
    item = evidence[0]
    # Contract fields expected by the workflow + FakeLLM citation builder.
    assert {"evidence_id", "resource_id", "page_start", "page_end", "text"} <= set(item.keys())
    assert item["evidence_id"], "evidence_id must be non-empty"
    assert isinstance(item["evidence_id"], str) and item["evidence_id"].startswith("ev_")
    assert item["resource_id"] and item["resource_id"].startswith("art_")
    assert item["page_start"] is not None and item["page_end"] == item["page_start"]
    assert item["text"], "text snippet must be non-empty"


def test_real_r2_evidence_port_empty_for_course_without_sidecar(tmp_path):
    """A course with no sidecar must yield [] (no fabricated evidence)."""
    import asyncio
    service = _service(tmp_path, course_id="101")  # only 101 has a sidecar
    port = RetrievalDemoEvidencePort(service)
    evidence = asyncio.run(port.retrieve_course_evidence(
        course_id="999", message="二叉树", concept_id=None, resource_id=None,
    ))
    assert evidence == []
