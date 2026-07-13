"""
树式关键词检索 Provider。

将现有 ``app.common.RAG.tree_rag.TreeRAGRetriever`` 包装为统一 Retriever Provider：
- 不重复实现 IK 分词与树检索，直接复用 ``TreeRAGRetriever``。
- 以 ``RetrievalScope`` 管理多棵树（课程 / 知识库作用域隔离）。
- 返回统一 ``RetrievedChunk``，不伪造当前不具备的元数据（页码/章节 ID 置空）。
- 缺失作用域 / 空查询时返回空列表，不回退到其他作用域。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from app.platform.retrieval.registry import RetrieverRegistry
from app.platform.retrieval.schemas import (
    RetrievedChunk,
    RetrievalScope,
    stable_chunk_id,
)

# 延迟导入 app.common.RAG.tree_rag：该模块的加载会触发 app.common.RAG 包初始化，
# 而 rag_utils 又依赖本包，形成循环。tree_rag 仅在 index/retrieve 运行时需要，
# 故用 TYPE_CHECKING 守卫类型注解、运行时在方法内导入，打破导入期循环。
if TYPE_CHECKING:
    from app.common.RAG.tree_rag import RetrievalResult, TreeBuildResult, TreeRAGRetriever

logger = logging.getLogger(__name__)


class TreeRetrieverProvider:
    """
    树式检索 Provider，实现 ``ScopedRetriever`` 协议。

    构建参数 ``top_k`` / ``context_window`` 与旧 ``RAGPipeline`` 默认值一致，
    以保持检索行为不变。
    """

    def __init__(
        self,
        registry: RetrieverRegistry,
        top_k: int = 5,
        context_window: int = 1,
    ) -> None:
        self._registry = registry
        self._top_k = top_k
        self._context_window = context_window

    # ---- 索引管理 ----

    def index(self, scope: RetrievalScope, tree_result: "TreeBuildResult") -> None:
        """
        为指定作用域构建并原子注册一棵检索树。

        先在局部变量中完整构建 ``TreeRAGRetriever`` 并 ``build_index``，
        成功后再通过 registry 单次绑定替换。构建异常由调用方处理，
        此时旧索引保留在 registry 中不受影响。
        """
        from app.common.RAG.tree_rag import TreeRAGRetriever

        retriever = TreeRAGRetriever(
            top_k=self._top_k,
            context_window=self._context_window,
        )
        retriever.build_index(tree_result)
        self._registry.register(scope, retriever)

    def has_scope(self, scope: RetrievalScope) -> bool:
        return self._registry.has(scope)

    def clear_scope(self, scope: RetrievalScope) -> bool:
        return self._registry.clear(scope)

    # ---- 检索 ----

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """
        在指定作用域内检索。

        - 查询为空 -> 返回空（不抛异常）。
        - 作用域未建立 -> 返回空，不回退其他作用域。
        - 底层异常向上抛出，由 Gateway 统一兜底（不在 Provider 内静默串库）。
        """
        if not query or not query.strip():
            return []

        from app.common.RAG.tree_rag import TreeRAGRetriever

        retriever = self._registry.get(scope)
        if retriever is None:
            logger.info(
                f"[TreeProvider] 作用域未建立索引，返回空: scope={scope.key}"
            )
            return []

        assert isinstance(retriever, TreeRAGRetriever)
        results: List["RetrievalResult"] = retriever.retrieve(
            query, strategy="hybrid", top_k=top_k
        )
        return [self._to_chunk(r, scope, retriever) for r in results]

    # ---- 映射 ----

    def _to_chunk(
        self,
        result: "RetrievalResult",
        scope: RetrievalScope,
        retriever: "TreeRAGRetriever",
    ) -> RetrievedChunk:
        node = result.node
        # 复用底层检索器的上下文展开逻辑（节点自身 + 子节点），保持与旧
        # rag_pipeline.get_context_for_result 一致的内容形态，供 LLM 直接使用。
        expanded_content = retriever.get_context_for_result(result)

        path_parts = [p for p in (result.context_path or "").split("/") if p]

        chapter_title: Optional[str] = path_parts[0] if path_parts else None

        return RetrievedChunk(
            chunk_id=stable_chunk_id(scope, result.context_path or "", node.content),
            content=expanded_content,
            scope=scope,
            # 当前树式检索无持久 source/chapter/page 标识，留空不伪造
            source_id=None,
            source_name=None,
            chapter_id=None,
            chapter_title=chapter_title,
            page_number=None,
            retrieval_score=result.score,
            retrieval_source="tree_keyword",
            match_type=result.match_type,
            path=path_parts,
            metadata={
                "context_path": result.context_path,
                "matched_content_preview": (result.matched_content or "")[:200],
                "node_id": node.node_id,
            },
        )
