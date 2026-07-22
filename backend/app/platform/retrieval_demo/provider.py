"""Adapter that executes the frozen R2 BM25 + local BGE + RRF research path.

This module is purposefully not registered in the normal retrieval gateway.
It is loaded only by the Shadow-1 demo router and reads public fixture inputs
only; qrels, query labels, R3 expansion, external vector services, and LLMs
are not imported or called.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_ROOT = PROJECT_ROOT / "research" / "product1_graph_retrieval"
FIXTURE_DIR = RESEARCH_ROOT / "datasets" / "reviewed_silver_v0_2"
GRAPH_DIR = RESEARCH_ROOT / "graphs" / "reviewed_silver_v0_2_snapshot_r0_m0"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ResearchR2Provider:
    """Lazy, course-filtered provider over the immutable Reviewed Silver fixture."""

    def __init__(self, *, fixture_dir: Path = FIXTURE_DIR, graph_dir: Path = GRAPH_DIR, cache_dir: Path | None = None) -> None:
        self.fixture_dir = Path(fixture_dir)
        self.graph_dir = Path(graph_dir)
        self.cache_dir = Path(cache_dir or (RESEARCH_ROOT / "runtime" / "demo_embedding_cache"))
        self._ready = False
        self._bm25: Any = None
        self._dense: Any = None
        self._fuse: Any = None
        self._metadata: dict[str, Any] = {}
        self._chunks: dict[str, dict[str, Any]] = {}
        self._queries: list[dict[str, Any]] = []
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self._course_ids = tuple(_json(self.fixture_dir / "manifest.json")["course_ids"])

    @property
    def course_ids(self) -> tuple[str, ...]:
        return self._course_ids

    @property
    def metadata(self) -> dict[str, Any]:
        self._load_metadata()
        return dict(self._metadata)

    def _load_metadata(self) -> None:
        if self._metadata:
            return
        r0_config = _json(RESEARCH_ROOT / "configs" / "r0_bm25_reviewed_silver_v0_2.json")
        r1_config = _json(RESEARCH_ROOT / "configs" / "r1_dense_bge_small_zh_v1_5_reviewed_silver_v0_2.json")
        r2_config = _json(RESEARCH_ROOT / "configs" / "r2_rrf_reviewed_silver_v0_2.json")
        snapshot = _json(self.graph_dir / "snapshot.json")
        sys.path.insert(0, str(RESEARCH_ROOT)) if str(RESEARCH_ROOT) not in sys.path else None
        from src.canonical import canonical_json_bytes, sha256_bytes
        from src.fixture_io import manifest_sha256

        self._metadata = {
            "fixture_id": "reviewed_silver_v0_2",
            "fixture_manifest_sha256": manifest_sha256(self.fixture_dir),
            "dataset_level": "reviewed_silver",
            "evaluation_eligibility": "reviewed_silver_offline_research_only",
            "r0_bm25": r0_config["bm25"],
            "r0_candidate_k": r0_config["candidate_k"],
            "r1_candidate_k": r1_config["candidate_k"],
            "r1_minimum_cosine": r1_config["minimum_cosine"],
            "r2_config_sha256": sha256_bytes(canonical_json_bytes(r2_config)),
            "r2_candidate_k": r2_config["candidate_k"],
            "rrf": r2_config["rrf"],
            "model": {
                "repo_id": r1_config["model"]["repo_id"],
                "revision": r1_config["model"]["revision"],
                "model_safetensors_sha256": r1_config["model"]["model_safetensors_sha256"],
                "pooling": r1_config["model"]["pooling"],
                "normalization": r1_config["model"]["normalization"],
            },
            "graph_content_sha256": snapshot["graph_content_sha256"],
            "accepted_graph_predicates": snapshot["accepted_predicates"],
            "r3_graph_expansion_called": False,
        }

    def _bootstrap(self) -> None:
        if self._ready:
            return
        self._load_metadata()
        self._load_static_data()
        sys.path.insert(0, str(RESEARCH_ROOT)) if str(RESEARCH_ROOT) not in sys.path else None
        from src.bm25 import CourseBM25Retriever
        from src.canonical import sha256_file
        from src.dense import BgeSmallZhEmbedder, CourseDenseRetriever, cache_filename, cache_identity, model_file_manifest
        from src.fixture_io import manifest_sha256
        from src.rrf import fuse

        r0_config = _json(RESEARCH_ROOT / "configs" / "r0_bm25_reviewed_silver_v0_2.json")
        r1_config = _json(RESEARCH_ROOT / "configs" / "r1_dense_bge_small_zh_v1_5_reviewed_silver_v0_2.json")
        r2_config = _json(RESEARCH_ROOT / "configs" / "r2_rrf_reviewed_silver_v0_2.json")
        if len({r0_config["candidate_k"], r1_config["candidate_k"], r2_config["candidate_k"]}) != 1:
            raise RuntimeError("frozen R0/R1/R2 candidate budgets disagree")
        corpus, evidence = _jsonl(self.fixture_dir / "corpus.jsonl"), _jsonl(self.fixture_dir / "evidence.jsonl")
        model = r1_config["model"]
        model_dir = PROJECT_ROOT / model["local_dir"]
        files = model_file_manifest(model_dir)
        if files["model.safetensors"] != f"sha256:{model['model_safetensors_sha256']}":
            raise RuntimeError("local BGE model weight hash mismatch")
        identity = cache_identity(
            fixture_manifest_sha256=manifest_sha256(self.fixture_dir),
            model={"repo_id": model["repo_id"], "revision": model["revision"], "files": files},
            max_length=model["max_length"],
            query_instruction=model["query_instruction"],
        )
        embedder = BgeSmallZhEmbedder(model_dir, max_length=model["max_length"], query_instruction=model["query_instruction"])
        self._bm25 = CourseBM25Retriever(
            corpus,
            evidence,
            k1=r0_config["bm25"]["k1"],
            b=r0_config["bm25"]["b"],
        )
        self._dense = CourseDenseRetriever(
            corpus,
            evidence,
            embedder=embedder,
            cache_path=self.cache_dir / cache_filename(identity),
            cache_key=identity,
        )
        self._fuse = fuse
        self._metadata["model_files"] = files
        self._metadata["embedding_cache_sha256"] = f"sha256:{sha256_file(self.cache_dir / cache_filename(identity))}"
        self._ready = True

    def _load_static_data(self) -> None:
        """Load public fixture/snapshot data without loading the Dense model."""
        if self._chunks:
            return
        corpus = _jsonl(self.fixture_dir / "corpus.jsonl")
        self._chunks = {row["research_chunk_id"]: row for row in corpus}
        self._queries = _jsonl(self.fixture_dir / "queries.jsonl")
        self._nodes, self._edges = _jsonl(self.graph_dir / "nodes.jsonl"), _jsonl(self.graph_dir / "edges.jsonl")

    def retrieve(self, *, course_id: str, question: str) -> dict[str, Any]:
        """Run exactly R0 + R1 + R2 after validating course scope first."""
        if course_id not in self.course_ids:
            return {"status": "abstain", "abstain_reason": "course_not_available", "hits": []}
        self._bootstrap()
        from src.identities import research_query_id

        query = {"research_query_id": research_query_id(course_id=course_id, text=question), "course_id": course_id, "text": question}
        top_k = int(self._metadata["r2_candidate_k"])
        sparse = self._bm25.retrieve(query, top_k=top_k)
        dense = self._dense.retrieve(
            query,
            top_k=top_k,
            minimum_cosine=float(self._metadata["r1_minimum_cosine"]),
        )
        rrf = self._metadata["rrf"]
        result = self._fuse(query["research_query_id"], course_id, sparse, dense, k=rrf["k"], sparse_weight=rrf["bm25_weight"], dense_weight=rrf["dense_weight"], top_k=top_k)
        for hit in result.get("hits", []):
            chunk = self._chunks[hit["research_chunk_id"]]
            hit["text_snippet"] = chunk["text"][:480]
        return result

    def presets(self, course_id: str, *, limit: int = 6) -> list[dict[str, str]]:
        if course_id not in self.course_ids:
            return []
        self._load_static_data()
        return [
            {"research_query_id": row["research_query_id"], "text": row["text"], "query_stratum": row["query_stratum"]}
            for row in sorted((row for row in self._queries if row["course_id"] == course_id), key=lambda row: row["research_query_id"])[:limit]
        ]

    def graph_snapshot(self, course_id: str) -> dict[str, Any]:
        if course_id not in self.course_ids:
            return {"nodes": [], "edges": [], "accepted_predicates": [], "graph_content_sha256": self.metadata["graph_content_sha256"]}
        self._load_metadata()
        self._load_static_data()
        node_ids = {row["node_id"] for row in self._nodes if row["course_id"] == course_id}
        return {
            "nodes": [row for row in self._nodes if row["node_id"] in node_ids],
            "edges": [row for row in self._edges if row["subject_node_id"] in node_ids and row["object_node_id"] in node_ids and row["status"] == "accepted"],
            "accepted_predicates": self.metadata["accepted_graph_predicates"],
            "graph_content_sha256": self.metadata["graph_content_sha256"],
            "graph_kind": "deterministic_research_graph_not_production_graphrag",
        }
