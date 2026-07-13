"""
统一 Retriever 抽象接口。

职责边界：
- ``Retriever``：输入 ``query + scope``，输出 ``RetrievedChunk`` 列表。仅负责检索。
- Indexer / Provider：负责构建与管理底层检索器（注册、清除）。
- Gateway：负责统一调用、兼容与错误处理。
- QAService：负责使用证据生成答案。

不在 Retriever 中混入文档解析、索引构建编排、LLM 生成或权限逻辑。
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from app.platform.retrieval.schemas import RetrievedChunk, RetrievalScope


@runtime_checkable
class Retriever(Protocol):
    """统一检索器协议。"""

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        ...


class ScopedRetriever(Protocol):
    """
    带作用域索引管理的检索器协议（Provider 实现）。

    Gateway 与 Provider 通过该协议交互：``index`` 构建并原子注册，
    ``has_scope`` / ``clear_scope`` 管理生命周期。
    """

    def index(self, scope: RetrievalScope, tree_result: object) -> None:
        ...

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        ...

    def has_scope(self, scope: RetrievalScope) -> bool:
        ...

    def clear_scope(self, scope: RetrievalScope) -> bool:
        ...
