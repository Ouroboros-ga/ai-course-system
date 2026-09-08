"""TeachingAgent adapter over CS discipline references (R14 + CR4).

两层来源经**同一版本化检索服务**提供补充参考（CR4）：
- 概念层（``discipline_kb``）：本地精编 JSON（112 节点/106 关系），
  书目来源可追溯但无逐句证据——``authority_label`` 如实标注，不称
  "教材级权威"；
- 语料层（``discipline_corpus``）：``search_corpus_unified`` 按已发布
  head 版本检索（``CorpusSearchService``），无已发布版本时回退旧索引
  路径（legacy，结果无版本语义，调用方不得冒充版本化引用）。

契约（AGENTS.md §4.1.5 / §5.1）：
- 每条结果 ``is_supplementary=True``，无 ``evidence_id``——P1-E1 引用闭包
  （``validate_response`` 只认课程 evidence_id）不受影响；
- 语料块带 ``reference_id``（``{release_id}:{chunk_id}``）与 ``release_id``，
  供回答声明实际引用（``used_discipline_reference_ids``，仅限本次返回）；
- ``node_id`` 命名空间分离：语料块的 ``node_id`` 恒为空，禁止拿
  ``chunk_id`` 去调 ``/nodes/{node_id}``；
- 审计只记录引用身份与计数（见 workflow），正文不进 audit。
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.platform.knowledge import discipline_kb

#: 未知来源不全称"教材"：按 source_kind 的诚实标签。
_SOURCE_AUTHORITY_LABELS = {
    "textbook": "开放教材",
    "zhwiki": "维基百科（CC BY-SA）",
    "enwiki": "维基百科（CC BY-SA）",
    "rfc": "RFC（IETF）",
    "arxiv": "arXiv 论文（研究层）",
}

_CONCEPT_AUTHORITY_LABEL = "精编概念（书目来源）"


def authority_label_for(source_kind: str) -> str:
    """按来源的诚实标签；未知来源原样返回，不全称教材。"""
    kind = str(source_kind or "").strip()
    if not kind:
        return "未知来源"
    return _SOURCE_AUTHORITY_LABELS.get(kind, kind)


def _corpus_embed_client():
    """版本化检索的向量客户端：loopback 服务；未配置即 None（词法降级）。"""
    from app.core.config import settings

    url = str(getattr(settings, "CORPUS_EMBEDDING_URL", "") or "").strip()
    if not url:
        return None
    from app.platform.knowledge.corpus_embedding import HttpEmbedClient

    return HttpEmbedClient(base_url=url)


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
        # 语料原文级补充（CR4 版本化统一检索）：失败/无版本时静默降级为空，
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
                "result_type": "concept",
                "name": str(item.get("name") or ""),
                "course": str(item.get("course") or ""),
                "node_type": str(item.get("node_type") or "concept"),
                "definition": str(item.get("definition") or ""),
                "key_points": [str(p) for p in (item.get("key_points") or [])][:5],
                "example": str(item.get("example") or ""),
                "source_title": str(source.get("title") or ""),
                "source_authors": str(source.get("authors") or ""),
                "source_chapter": str(source.get("chapter") or ""),
                "authority_label": _CONCEPT_AUTHORITY_LABEL,
                "retrieval_source": "discipline_kb",
                "is_supplementary": True,
            })
        return refs

    async def _search_corpus_layer(self, query: str) -> list[dict[str, Any]]:
        try:
            from app.models import database
            from app.models.database import session_factory
            from app.platform.knowledge.discipline_corpus import (
                search_corpus_unified,
            )

            client = _corpus_embed_client()

            def _run():
                try:
                    with session_factory() as session:
                        return search_corpus_unified(
                            session, query, top_k=6, embed_client=client)
                finally:
                    # 文件型 SQLite + 常驻连接池会在 Windows 上锁住库文件
                    # （冷路径低频调用，释放空闲连接；PG 等不受影响）。
                    try:
                        url = str(getattr(database, "DATABASE_URL", ""))
                        if url.startswith("sqlite:///") and ":memory:" not in url:
                            database.engine.dispose()
                    except Exception:  # noqa: BLE001 - 连接释放失败不影响结果
                        pass

            result = await asyncio.to_thread(_run)
        except Exception:  # noqa: BLE001 - 语料层检索失败不影响概念层结果
            return []
        if not isinstance(result, dict) or result.get("status") == "unavailable":
            return []
        release_id = str(result.get("release_id") or "")
        refs: list[dict[str, Any]] = []
        for item in result.get("results") or []:
            if not isinstance(item, dict):
                continue
            refs.append({
                "node_id": "",
                "result_type": "corpus_chunk",
                "name": str(item.get("title") or ""),
                "course": "",
                "node_type": "corpus_paragraph",
                "definition": str(item.get("snippet") or ""),
                "context_text": str(item.get("context_text") or ""),
                "key_points": [],
                "example": "",
                "reference_id": str(item.get("reference_id") or ""),
                "release_id": release_id,
                "chunk_id": str(item.get("chunk_id") or ""),
                "chunk_no": int(item.get("chunk_no") or 0),
                "doc_id": str(item.get("doc_id") or ""),
                "section_path": str(item.get("section_path") or ""),
                "source_kind": str(item.get("source_kind") or ""),
                "source_url": str(item.get("source_url") or ""),
                "matched_by": [str(m) for m in (item.get("matched_by") or [])],
                "source_title": str(item.get("title") or ""),
                "source_authors": "",
                "source_chapter": str(item.get("section_path") or ""),
                "source_license": str(item.get("license") or ""),
                "authority_label": authority_label_for(item.get("source_kind")),
                "retrieval_source": "discipline_corpus",
                "is_supplementary": True,
            })
        return refs


__all__ = ["DisciplineKnowledgePortImpl", "authority_label_for"]
