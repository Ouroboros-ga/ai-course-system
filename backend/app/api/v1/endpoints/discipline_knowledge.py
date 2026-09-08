"""CS 学科垂类知识库 API（挑战杯 XH-202620）。

只读检索接口：概念检索（带权威来源引用）、语料资料检索（版本化原文块）、
节点 + 图邻居查询、知识库概览（含语料版本覆盖）、原文引用回读。
概念数据来自 ``knowledge_data/``（公开教材内容摘要），语料来自已发布
语料版本（``scope=corpus:cs``）；认证用户可访问；不修改任何课程/证据/
图谱数据。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.platform.knowledge.discipline_kb import get_node, get_knowledge_base, overview, search_nodes
from app.services.discipline_knowledge.corpus_index import (
    CorpusIndexError,
    get_chunk_reference,
    get_release,
    read_head,
)
from app.services.discipline_knowledge.corpus_search import CorpusSearchService

router = APIRouter()

SEARCH_MODES = ("concept", "corpus", "all")


def _corpus_error_to_http(error: CorpusIndexError) -> HTTPException:
    if error.error_code in ("NOT_IN_RELEASE", "RELEASE_NOT_FOUND", "NOT_FOUND"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.error_code)
    if error.error_code == "SOURCE_WITHDRAWN":
        return HTTPException(status_code=status.HTTP_410_GONE, detail=error.error_code)
    if error.error_code in ("NOT_READY", "INDEX_NOT_READY"):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.error_code)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=error.error_code)


@router.get("/search")
async def search_discipline_knowledge(
    q: str = Query(..., min_length=1, max_length=200, description="学科知识关键词，如：哈希表、快速排序"),
    top_k: int = Query(default=5, ge=1, le=20),
    mode: str = Query(default="concept", description="concept=精编概念（默认兼容）|corpus=语料资料|all=两者合并"),
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """关键词检索：概念层默认兼容；corpus/all 返回版本化语料块与 release_id。"""
    if mode not in SEARCH_MODES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="SCHEMA_INVALID")
    results: list[dict[str, Any]] = []
    release_id = ""
    degraded_reasons: list[str] = []
    coverage: dict[str, Any] = {}
    if mode in ("concept", "all"):
        for item in search_nodes(q, top_k=top_k):
            results.append({**item, "result_type": "concept"})
    if mode in ("corpus", "all"):
        try:
            corpus = CorpusSearchService().search(session, q, top_k=top_k)
        except CorpusIndexError as exc:
            raise _corpus_error_to_http(exc)
        release_id = corpus.get("release_id") or ""
        degraded_reasons = list(corpus.get("degraded_reasons") or [])
        coverage = dict(corpus.get("coverage") or {})
        for row in corpus.get("results") or []:
            row.setdefault("result_type", "corpus_chunk")
            results.append(row)
    return unified_response(
        code=200,
        message=f"学科知识检索完成（{len(results)} 条）",
        data={"query": q, "mode": mode, "release_id": release_id,
              "results": results, "degraded_reasons": degraded_reasons,
              "coverage": coverage},
    )


@router.get("/nodes/{node_id}")
async def get_discipline_node(
    node_id: str,
    current_user: dict = Depends(get_current_user),
):
    """查询单个知识节点及其图邻居（关系可追溯）。"""
    node = get_node(node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"知识节点不存在: {node_id}")
    return unified_response(code=200, message="获取知识节点成功", data=node)


@router.get("/overview")
async def get_discipline_overview(
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """知识库概览：精编节点/关系统计（兼容）+ 语料版本覆盖（文档/块/向量/范围）。"""
    data = overview()
    data["corpus"] = _corpus_overview(session)
    return unified_response(code=200, message="获取知识库概览成功", data=data)


def _corpus_overview(session: Session) -> dict[str, Any]:
    """语料覆盖：已发布版本成员计数；无版本时可用性为 False，不冒充完成。"""
    from app.models.discipline_corpus_index_model import (
        DisciplineCorpusIndexMember,
    )
    from sqlmodel import select

    head = read_head(session)
    if not head["release_id"]:
        return {"available": False, "release_id": "", "revision": 0,
                "documents": 0, "eligible_chunks": 0, "embedded_chunks": 0,
                "scope": "corpus:cs"}
    try:
        release = get_release(session, head["release_id"])
    except CorpusIndexError:
        return {"available": False, "release_id": "", "revision": 0,
                "documents": 0, "eligible_chunks": 0, "embedded_chunks": 0,
                "scope": "corpus:cs"}
    members = session.exec(
        select(DisciplineCorpusIndexMember).where(
            DisciplineCorpusIndexMember.release_id == head["release_id"])
    ).all()
    documents = len({dict(m.display_metadata or {}).get("version_id", "")
                     for m in members} - {""})
    return {"available": True, "release_id": head["release_id"],
            "revision": head["revision"], "documents": documents,
            "eligible_chunks": release["members"],
            "embedded_chunks": release["embedded"],
            "scope": release.get("scope") or "corpus:cs"}


@router.get("/chunks/{chunk_id}")
async def get_discipline_chunk_reference(
    chunk_id: str,
    release_id: str = Query(..., min_length=1, max_length=64, description="固定语料版本，不接受磁盘路径"),
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """原文引用回读：该版本限定的 chunk 原文与定位。

    越版本 404；来源撤回 410；文本缺失 503。不返回对象存储 key 与路径。
    """
    try:
        reference = get_chunk_reference(session, chunk_id, release_id)
    except CorpusIndexError as exc:
        raise _corpus_error_to_http(exc)
    reference.pop("object_key", None)
    reference.pop("text_object_key", None)
    return unified_response(code=200, message="获取语料原文成功", data=reference)


@router.post("/reload")
async def reload_discipline_knowledge(
    current_user: dict = Depends(get_current_user),
):
    """数据文件更新后手动刷新内存缓存（只读重载，不写数据）。"""
    kb = get_knowledge_base(force_reload=True)
    return unified_response(
        code=200,
        message="学科知识库已重新加载",
        data={"node_count": len(kb.nodes), "relation_count": len(kb.relations)},
    )
