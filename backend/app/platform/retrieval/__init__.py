"""
统一检索基础架构（R2D0-P1A）。

提供知识检索的显式作用域建模、统一结果结构、Retriever 抽象、注册表与网关。
将 ``QAService`` 从直接依赖全局 ``rag_pipeline`` 迁移为依赖 ``RetrievalGateway``。

调用链：
    QAService
      -> RetrievalGateway
         -> TreeRetrieverProvider (Retriever 协议)
            -> TreeRAGRetriever (app.common.RAG.tree_rag)

旧 ``rag_pipeline`` 保留为兼容层，内部委托本包的 Gateway / Registry。
"""

from app.platform.retrieval.base import Retriever, ScopedRetriever
from app.platform.retrieval.gateway import RetrievalGateway, retrieval_gateway
from app.platform.retrieval.registry import RetrieverRegistry
from app.platform.retrieval.schemas import (
    RetrievedChunk,
    RetrievalScope,
    ScopeType,
    stable_chunk_id,
)

__all__ = [
    "RetrievedChunk",
    "RetrievalScope",
    "ScopeType",
    "stable_chunk_id",
    "Retriever",
    "ScopedRetriever",
    "RetrieverRegistry",
    "RetrievalGateway",
    "retrieval_gateway",
]
