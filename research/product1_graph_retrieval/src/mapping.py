"""Deterministic B-R2 knowledge-point to PPT-slide mapping over R0 BM25."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .bm25 import BM25Index
from .chapter_distance import chapter_distance
from .tokenizer import normalize_search_text, tokenize


MAPPING_VERSION = "title-bm25-chapter/1.0"


def _dice(left: set[str], right: set[str]) -> float:
    return 0.0 if not left or not right else 2.0 * len(left & right) / (len(left) + len(right))


def title_match(knowledge_point: dict[str, Any], slide: dict[str, Any]) -> float:
    """Use only fixture-provided title strings, never inferred text or qrels."""

    title = slide.get("title", "")
    if not title.strip():
        return 0.0
    normalized_title = normalize_search_text(title).strip()
    labels = [knowledge_point["canonical_label"], *knowledge_point.get("aliases", [])]
    score = 0.0
    title_tokens = set(tokenize(title))
    for label in labels:
        if normalize_search_text(label).strip() == normalized_title:
            return 1.0
        score = max(score, _dice(set(tokenize(label)), title_tokens))
    return score


class KnowledgePointSlideMapper:
    """One course-local slide index per course using the frozen R0 BM25 class."""

    def __init__(
        self,
        slides: Iterable[dict[str, Any]],
        evidence: Iterable[dict[str, Any]],
        *,
        k1: float,
        b: float,
        title_weight: float,
        bm25_weight: float,
        chapter_weight: float,
    ) -> None:
        if round(title_weight + bm25_weight + chapter_weight, 12) != 1.0:
            raise ValueError("mapping feature weights must sum exactly to 1")
        evidence_by_id = {row["research_evidence_id"]: row for row in evidence}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.slides: dict[str, dict[str, Any]] = {}
        for slide in slides:
            refs = list(slide.get("research_evidence_ids", []))
            linked = [evidence_by_id.get(reference) for reference in refs]
            if not refs or any(item is None or item.get("status") != "active" for item in linked):
                continue
            if any(item["course_id"] != slide["course_id"] for item in linked if item):
                continue
            # This adapter changes only the document identity field.  Tokenization
            # and BM25 scoring remain the R0 implementation unchanged.
            document = dict(slide)
            document["research_chunk_id"] = slide["research_slide_id"]
            document["text"] = slide.get("body_text", "")
            grouped[slide["course_id"]].append(document)
            self.slides[slide["research_slide_id"]] = slide
        self.evidence_by_id = evidence_by_id
        self.indexes = {
            course_id: BM25Index(course_id, docs, k1=k1, b=b)
            for course_id, docs in sorted(grouped.items())
        }
        self.weights = {"title_match": title_weight, "normalized_bm25": bm25_weight, "chapter_proximity": chapter_weight}

    def map(self, knowledge_point: dict[str, Any], *, top_k: int) -> dict[str, Any]:
        course_id = knowledge_point["course_id"]
        index = self.indexes.get(course_id)
        if index is None:
            return {
                "research_knowledge_point_id": knowledge_point["research_knowledge_point_id"],
                "status": "abstain",
                "abstain_reason": "scope_not_available",
                "slides": [],
            }
        ranked_bm25 = index.search(knowledge_point["canonical_label"], top_k=index.document_count)
        raw_scores = {item.chunk["research_slide_id"]: item.score for item in ranked_bm25}
        maximum = max(raw_scores.values(), default=0.0)
        candidates: list[dict[str, Any]] = []
        for document in index.chunks:
            slide_id = document["research_slide_id"]
            slide = self.slides[slide_id]
            raw_bm25 = raw_scores.get(slide_id, 0.0)
            normalized_bm25 = 0.0 if maximum == 0.0 else raw_bm25 / maximum
            distance = chapter_distance(
                knowledge_point.get("chapter_path"),
                slide.get("chapter_path"),
                left_document_id=knowledge_point.get("document_id"),
                right_document_id=slide.get("document_id"),
                left_page=knowledge_point.get("source_page_start"),
                right_page=slide.get("slide_number"),
            )
            features = {
                "title_match": title_match(knowledge_point, slide),
                "normalized_bm25": normalized_bm25,
                "chapter_proximity": distance.proximity,
            }
            score = sum(self.weights[name] * value for name, value in features.items())
            candidates.append({
                "slide": slide,
                "score": score,
                "raw_bm25": raw_bm25,
                "features": features,
                "chapter_distance": distance,
            })
        candidates.sort(key=lambda item: (-item["score"], item["slide"]["research_slide_id"]))
        if not candidates or candidates[0]["score"] == 0.0:
            return {
                "research_knowledge_point_id": knowledge_point["research_knowledge_point_id"],
                "status": "abstain",
                "abstain_reason": "no_mapping_signal",
                "slides": [],
            }
        output: list[dict[str, Any]] = []
        for rank, candidate in enumerate(candidates[:top_k], 1):
            slide, distance = candidate["slide"], candidate["chapter_distance"]
            refs = list(slide["research_evidence_ids"])
            output.append(
                {
                    "rank": rank,
                    "research_slide_id": slide["research_slide_id"],
                    "course_id": course_id,
                    "slide_number": slide["slide_number"],
                    "research_evidence_ids": refs,
                    "score": round(candidate["score"], 12),
                    "feature_trace": {
                        **{name: round(value, 12) for name, value in candidate["features"].items()},
                        "raw_bm25": round(candidate["raw_bm25"], 12),
                        "chapter_distance_basis": distance.basis,
                        "chapter_distance": distance.distance,
                        "chapter_distance_missing": distance.missing,
                    },
                    "citations": [
                        {
                            "research_evidence_id": evidence_id,
                            "citation_key": self.evidence_by_id[evidence_id]["citation_key"],
                            "artifact_id": self.evidence_by_id[evidence_id]["artifact_id"],
                            "block_id": self.evidence_by_id[evidence_id]["block_id"],
                            "page_or_slide": self.evidence_by_id[evidence_id]["page_or_slide"],
                        }
                        for evidence_id in refs
                    ],
                }
            )
        return {"research_knowledge_point_id": knowledge_point["research_knowledge_point_id"], "status": "ok", "slides": output}
