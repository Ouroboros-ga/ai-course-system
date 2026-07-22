"""Deterministic, course-scoped BM25 index used only by offline R0 research."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .tokenizer import TOKENIZER_VERSION, tokenize, unique_query_terms


BM25_VERSION = "course-bm25/1.0"


@dataclass(frozen=True)
class ScoredChunk:
    chunk: dict[str, Any]
    score: float
    matched_terms: tuple[str, ...]


class BM25Index:
    """An immutable sparse index.  Its constructor never mixes courses."""

    def __init__(self, course_id: str, chunks: Iterable[dict[str, Any]], *, k1: float, b: float) -> None:
        if not isinstance(k1, (int, float)) or k1 <= 0:
            raise ValueError("k1 must be positive")
        if not isinstance(b, (int, float)) or not 0 <= b <= 1:
            raise ValueError("b must be in [0, 1]")
        self.course_id, self.k1, self.b = course_id, float(k1), float(b)
        self.chunks = tuple(sorted(chunks, key=lambda row: row["research_chunk_id"]))
        if any(row.get("course_id") != course_id for row in self.chunks):
            raise ValueError("a BM25Index may contain exactly one course")
        self.term_frequencies: dict[str, Counter[str]] = {}
        self.document_lengths: dict[str, int] = {}
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)
        for chunk in self.chunks:
            chunk_id = chunk["research_chunk_id"]
            frequencies = Counter(tokenize(chunk["text"]))
            self.term_frequencies[chunk_id] = frequencies
            self.document_lengths[chunk_id] = sum(frequencies.values())
            for term, frequency in frequencies.items():
                self.postings[term][chunk_id] = frequency
        self.document_count = len(self.chunks)
        self.average_document_length = (
            sum(self.document_lengths.values()) / self.document_count if self.document_count else 0.0
        )
        self._chunk_by_id = {row["research_chunk_id"]: row for row in self.chunks}

    def _idf(self, document_frequency: int) -> float:
        return math.log(1.0 + (self.document_count - document_frequency + 0.5) / (document_frequency + 0.5))

    def search(self, query_text: str, *, top_k: int) -> list[ScoredChunk]:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if not self.document_count:
            return []
        scores: dict[str, float] = defaultdict(float)
        matched: dict[str, list[str]] = defaultdict(list)
        for term in unique_query_terms(query_text):
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = self._idf(len(posting))
            for chunk_id, term_frequency in posting.items():
                length = self.document_lengths[chunk_id]
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length / self.average_document_length
                )
                scores[chunk_id] += idf * term_frequency * (self.k1 + 1) / denominator
                matched[chunk_id].append(term)
        ranked = [
            ScoredChunk(self._chunk_by_id[chunk_id], score, tuple(matched[chunk_id]))
            for chunk_id, score in scores.items()
            if score > 0.0
        ]
        ranked.sort(key=lambda item: (-item.score, item.chunk["research_chunk_id"]))
        return ranked[:top_k]


class CourseBM25Retriever:
    """Build one index per course and return closed evidence/citation hits."""

    def __init__(self, corpus: Iterable[dict[str, Any]], evidence: Iterable[dict[str, Any]], *, k1: float, b: float) -> None:
        evidence_by_id = {row["research_evidence_id"]: row for row in evidence}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for chunk in corpus:
            references = chunk.get("research_evidence_ids", [])
            linked = [evidence_by_id.get(reference) for reference in references]
            if not references or any(row is None or row.get("status") != "active" for row in linked):
                continue
            if any(row["course_id"] != chunk.get("course_id") for row in linked if row):
                continue
            grouped[chunk["course_id"]].append(chunk)
        self.evidence_by_id = evidence_by_id
        self.indexes = {
            course_id: BM25Index(course_id, chunks, k1=k1, b=b)
            for course_id, chunks in sorted(grouped.items())
        }
        self.k1, self.b = float(k1), float(b)

    def retrieve(self, query: dict[str, Any], *, top_k: int) -> dict[str, Any]:
        query_id, course_id = query["research_query_id"], query["course_id"]
        index = self.indexes.get(course_id)
        if index is None:
            return {
                "research_query_id": query_id,
                "status": "abstain",
                "abstain_reason": "scope_not_available",
                "hits": [],
            }
        candidates = index.search(query["text"], top_k=top_k)
        if not candidates:
            return {
                "research_query_id": query_id,
                "status": "abstain",
                "abstain_reason": "no_positive_bm25_match",
                "hits": [],
            }
        hits: list[dict[str, Any]] = []
        for rank, candidate in enumerate(candidates, 1):
            chunk = candidate.chunk
            refs = list(chunk["research_evidence_ids"])
            citations = []
            for evidence_id in refs:
                source = self.evidence_by_id[evidence_id]
                citations.append(
                    {
                        "research_evidence_id": evidence_id,
                        "citation_key": source["citation_key"],
                        "artifact_id": source["artifact_id"],
                        "document_id": source["document_id"],
                        "unit_id": source["unit_id"],
                        "block_id": source["block_id"],
                        "page_or_slide": source["page_or_slide"],
                    }
                )
            hits.append(
                {
                    "rank": rank,
                    "research_chunk_id": chunk["research_chunk_id"],
                    "course_id": course_id,
                    "page_or_slide": chunk["page_or_slide"],
                    "block_id": chunk["block_id"],
                    "research_evidence_ids": refs,
                    "score": round(candidate.score, 12),
                    "citations": citations,
                    "feature_trace": {
                        "tokenizer_version": TOKENIZER_VERSION,
                        "matched_terms": list(candidate.matched_terms),
                    },
                }
            )
        return {"research_query_id": query_id, "status": "ok", "hits": hits}
