"""NX-H1 计划产品投影：TodoListMiddleware 原生状态 → 前端计划快照。

语义冻结（NX-H1/R1 夜间任务书 §4）：
- Todo 状态枚举保持 middleware 原生 ``pending / in_progress / completed``；
  暂停、取消、失败属于运行状态，不塞进上游不支持的 Todo 枚举。
- 稳定 id / plan_id / revision 属产品投影：
  - 条目 id 由内容派生（同内容跨 revision 稳定，重复内容加序号后缀）；
  - plan_id 由 session 派生（同会话恒定，全量替换不换 plan_id）；
  - revision 由调用方（Runtime 进程内单调计数器）递增，本模块不记忆。
- 计划 completed 是模型的计划标记，不作为工具成功或实验 PASS 证据。
- 不同用户/会话绝不共享快照：thread 命名空间隔离由调用方保证，本模块
  只做纯投影，不持有任何跨请求状态。
"""
from __future__ import annotations

import hashlib
from typing import Any

PLAN_SOURCE = "agent_plan"
PLAN_ITEM_STATUSES = ("pending", "in_progress", "completed")
_PLAN_ITEM_CONTENT_MAX = 200
_MAX_ITEMS = 50


def _hash8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def normalize_todos(raw: Any) -> list[dict[str, str]] | None:
    """middleware 原生 todos（[{content, status}]）→ 规范条目列表。

    形状非法（非 list/全空）返回 None（调用方不 emit 空计划）。非法 status
    的条目直接丢弃而不猜测语义——coerce 成 pending 会把模型错误伪装成
    正常状态，违反诚实边界。
    """
    if not isinstance(raw, list):
        return None
    items: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        status = entry.get("status")
        if not isinstance(content, str) or not content.strip():
            continue
        if status not in PLAN_ITEM_STATUSES:
            continue
        items.append(
            {"content": content.strip()[:_PLAN_ITEM_CONTENT_MAX], "status": status}
        )
        if len(items) >= _MAX_ITEMS:
            break
    return items or None


def plan_snapshot(session_id: str, todos: Any, *, revision: int) -> dict[str, Any] | None:
    """投影计划快照（任务书 §4 最低语义）；无有效条目返回 None。

    返回形如::

        {"session_id", "plan_id", "revision",
         "items": [{"id", "content", "status"}], "source": "agent_plan"}
    """
    items = normalize_todos(todos)
    if items is None:
        return None
    seen: dict[str, int] = {}
    projected: list[dict[str, str]] = []
    for item in items:
        base = _hash8(item["content"])
        seen[base] = seen.get(base, 0) + 1
        item_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
        projected.append({"id": item_id, "content": item["content"], "status": item["status"]})
    return {
        "session_id": session_id,
        "plan_id": f"plan-{_hash8(session_id)}",
        "revision": int(revision),
        "items": projected,
        "source": PLAN_SOURCE,
    }
