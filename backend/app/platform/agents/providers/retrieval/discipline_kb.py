"""TeachingAgent adapter over the CS discipline knowledge base (R14).

The discipline KB is a local, read-only, textbook-sourced JSON knowledge layer
(``app.platform.knowledge.discipline_kb``). This port exposes it to the
teaching workflow as **supplementary references**:

- every result is marked ``is_supplementary=True`` and ``retrieval_source="discipline_kb"``;
- results carry their authoritative source (title/authors/chapter) for traceability;
- results deliberately have **no** ``evidence_id`` — the P1-E1 citation closure
  (``validate_response`` filters citations to the course evidence set) stays
  intact, so discipline references can ground the answer but never masquerade
  as formal course citations (AGENTS.md §4.1.5).
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.platform.knowledge import discipline_kb


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


__all__ = ["DisciplineKnowledgePortImpl"]
