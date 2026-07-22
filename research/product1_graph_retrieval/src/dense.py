"""Local, exact-cosine R1 dense retrieval; no vector service or vector database."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_json_bytes, sha256_bytes, sha256_file


DENSE_VERSION = "local-exact-cosine/1.0"


class BgeSmallZhEmbedder:
    """Minimal offline BGE encoder with fixed local files and CLS pooling."""

    def __init__(self, model_dir: Path, *, max_length: int, query_instruction: str) -> None:
        # Target-installed torch needs torchgen import first on this Windows/Python
        # runtime. Both imports are local and no model request is made.
        import torchgen  # noqa: F401
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.max_length = max_length
        self.query_instruction = query_instruction
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self.model = AutoModel.from_pretrained(str(model_dir), local_files_only=True)
        self.model.eval()

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.query_instruction + text for text in texts])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with self.torch.inference_mode():
            for offset in range(0, len(texts), 32):
                batch = self.tokenizer(texts[offset : offset + 32], padding=True, truncation=True, max_length=self.max_length, return_tensors="pt")
                output = self.model(**batch).last_hidden_state[:, 0]
                output = self.torch.nn.functional.normalize(output, p=2, dim=1)
                vectors.extend(output.cpu().tolist())
        return vectors


def model_file_manifest(model_dir: Path) -> dict[str, str]:
    required = ("config.json", "tokenizer.json", "model.safetensors")
    result = {}
    for name in required:
        path = model_dir / name
        if not path.is_file():
            raise ValueError(f"local dense model file missing: {name}")
        result[name] = f"sha256:{sha256_file(path)}"
    return result


class CourseDenseRetriever:
    def __init__(self, corpus: Iterable[dict[str, Any]], evidence: Iterable[dict[str, Any]], *, embedder: Any, cache_path: Path, cache_key: dict[str, Any]) -> None:
        self.evidence_by_id = {row["research_evidence_id"]: row for row in evidence}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for chunk in corpus:
            refs = chunk.get("research_evidence_ids", [])
            linked = [self.evidence_by_id.get(reference) for reference in refs]
            if refs and all(item and item.get("status") == "active" and item["course_id"] == chunk["course_id"] for item in linked):
                grouped[chunk["course_id"]].append(chunk)
        self.chunks = {course_id: sorted(rows, key=lambda row: row["research_chunk_id"]) for course_id, rows in grouped.items()}
        self.embedder = embedder
        self.cache_path = cache_path
        self.cache_key = cache_key
        self.vectors = self._load_or_embed()

    def _load_or_embed(self) -> dict[str, list[list[float]]]:
        expected_ids = {course: [row["research_chunk_id"] for row in rows] for course, rows in self.chunks.items()}
        if self.cache_path.is_file():
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") == self.cache_key and cached.get("chunk_ids") == expected_ids:
                return cached["vectors"]
        vectors = {course: self.embedder.encode_documents([row["text"] for row in rows]) for course, rows in self.chunks.items()}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_bytes(canonical_json_bytes({"cache_key": self.cache_key, "chunk_ids": expected_ids, "vectors": vectors}))
        return vectors

    def retrieve(self, query: dict[str, Any], *, top_k: int, minimum_cosine: float) -> dict[str, Any]:
        course_id, query_id = query["course_id"], query["research_query_id"]
        chunks, vectors = self.chunks.get(course_id), self.vectors.get(course_id)
        if not chunks or not vectors:
            return {"research_query_id": query_id, "status": "abstain", "abstain_reason": "scope_not_available", "hits": []}
        query_vector = self.embedder.encode_queries([query["text"]])[0]
        scored = [(sum(left * right for left, right in zip(query_vector, vector)), chunk) for vector, chunk in zip(vectors, chunks)]
        scored = [(score, chunk) for score, chunk in scored if score >= minimum_cosine]
        scored.sort(key=lambda item: (-item[0], item[1]["research_chunk_id"]))
        if not scored:
            return {"research_query_id": query_id, "status": "abstain", "abstain_reason": "below_dense_threshold", "hits": []}
        hits = []
        for rank, (score, chunk) in enumerate(scored[:top_k], 1):
            refs = list(chunk["research_evidence_ids"])
            hits.append({
                "rank": rank,
                "research_chunk_id": chunk["research_chunk_id"],
                "course_id": course_id,
                "page_or_slide": chunk["page_or_slide"],
                "block_id": chunk["block_id"],
                "research_evidence_ids": refs,
                "score": round(score, 12),
                "citations": [{"research_evidence_id": ref, "citation_key": self.evidence_by_id[ref]["citation_key"], "artifact_id": self.evidence_by_id[ref]["artifact_id"], "block_id": self.evidence_by_id[ref]["block_id"], "page_or_slide": self.evidence_by_id[ref]["page_or_slide"]} for ref in refs],
                "feature_trace": {"dense_version": DENSE_VERSION, "cosine_similarity": round(score, 12)},
            })
        return {"research_query_id": query_id, "status": "ok", "hits": hits}


def cache_identity(*, fixture_manifest_sha256: str, model: dict[str, Any], max_length: int, query_instruction: str) -> dict[str, Any]:
    return {"dense_version": DENSE_VERSION, "fixture_manifest_sha256": fixture_manifest_sha256, "model": model, "pooling": "cls", "normalization": "l2", "max_length": max_length, "query_instruction": query_instruction}


def cache_filename(identity: dict[str, Any]) -> str:
    return f"dense_{sha256_bytes(canonical_json_bytes(identity))}.json"
