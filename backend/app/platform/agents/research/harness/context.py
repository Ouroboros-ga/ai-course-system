"""Bounded context selection, chunking and compression for ResearchAgent."""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s*")


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    kind: str
    content: str
    sequence: int = 0
    importance: float = 0.5


@dataclass(frozen=True)
class PreparedContext:
    selected_chunks: tuple[str, ...]
    selected_item_ids: tuple[str, ...]
    dropped_item_ids: tuple[str, ...]
    summary: str
    estimated_tokens: int
    budget_tokens: int
    compressed: bool
    compression_method: str

    @property
    def text(self) -> str:
        sections = list(self.selected_chunks)
        if self.summary:
            sections.append(f"压缩摘要：{self.summary}")
        return "\n\n".join(sections)


class ContextSummarizer(Protocol):
    async def summarize(
        self,
        *,
        query: str,
        texts: Sequence[str],
        max_chars: int,
    ) -> str: ...


class ExtractiveContextSummarizer:
    """A deterministic fallback that never invents facts."""

    async def summarize(
        self,
        *,
        query: str,
        texts: Sequence[str],
        max_chars: int,
    ) -> str:
        if max_chars <= 0:
            return ""
        query_terms = _terms(query)
        candidates: list[tuple[float, int, str]] = []
        position = 0
        for text in texts:
            for sentence in _SENTENCE_SPLIT.split(text.strip()):
                normalized = sentence.strip()
                if not normalized:
                    continue
                score = _relevance(query_terms, _terms(normalized))
                candidates.append((score, -position, normalized))
                position += 1
        candidates.sort(reverse=True)
        selected: list[str] = []
        used = 0
        for _, _, sentence in candidates:
            addition = sentence if not selected else f"；{sentence}"
            if used + len(addition) > max_chars:
                remaining = max_chars - used
                if remaining > 8:
                    selected.append(addition[:remaining])
                break
            selected.append(addition)
            used += len(addition)
        return "".join(selected)


@dataclass(frozen=True)
class _ScoredChunk:
    item: ContextItem
    text: str
    chunk_index: int
    score: float
    tokens: int


class ResearchContextManager:
    """Prepare a relevance-ranked context that never exceeds its budget."""

    def __init__(
        self,
        *,
        max_tokens: int = 4_000,
        chunk_chars: int = 1_200,
        chunk_overlap: int = 120,
        preserve_recent: int = 2,
        summarizer: ContextSummarizer | None = None,
    ) -> None:
        if max_tokens < 32:
            raise ValueError("max_tokens must be at least 32")
        if chunk_chars < 16 or chunk_overlap < 0 or chunk_overlap >= chunk_chars:
            raise ValueError("chunk size/overlap is invalid")
        self.max_tokens = max_tokens
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap
        self.preserve_recent = max(0, preserve_recent)
        self._summarizer = summarizer or ExtractiveContextSummarizer()

    @property
    def summarizer(self) -> ContextSummarizer:
        """Expose the immutable summarizer strategy for request-local managers."""

        return self._summarizer

    def chunk_text(self, text: str) -> list[str]:
        normalized = str(text or "")
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + self.chunk_chars, len(normalized))
            chunks.append(normalized[start:end])
            if end >= len(normalized):
                break
            start = end - self.chunk_overlap
        return chunks

    async def prepare(
        self,
        *,
        query: str,
        items: Sequence[ContextItem],
    ) -> PreparedContext:
        query_terms = _terms(query)
        chunks: list[_ScoredChunk] = []
        for item in items:
            for index, text in enumerate(self.chunk_text(item.content)):
                score = _relevance(query_terms, _terms(text))
                score += max(0.0, min(1.0, item.importance)) * 0.2
                chunks.append(_ScoredChunk(
                    item=item,
                    text=text,
                    chunk_index=index,
                    score=score,
                    tokens=_estimate_tokens(text),
                ))

        total_tokens = sum(chunk.tokens for chunk in chunks)
        if total_tokens <= self.max_tokens:
            return PreparedContext(
                selected_chunks=tuple(chunk.text for chunk in chunks),
                selected_item_ids=_unique(chunk.item.item_id for chunk in chunks),
                dropped_item_ids=(),
                summary="",
                estimated_tokens=total_tokens,
                budget_tokens=self.max_tokens,
                compressed=False,
                compression_method="none",
            )

        recent_ids = {
            item.item_id
            for item in sorted(items, key=lambda candidate: candidate.sequence, reverse=True)[
                : self.preserve_recent
            ]
        }
        raw_budget = max(16, math.floor(self.max_tokens * 0.72))
        ranked = sorted(
            chunks,
            key=lambda chunk: (
                chunk.item.item_id in recent_ids,
                chunk.score,
                chunk.item.sequence,
                -chunk.chunk_index,
            ),
            reverse=True,
        )
        selected: list[_ScoredChunk] = []
        used_tokens = 0
        for chunk in ranked:
            if used_tokens + chunk.tokens > raw_budget:
                continue
            selected.append(chunk)
            used_tokens += chunk.tokens

        # A tiny budget can otherwise select nothing. Keep a bounded prefix of
        # the most relevant chunk so the caller always receives useful context.
        if not selected and ranked:
            best = ranked[0]
            max_chars = max(1, raw_budget * 3)
            clipped = best.text[:max_chars]
            selected.append(_ScoredChunk(
                item=best.item,
                text=clipped,
                chunk_index=best.chunk_index,
                score=best.score,
                tokens=_estimate_tokens(clipped),
            ))
            used_tokens = selected[0].tokens

        selected_keys = {(chunk.item.item_id, chunk.chunk_index) for chunk in selected}
        dropped = [
            chunk for chunk in chunks
            if (chunk.item.item_id, chunk.chunk_index) not in selected_keys
        ]
        remaining_tokens = max(0, self.max_tokens - used_tokens)
        max_summary_chars = remaining_tokens * 3
        summary = await self._summarizer.summarize(
            query=query,
            texts=[chunk.text for chunk in dropped],
            max_chars=max_summary_chars,
        )
        summary = summary[:max_summary_chars]
        estimated = used_tokens + _estimate_tokens(summary)
        if estimated > self.max_tokens:
            overflow = estimated - self.max_tokens
            summary = summary[: max(0, len(summary) - overflow * 3)]
            estimated = used_tokens + _estimate_tokens(summary)

        selected.sort(key=lambda chunk: (chunk.item.sequence, chunk.chunk_index))
        return PreparedContext(
            selected_chunks=tuple(chunk.text for chunk in selected),
            selected_item_ids=_unique(chunk.item.item_id for chunk in selected),
            dropped_item_ids=_unique(chunk.item.item_id for chunk in dropped),
            summary=summary,
            estimated_tokens=min(estimated, self.max_tokens),
            budget_tokens=self.max_tokens,
            compressed=True,
            compression_method="extractive",
        )


def _terms(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(str(text or ""))}


def _relevance(query_terms: set[str], content_terms: set[str]) -> float:
    if not query_terms or not content_terms:
        return 0.0
    overlap = query_terms & content_terms
    return len(overlap) / len(query_terms)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 3))


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values))


__all__ = [
    "ContextItem",
    "ContextSummarizer",
    "ExtractiveContextSummarizer",
    "PreparedContext",
    "ResearchContextManager",
]
