"""R2 adapter over test-course DocumentIR/Evidence sidecars.

Unlike the retired fixture provider, this adapter never opens Reviewed Silver,
qrels, query labels, or a production database.  It turns the active Evidence
sidecar of a requested course into the frozen R0+R1+R2 representations and
checks citation closure before returning a hit.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from app.platform.shadow.course_evidence_sidecar import CourseEvidenceSidecarStore


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_ROOT = PROJECT_ROOT / "research" / "product1_graph_retrieval"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class CourseSidecarR2Provider:
    """Exact local BM25 + BGE Dense + RRF over one course sidecar at a time."""

    def __init__(self, *, store: CourseEvidenceSidecarStore | None = None, cache_dir: Path | None = None) -> None:
        self.store = store or CourseEvidenceSidecarStore()
        self.cache_dir = Path(cache_dir or (self.store.root / "embedding-cache"))
        self._loaded_content_sha: str | None = None
        self._loaded_course: str | None = None
        self._bm25: Any = None
        self._dense: Any = None
        self._fuse: Any = None
        self._chunks: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, Any] = {}

    @property
    def course_ids(self) -> tuple[str, ...]:
        return self.store.course_ids()

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "data_source": "test_course_documentir_evidence_sidecar",
            "sidecar_schema_version": "test-course-evidence-sidecar/1.0",
            "course_ids": list(self.course_ids),
            "r3_graph_expansion_called": False,
            **self._metadata,
        }

    @staticmethod
    def _adapt(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evidence = []
        for row in snapshot.get("evidence", []):
            if row.get("status") != "active":
                continue
            evidence.append({**row, "research_evidence_id": row["evidence_id"]})
        active = {row["research_evidence_id"] for row in evidence}
        corpus = []
        for row in snapshot.get("corpus", []):
            refs = list(row.get("evidence_ids", []))
            if refs and all(ref in active for ref in refs):
                corpus.append({
                    **row,
                    "research_chunk_id": row["chunk_id"],
                    "research_evidence_ids": refs,
                })
        if not corpus:
            raise ValueError("sidecar has no active evidence-closed chunks")
        return corpus, evidence

    def _bootstrap(self, course_id: str) -> None:
        snapshot = self.store.read_course(course_id)
        if snapshot is None:
            raise KeyError("course_sidecar_not_available")
        content_sha = str(snapshot.get("content_sha256") or "")
        if self._loaded_course == course_id and self._loaded_content_sha == content_sha:
            return
        if str(RESEARCH_ROOT) not in sys.path:
            sys.path.insert(0, str(RESEARCH_ROOT))
        from src.bm25 import CourseBM25Retriever
        from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file
        from src.dense import BgeSmallZhEmbedder, CourseDenseRetriever, cache_filename, cache_identity, model_file_manifest
        from src.rrf import fuse

        corpus, evidence = self._adapt(snapshot)
        r0 = _json(RESEARCH_ROOT / "configs" / "r0_bm25_reviewed_silver_v0_2.json")
        r1 = _json(RESEARCH_ROOT / "configs" / "r1_dense_bge_small_zh_v1_5_reviewed_silver_v0_2.json")
        r2 = _json(RESEARCH_ROOT / "configs" / "r2_rrf_reviewed_silver_v0_2.json")
        model = r1["model"]
        model_dir = PROJECT_ROOT / model["local_dir"]
        files = model_file_manifest(model_dir)
        if files["model.safetensors"] != f"sha256:{model['model_safetensors_sha256']}":
            raise RuntimeError("local BGE model weight hash mismatch")
        identity = cache_identity(
            fixture_manifest_sha256=f"sidecar:{content_sha}",
            model={"repo_id": model["repo_id"], "revision": model["revision"], "files": files},
            max_length=model["max_length"],
            query_instruction=model["query_instruction"],
        )
        embedder = BgeSmallZhEmbedder(model_dir, max_length=model["max_length"], query_instruction=model["query_instruction"])
        self._bm25 = CourseBM25Retriever(corpus, evidence, k1=r0["bm25"]["k1"], b=r0["bm25"]["b"])
        self._dense = CourseDenseRetriever(
            corpus, evidence, embedder=embedder,
            cache_path=self.cache_dir / cache_filename(identity), cache_key=identity,
        )
        self._fuse = fuse
        self._chunks = {row["research_chunk_id"]: row for row in corpus}
        self._loaded_course, self._loaded_content_sha = course_id, content_sha
        self._metadata = {
            "course_id": course_id,
            "sidecar_content_sha256": content_sha,
            "r2_config_sha256": sha256_bytes(canonical_json_bytes(r2)),
            "model": {"repo_id": model["repo_id"], "revision": model["revision"], "model_safetensors_sha256": model["model_safetensors_sha256"]},
        }

    def retrieve(self, *, course_id: str, question: str) -> dict[str, Any]:
        if course_id not in self.course_ids:
            return {"status": "abstain", "abstain_reason": "course_sidecar_not_available", "hits": []}
        self._bootstrap(course_id)
        query_id = "q_" + hashlib.sha256(f"{course_id}:{question}".encode("utf-8")).hexdigest()[:24]
        query = {"research_query_id": query_id, "course_id": course_id, "text": question}
        sparse = self._bm25.retrieve(query, top_k=50)
        dense = self._dense.retrieve(query, top_k=50, minimum_cosine=0.0)
        result = self._fuse(query_id, course_id, sparse, dense, k=60, sparse_weight=1.0, dense_weight=1.0, top_k=10)
        for hit in result.get("hits", []):
            if hit.get("course_id") != course_id or not hit.get("citations"):
                raise ValueError("sidecar retrieval citation closure failed")
            chunk = self._chunks[hit["research_chunk_id"]]
            hit["text_snippet"] = chunk["text"][:480]
            hit["source_kind"] = "test_course_documentir_evidence_sidecar"
        return result

    def presets(self, course_id: str, *, limit: int = 6) -> list[dict[str, str]]:
        return []

    def graph_snapshot(self, course_id: str) -> dict[str, Any]:
        return {"nodes": [], "edges": [], "graph_kind": "disabled_not_a_production_retrieval_candidate"}
