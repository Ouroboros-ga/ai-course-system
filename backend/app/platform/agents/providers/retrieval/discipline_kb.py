"""TeachingAgent adapter over the CS discipline knowledge base (R14).

The discipline KB is a local, read-only, textbook-sourced JSON knowledge layer
(``app.platform.knowledge.discipline_kb``). This port exposes it to the
teaching workflow as **supplementary references**:

- every result is marked ``is_supplementary=True``;
- concept-layer results carry ``retrieval_source="discipline_kb"`` and their
  authoritative source (title/authors/chapter) for traceability;
- corpus-layer results (RAG 检索白名单接入, 2026-09-01) carry
  ``retrieval_source="discipline_corpus"`` and paragraph-level fields
  (``doc_id``/``chunk_no``/``snippet``/``source_license``); they are only
  returned when ``DISCIPLINE_CORPUS_INDEX_PATH`` points to a built index
  (fail-closed, never fabricated);
- results deliberately have **no** ``evidence_id`` — the P1-E1 citation closure
  (``validate_response`` filters citations to the course evidence set) stays
  intact, so discipline references can ground the answer but never masquerade
  as formal course citations (AGENTS.md §4.1.5).
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.platform.knowledge import discipline_corpus, discipline_kb


class DisciplineKnowledgePortImpl:
    """Read-only wrapper; module-level JSON cache makes it cheap and stateless."""

    async def search_discipline_knowledge(
        self,
        *,
        course_id: str,
        message: str,
        concept_id: str | None,
        top_k: int = 3,
    ) -> list[Mapping[str, Any]]:
        query = str(message or "").strip()
        if not query:
            return []
        refs: list[dict[str, Any]] = await self._search_concept_layer(query, top_k)
        # 语料段落级补充（RAG 白名单）：未配置索引/检索失败时静默降级为空，
        # 概念层结果不受影响。
        refs.extend(await self._search_corpus_layer(query))
        return refs

    async def _search_concept_layer(self, query: str, top_k: int) -> list[dict[str, Any]]:
        try:
            # concept_id 是课程内图谱节点（kn_*），与学科 KB 的 dm-/ds- 等 id
            # 不在同一命名空间，直接检索消息本身；概念名已在消息/候选中体现。
            items = await asyncio.to_thread(discipline_kb.search_nodes, query, top_k=max(1, top_k))
        except Exception:  # noqa: BLE001 - 补充参考检索失败不得阻断问答主链路
            return []
        refs: list[dict[str, Any]] = []
        for item in items:
            source = dict(item.get("source") or {})
            refs.append({
                "node_id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "course": str(item.get("course") or ""),
                "node_type": str(item.get("node_type") or "concept"),
                "definition": str(item.get("definition") or ""),
                "key_points": [str(p) for p in (item.get("key_points") or [])][:5],
                "example": str(item.get("example") or ""),
                "source_title": str(source.get("title") or ""),
                "source_authors": str(source.get("authors") or ""),
                "source_chapter": str(source.get("chapter") or ""),
                "retrieval_source": "discipline_kb",
                "is_supplementary": True,
            })
        return refs

    async def _search_corpus_layer(self, query: str) -> list[dict[str, Any]]:
        try:
            items = await asyncio.to_thread(discipline_corpus.search_corpus, query)
        except Exception:  # noqa: BLE001 - 语料层检索失败不影响概念层结果
            return []
        refs: list[dict[str, Any]] = []
        for item in items:
            refs.append({
                "node_id": "",
                "name": str(item.get("title") or ""),
                "course": "",
                "node_type": "corpus_paragraph",
                "definition": str(item.get("snippet") or ""),
                "key_points": [],
                "example": "",
                "doc_id": str(item.get("doc_id") or ""),
                "chunk_no": int(item.get("chunk_no") or 0),
                "source_title": str(item.get("book") or item.get("source") or ""),
                "source_authors": "",
                "source_chapter": "",
                "source_license": str(item.get("license") or ""),
                "retrieval_source": "discipline_corpus",
                "is_supplementary": True,
            })
        return refs


__all__ = ["DisciplineKnowledgePortImpl"]
