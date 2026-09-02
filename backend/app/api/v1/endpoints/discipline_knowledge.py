"""CS 学科垂类知识库 API（挑战杯 XH-202620）。

只读检索接口：关键词检索（带权威来源引用）、节点 + 图邻居查询、知识库概览。
数据来自 ``knowledge_data/``（公开教材内容摘要），认证用户可访问；
不修改任何课程/证据/图谱数据。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.platform.knowledge.discipline_kb import get_node, get_knowledge_base, overview, search_nodes

router = APIRouter()


@router.get("/search")
async def search_discipline_knowledge(
    q: str = Query(..., min_length=1, max_length=200, description="学科知识关键词，如：哈希表、快速排序"),
    top_k: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """关键词检索学科知识节点，结果附带权威来源（内容可追溯）。"""
    results = search_nodes(q, top_k=top_k)
    return unified_response(
        code=200,
        message=f"学科知识检索完成（{len(results)} 条）",
        data={"query": q, "results": results},
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
):
    """知识库概览：节点/关系/课程/类型统计与数据版本。"""
    return unified_response(code=200, message="获取知识库概览成功", data=overview())


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
