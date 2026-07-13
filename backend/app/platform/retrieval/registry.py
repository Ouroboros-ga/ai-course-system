"""
检索器注册表。

维护 ``RetrievalScope -> TreeRAGRetriever`` 的映射，是 Tree Provider、
Gateway 与旧 ``rag_pipeline`` 兼容层共享的单一事实源。

并发与原子性：
- 注册采用「局部完整构建 -> 成功后单次赋值替换」模式。新检索器在调用方
  完整 ``build_index`` 后才传入 ``register``，注册仅为一次字典绑定，
  不会出现「边构建边开放查询」。
- 构建失败由调用方捕获，旧索引保留在注册表中不受影响。
- ``clear`` 仅删除指定 scope，不影响其他 scope。
- 当前为单事件循环内存模型，未引入显式锁；多 worker / 水平扩容下的
  一致性问题见 P1A 文档「多进程风险」一节（本轮不实现持久化）。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from app.platform.retrieval.schemas import RetrievalScope

logger = logging.getLogger(__name__)


class RetrieverRegistry:
    """作用域 -> 底层检索器的注册表。"""

    def __init__(self) -> None:
        self._scopes: Dict[str, object] = {}

    def register(self, scope: RetrievalScope, retriever: object) -> None:
        """原子注册（替换）某作用域的检索器。retriever 须已完成索引构建。"""
        self._scopes[scope.key] = retriever
        logger.info(f"[RetrieverRegistry] 已注册检索器: scope={scope.key}")

    def get(self, scope: RetrievalScope) -> Optional[object]:
        return self._scopes.get(scope.key)

    def has(self, scope: RetrievalScope) -> bool:
        return scope.key in self._scopes

    def clear(self, scope: RetrievalScope) -> bool:
        """清除指定作用域检索器。返回是否确实存在并清除。不影响其他 scope。"""
        if scope.key in self._scopes:
            del self._scopes[scope.key]
            logger.info(f"[RetrieverRegistry] 已清除检索器: scope={scope.key}")
            return True
        return False

    def clear_all(self) -> int:
        """清除全部作用域检索器（主要用于测试隔离）。返回清除数量。"""
        count = len(self._scopes)
        self._scopes.clear()
        if count:
            logger.info(f"[RetrieverRegistry] 已清除全部检索器: {count} 个")
        return count

    def scope_keys(self):
        """当前已注册作用域键的快照（调试/测试用）。"""
        return list(self._scopes.keys())
