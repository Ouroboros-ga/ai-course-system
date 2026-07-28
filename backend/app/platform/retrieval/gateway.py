"""
统一检索 Gateway。

为 Service 层提供唯一检索入口，屏蔽底层 Provider 细节：

    QAService -> RetrievalGateway -> TreeRetrieverProvider -> TreeRAGRetriever

Gateway 职责（本轮）：
- 统一入口与结果结构（``RetrievedChunk``）；
- 空查询、``top_k`` 边界、检索异常的兜底处理；
- 作用域索引构建委托（``index``）与生命周期管理（``has_scope`` / ``clear_scope``）。

本轮 Gateway 不包含：BM25 / Dense / 融合 / 重排 / LLM / 权限 / 评测。
Gateway 是稳定 seam，不是堆功能的容器。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.platform.retrieval.providers.tree import TreeRetrieverProvider
from app.platform.retrieval.providers.canonical_document_ir import CanonicalDocumentIRRetriever
from app.platform.retrieval.registry import RetrieverRegistry
from app.platform.retrieval.schemas import RetrievedChunk, RetrievalScope

logger = logging.getLogger(__name__)

# top_k 合法区间。负数或 0 归一为默认；过大不裁剪（底层已按 top_k 截断）。
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 100


class RetrievalGateway:
    """统一检索网关。持有共享 registry 与默认 tree provider。"""

    def __init__(self) -> None:
        self._registry = RetrieverRegistry()
        self._provider = TreeRetrieverProvider(self._registry)

    # ---- 索引（供 rag_pipeline 兼容层与上传主链调用）----

    def index(self, scope: RetrievalScope, tree_result: object) -> None:
        """为作用域构建并原子注册树索引。"""
        self._provider.index(scope, tree_result)

    # ---- 检索（供 QAService 调用）----

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = _DEFAULT_TOP_K,
    ) -> List[RetrievedChunk]:
        """
        在指定作用域检索。返回统一 ``RetrievedChunk`` 列表。

        - 空查询 -> []；
        - 作用域未建立 -> []（不回退其他作用域）；
        - 检索异常 -> 记录日志并返回 []（不向上抛，保证问答主链稳定）。
        """
        if not query or not query.strip():
            return []

        k = self._normalize_top_k(top_k)

        try:
            # Production course material is retrieved from immutable Canonical
            # DocumentIR projections first. The tree retriever remains only a
            # compatibility fallback for older course content.
            canonical = CanonicalDocumentIRRetriever.retrieve(
                query, scope=scope, top_k=k,
            )
            if canonical:
                return canonical
            return self._provider.retrieve(query, scope=scope, top_k=k)
        except Exception as e:  # noqa: BLE001 - 网关层兜底，保证主链不中断
            logger.error(
                f"[RetrievalGateway] 检索异常，返回空: scope={scope.key}, "
                f"error={type(e).__name__}: {e}"
            )
            return []

    # ---- 生命周期 ----

    def has_scope(self, scope: RetrievalScope) -> bool:
        return self._provider.has_scope(scope)

    def clear_scope(self, scope: RetrievalScope) -> bool:
        return self._provider.clear_scope(scope)

    def clear_all(self) -> int:
        return self._registry.clear_all()

    # ---- 旧 rag_pipeline 兼容所需：取底层检索器 ----

    def get_raw_retriever(self, scope: RetrievalScope) -> Optional[object]:
        """
        返回作用域对应的底层 ``TreeRAGRetriever``（无则 None）。

        仅供旧 ``rag_pipeline.retrieve`` 兼容层使用，以保持其返回
        ``RetrievalResult`` 的旧类型契约。新代码应使用 ``retrieve``。
        """
        return self._registry.get(scope)

    @staticmethod
    def _normalize_top_k(top_k: int) -> int:
        if not isinstance(top_k, int) or top_k <= 0:
            return _DEFAULT_TOP_K
        return min(top_k, _MAX_TOP_K)


# 进程级单例。rag_pipeline 兼容层与 QAService 共享同一 registry。
retrieval_gateway = RetrievalGateway()
