"""Read-only TeachingAgent adapters over the active CourseKnowledgeBundle."""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from fastapi import HTTPException
from sqlmodel import select

from app.models.course_outline_model import CourseOutlineNode
from app.models.database import session_factory
from app.models.graph_production_model import CourseKnowledgeNode
from app.platform.knowledge.sql_lance_provider import SqlLanceCourseKnowledgeProvider
from app.services.course_access_service import resolve_course_access

from ...errors import ScopeRejectedError, ServiceUnavailableError


def _shares_keyword(left: str, right: str, min_span: int = 4) -> bool:
    """Return True when two titles share a meaningful character span.

    Outlines whose knowledge_graph_node_id mapping is empty fall back to title
    matching.  ``min_span=4`` rejects coincidental short overlaps and single
    noise characters (e.g. the graph node titled "的").
    """
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    n = len(shorter)
    if n < min_span:
        return False
    for size in range(min(n, 16), min_span - 1, -1):
        for i in range(n - size + 1):
            if shorter[i:i + size] in longer:
                return True
    return False


class ActiveBundleScopePort:
    """Fail-closed Course Access v1 gate for non-HTTP agent invocations."""

    async def validate_scope(
        self,
        *,
        student_id: str,
        course_id: str,
        resource_id: str | None,
    ) -> Mapping[str, Any]:
        try:
            user_id = int(student_id)
            course = _course_id(course_id)
            with session_factory() as session:
                access = resolve_course_access(
                    session,
                    {"user_id": user_id},
                    course,
                )
                allowed = (
                    access.allows("knowledge.view")
                    and access.allows("course.citation.read")
                )
        except (TypeError, ValueError, HTTPException):
            allowed = False
        if not allowed:
            raise ScopeRejectedError("course knowledge scope rejected")
        return {
            "allowed": True,
            "source": "course_access_v1",
            "resource_id": resource_id,
        }


class ActiveBundleKnowledgeGraphPort:
    def __init__(self, provider=None) -> None:
        self._provider = provider or SqlLanceCourseKnowledgeProvider()

    async def resolve_concepts(
        self,
        *,
        course_id: str,
        message: str,
        candidates: list[Mapping[str, Any]],
        resource_id: str | None,
    ) -> list[Mapping[str, Any]]:
        course = _course_id(course_id)
        graph = await asyncio.to_thread(self._provider.get_graph, course)
        if graph is None:
            raise ServiceUnavailableError("active course knowledge bundle pending")
        lowered = message.casefold()

        def _title(node: Mapping[str, Any]) -> str:
            return str(node.get("title") or node.get("label") or "").casefold()

        # 1) 当前学习位置（resource_id）是强先验：学生的问题通常指"这里/当前知识点"。
        #    此前实现完全忽略 resource_id，纯文本匹配失败后回退语义检索，
        #    会把"请问这里涉及到的数学模型是什么？"解析到噪声节点（如名称为"的"），
        #    导致智能体不知道自己正在讲解的知识点（2026-08-18 修复）。
        #    outline→图谱映射缺失的课程（knowledge_graph_node_id 为空）用标题关键词回退。
        resource_nodes: list[Mapping[str, Any]] = []
        if resource_id:
            resource_key, outline_title = await asyncio.to_thread(
                self._resource_id_and_outline_title, course, str(resource_id)
            )
            if resource_key:
                resource_nodes = [
                    node for node in graph.nodes
                    if str(node.get("id")) == resource_key
                ]
            elif outline_title:
                resource_nodes = [
                    node for node in graph.nodes
                    if _shares_keyword(outline_title, _title(node))
                ]

        # 2) 消息明确点名：节点标题完整出现在问题中（如"传递函数是什么"）。
        #    单字标题（如源文本切分产生的"的"）几乎出现在所有中文消息里，
        #    不构成点名，必须排除，否则会把"这里"误解析到噪声节点。
        named_nodes = [
            node for node in graph.nodes
            if len(_title(node)) >= 2 and _title(node) in lowered
        ]
        candidate_names = {
            str(item.get("name") or "").casefold() for item in candidates
        }
        # 3) 候选名匹配：候选名是图谱节点标题的子串即命中（学生说"传递函数"，
        #    图谱标题"一、 传递函数的定义和主要性质"应命中），而非仅精确相等。
        candidate_nodes = [
            node for node in graph.nodes
            if len(_title(node)) >= 2
            and any(name and name in _title(node) for name in candidate_names)
            and node not in named_nodes
            and node not in resource_nodes
        ]

        # 4) 选择顺序：明确点名 > 当前学习位置 > 候选名。
        #    学生明确点名某知识点时以点名优先（他想去那里）；否则默认停留在
        #    当前学习位置，避免"这里/这个公式"等指代被误解析到其他节点。
        if named_nodes:
            ordered: list[Mapping[str, Any]] = []
            for node in (*named_nodes, *resource_nodes, *candidate_nodes):
                if node not in ordered:
                    ordered.append(node)
        else:
            ordered = [*resource_nodes, *candidate_nodes]
            seen: set[str] = set()
            deduped: list[Mapping[str, Any]] = []
            for node in ordered:
                key = str(node.get("id"))
                if key not in seen:
                    seen.add(key)
                    deduped.append(node)
            ordered = deduped

        if not ordered and message.strip():
            result = await asyncio.to_thread(
                self._provider.search_evidence,
                course,
                message,
                top_k=6,
            )
            if result is not None:
                matched_keys = {
                    item.node_key for item in result.items if item.node_key
                }
                # 回退检索同样排除单字噪声标题（如"的"），避免把指代解析到噪声节点。
                ordered = [
                    node for node in graph.nodes
                    if str(node.get("id")) in matched_keys
                    and len(_title(node)) >= 2
                ]
        return [{
            "concept_id": str(node["id"]),
            "name": node.get("title") or node.get("label") or node["id"],
            "confidence": 0.9,
            "bundle_id": graph.bundle.bundle_id,
            "graph_snapshot_id": graph.bundle.graph_snapshot_id,
        } for node in ordered[:12]]

    @staticmethod
    def _resource_id_and_outline_title(
        course: int, resource_id: str
    ) -> tuple[str | None, str | None]:
        """Resolve a browser resource id to (graph node key, outline title).

        The learning page sends the current outline node id (``on_*``) as
        ``resource_id``; graph node keys (``kn_*``) and legacy numeric ids are
        also accepted.  Outlines whose knowledge_graph_node_id mapping is empty
        (data gap) return the outline title for keyword fallback.
        """
        if resource_id.startswith("kn_"):
            return resource_id, None
        with session_factory() as session:
            if resource_id.isdigit():
                node = session.exec(
                    select(CourseKnowledgeNode).where(
                        CourseKnowledgeNode.course_id == course,
                        CourseKnowledgeNode.id == int(resource_id),
                    )
                ).first()
                return (node.node_key if node else None), None
            outline = session.exec(
                select(CourseOutlineNode).where(
                    CourseOutlineNode.course_id == course,
                    CourseOutlineNode.outline_node_id == resource_id,
                )
            ).first()
            if outline is None:
                return None, None
            if outline.knowledge_graph_node_id:
                return outline.knowledge_graph_node_id, None
            return None, (outline.title or "")[:64] or None
        return None, None

    async def get_context(
        self,
        *,
        course_id: str,
        concept_id: str,
    ) -> Mapping[str, Any]:
        course = _course_id(course_id)
        node = await asyncio.to_thread(self._provider.get_node, course, concept_id)
        bundle = await asyncio.to_thread(self._provider.get_active_bundle, course)
        if node is None or bundle is None:
            raise ServiceUnavailableError("active course knowledge node unavailable")
        return {
            "bundle_id": bundle.bundle_id,
            "graph_snapshot_id": bundle.graph_snapshot_id,
            "concept_id": node.node_key,
            "knowledge_node_id": node.knowledge_node_id,
            "name": node.title,
            "description": node.description,
            "prerequisites": [{"concept_id": item} for item in node.prerequisites],
            "successors": [{"concept_id": item} for item in node.successors],
            "citation_ids": list(node.citation_ids),
        }


class ActiveBundleCourseRetrievalPort:
    def __init__(self, provider=None) -> None:
        self._provider = provider or SqlLanceCourseKnowledgeProvider()

    async def retrieve_course_evidence(
        self,
        *,
        course_id: str,
        message: str,
        concept_id: str | None,
        resource_id: str | None,
    ) -> list[Mapping[str, Any]]:
        course = _course_id(course_id)
        result = await asyncio.to_thread(
            self._provider.search_evidence,
            course,
            message,
            top_k=6,
            node_keys=(concept_id,) if concept_id else (),
        )
        if result is None:
            return []
        return [{
            "evidence_id": item.evidence_ids[0] if item.evidence_ids else None,
            "resource_id": item.document_id,
            "page_start": item.page_number,
            "page_end": item.page_number,
            "text": item.content,
            "node_key": item.node_key,
            "knowledge_node_id": item.knowledge_node_id,
            "citation_ids": list(item.citation_ids),
            "bundle_id": result.bundle.bundle_id,
            "graph_snapshot_id": result.bundle.graph_snapshot_id,
            "vector_index_id": result.bundle.vector_index_id,
            "retrieval_sources": list(item.retrieval_sources),
        } for item in result.items if item.evidence_ids and item.citation_ids]


def _course_id(value: str) -> int:
    try:
        course_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceUnavailableError("invalid course scope") from exc
    if course_id <= 0:
        raise ServiceUnavailableError("invalid course scope")
    return course_id
