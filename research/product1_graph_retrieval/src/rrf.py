"""Deterministic Reciprocal Rank Fusion over already course-scoped runs."""

from __future__ import annotations

from typing import Any


RRF_VERSION = "rrf/1.0"


def fuse(query_id: str, course_id: str, sparse: dict[str, Any], dense: dict[str, Any], *, k: int, sparse_weight: float, dense_weight: float, top_k: int) -> dict[str, Any]:
    if sparse["status"] == "abstain" and dense["status"] == "abstain":
        return {"research_query_id": query_id, "status": "abstain", "abstain_reason": "all_retrievers_abstained", "hits": []}
    candidates: dict[str, dict[str, Any]] = {}
    for name, result, weight in (("bm25", sparse, sparse_weight), ("dense", dense, dense_weight)):
        for hit in result.get("hits", []):
            if hit.get("course_id") != course_id:
                raise ValueError("RRF input has cross-course hit")
            chunk_id = hit["research_chunk_id"]
            entry = candidates.setdefault(chunk_id, {"hit": hit, "score": 0.0, "ranks": {}})
            if entry["hit"]["research_evidence_ids"] != hit["research_evidence_ids"]:
                raise ValueError("RRF inputs disagree on evidence closure")
            entry["score"] += weight / (k + hit["rank"])
            entry["ranks"][name] = hit["rank"]
    ranked = sorted(candidates.values(), key=lambda row: (-row["score"], row["hit"]["research_chunk_id"]))[:top_k]
    output = []
    for rank, entry in enumerate(ranked, 1):
        hit = dict(entry["hit"])
        hit["rank"] = rank
        hit["score"] = round(entry["score"], 12)
        hit["feature_trace"] = {"rrf_version": RRF_VERSION, "rrf_k": k, "source_ranks": entry["ranks"], "source_scores": {}}
        output.append(hit)
    return {"research_query_id": query_id, "status": "ok", "hits": output}
