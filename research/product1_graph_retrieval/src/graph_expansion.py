"""Constrained one-hop graph expansion over an immutable course snapshot.

This is a retrieval ablation, not GraphRAG.  It deliberately follows only the
accepted ``PPTSlide -> ScriptNode`` structural relation.  A seed chunk is
anchored to its own slide by its frozen page value, then one graph edge may
surface other active chunks from that same slide.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


GRAPH_EXPANSION_VERSION = "one-hop-structural/1.0"


class OneHopStructuralExpander:
    """Expand a frozen R2 run without accessing query labels or qrels."""

    def __init__(self, *, corpus: Iterable[dict[str, Any]], evidence: Iterable[dict[str, Any]], nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]]) -> None:
        self.evidence = {row["research_evidence_id"]: row for row in evidence if row.get("status") == "active"}
        self.chunks = {}
        for row in corpus:
            refs = row.get("research_evidence_ids", [])
            if refs and all(reference in self.evidence and self.evidence[reference]["course_id"] == row["course_id"] for reference in refs):
                self.chunks[row["research_chunk_id"]] = row

        node_index = {row["node_id"]: row for row in nodes}
        self.slide_nodes = {
            (row["course_id"], row["properties"].get("slide_number")): row["node_id"]
            for row in nodes
            if row.get("node_type") == "PPTSlide"
        }
        self.script_block_by_node = {
            row["node_id"]: row["source_id"]
            for row in nodes
            if row.get("node_type") == "ScriptNode"
        }
        chunks_by_block: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in self.chunks.values():
            chunks_by_block[(row["course_id"], row["block_id"])].append(row)
        self.chunks_by_block = {key: sorted(value, key=lambda item: item["research_chunk_id"]) for key, value in chunks_by_block.items()}

        adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            subject = node_index.get(edge.get("subject_node_id"))
            object_ = node_index.get(edge.get("object_node_id"))
            if (
                edge.get("status") == "accepted"
                and edge.get("predicate") == "MAPPED_TO"
                and edge.get("source") == "slide_block_structure"
                and subject and subject.get("node_type") == "PPTSlide"
                and object_ and object_.get("node_type") == "ScriptNode"
                and subject.get("course_id") == edge.get("course_id") == object_.get("course_id")
                and set(edge.get("research_evidence_ids", [])) <= set(self.evidence)
            ):
                adjacency[edge["subject_node_id"]].append(edge)
        self.adjacency = {key: sorted(value, key=lambda item: (self.script_block_by_node[item["object_node_id"]], item["edge_id"])) for key, value in adjacency.items()}

    def _hit_from_chunk(self, *, chunk: dict[str, Any], score: float, seed: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
        refs = list(chunk["research_evidence_ids"])
        return {
            "research_chunk_id": chunk["research_chunk_id"],
            "course_id": chunk["course_id"],
            "page_or_slide": chunk["page_or_slide"],
            "block_id": chunk["block_id"],
            "research_evidence_ids": refs,
            "score": round(score, 12),
            "citations": [
                {
                    "research_evidence_id": reference,
                    "citation_key": self.evidence[reference]["citation_key"],
                    "artifact_id": self.evidence[reference]["artifact_id"],
                    "block_id": self.evidence[reference]["block_id"],
                    "page_or_slide": self.evidence[reference]["page_or_slide"],
                }
                for reference in refs
            ],
            "feature_trace": {
                "graph_expansion_version": GRAPH_EXPANSION_VERSION,
                "relation": "PPTSlide-MAPPED_TO-ScriptNode",
                "graph_edge_id": edge["edge_id"],
                "seed_research_chunk_id": seed["research_chunk_id"],
                "seed_rank": seed["rank"],
                "seed_score": seed["score"],
            },
        }

    def expand(self, query: dict[str, Any], baseline: dict[str, Any], *, seed_k: int, relation_budget_per_seed: int, graph_candidate_budget: int, final_candidate_k: int, score_decay: float) -> dict[str, Any]:
        """Return a fixed-size, deterministic R3 candidate list.

        Baseline R2 hits retain their scores.  New graph candidates receive a
        score derived from their seed only; this makes the structural increment
        inspectable rather than pretending it supplies semantic relevance.
        """
        query_id, course_id = query["research_query_id"], query["course_id"]
        if baseline.get("status") == "abstain":
            return {"research_query_id": query_id, "status": "abstain", "abstain_reason": "r2_abstained", "hits": []}
        base_hits = baseline.get("hits", [])
        if any(hit.get("course_id") != course_id for hit in base_hits):
            raise ValueError("R3 source has cross-course hit")
        candidates: dict[str, dict[str, Any]] = {hit["research_chunk_id"]: dict(hit) for hit in base_hits}
        expanded: dict[str, dict[str, Any]] = {}
        for seed in base_hits[:seed_k]:
            slide_node_id = self.slide_nodes.get((course_id, seed.get("page_or_slide")))
            if not slide_node_id:
                continue
            for edge in self.adjacency.get(slide_node_id, [])[:relation_budget_per_seed]:
                block_id = self.script_block_by_node[edge["object_node_id"]]
                for chunk in self.chunks_by_block.get((course_id, block_id), []):
                    chunk_id = chunk["research_chunk_id"]
                    if chunk_id in candidates:
                        continue
                    hit = self._hit_from_chunk(chunk=chunk, score=float(seed["score"]) * score_decay, seed=seed, edge=edge)
                    old = expanded.get(chunk_id)
                    if old is None or (-hit["score"], hit["feature_trace"]["seed_research_chunk_id"], hit["feature_trace"]["graph_edge_id"]) < (-old["score"], old["feature_trace"]["seed_research_chunk_id"], old["feature_trace"]["graph_edge_id"]):
                        expanded[chunk_id] = hit
        graph_hits = sorted(expanded.values(), key=lambda item: (-item["score"], item["research_chunk_id"]))[:graph_candidate_budget]
        candidates.update({hit["research_chunk_id"]: hit for hit in graph_hits})
        ranked = sorted(candidates.values(), key=lambda item: (-item["score"], item["research_chunk_id"]))[:final_candidate_k]
        for rank, hit in enumerate(ranked, 1):
            hit["rank"] = rank
        return {"research_query_id": query_id, "status": "ok", "hits": ranked}
