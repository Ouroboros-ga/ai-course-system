"""学习路径规划服务（M8）：当前节点完成后推荐下一学习节点。

基于 active release 的课件 pre-order 前序（``ordered_outline_nodes``，
key 与 ``ordered_knowledge_keys`` 一致：``knowledge_graph_node_id or
outline_node_id``），对候选节点做薄弱判定（复用 M3 判弱条件：表现分有值、
样本量达标、衰减后置信度达标、表现分 < 0.5），薄弱节点优先推荐。

输出项（供展示层映射）：
- ``outline_node_id``：课件节点 ID（展示层映射用）
- ``knowledge_graph_node_id``：图谱节点 key（认知/推荐用）
- ``title`` / ``position``（前序位置）/ ``is_weak`` / ``is_locked``（先恒 False）
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.services.unified_learning_service import (
    active_release,
    ordered_outline_nodes,
)


def _node_key(node: Any) -> str:
    return str(node.knowledge_graph_node_id or node.outline_node_id)


def _node_is_weak(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    node_key: str,
) -> bool:
    """M3 判弱条件：表现分有值、样本量达标、衰减后置信度达标、表现分 < 0.5。"""
    from app.services.cognitive_decay_service import decayed_confidence
    from app.services.cognitive_service import (
        MIN_SAMPLE_FOR_PERFORMANCE,
        get_latest_cognitive_state,
    )
    from app.services.knowledge_node_identity_service import resolve_node_id
    from app.services.recommendation_service import (
        PREREQ_WEAK_CONFIDENCE,
        PREREQ_WEAK_PERF,
    )

    node_id_int = resolve_node_id(session, course_id, node_key)
    if node_id_int is None and node_key.isdigit():
        node_id_int = int(node_key)
    if node_id_int is None:
        return False
    state = get_latest_cognitive_state(session, student_id, course_id, node_id_int)
    if state is None or state.observed_performance_score is None:
        return False
    if (state.sample_size or 0) < MIN_SAMPLE_FOR_PERFORMANCE:
        return False
    decayed = decayed_confidence(
        state.evidence_confidence, computed_at=state.computed_at,
    )
    if decayed is None or decayed < PREREQ_WEAK_CONFIDENCE:
        return False
    return state.observed_performance_score < PREREQ_WEAK_PERF


def plan_next_nodes(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    current_node_key: str | None = None,
    max_next: int = 3,
) -> list[dict[str, Any]]:
    """返回推荐学习序列（薄弱优先，含历史遗留薄弱节点）。

    ``current_node_key`` 接受 outline_node_id 或 knowledge_graph_node_id；
    不在课件前序中时从头推荐。无 active release 时返回空列表。

    候选集 = 当前节点之前的薄弱节点（历史遗留，按前序倒序取最近 max_next 个）
    + 当前节点之后的节点（前序）。最终按"薄弱优先、同组内前序"稳定排序，
    截断到 max_next 个。
    """
    release = active_release(session, course_id)
    if release is None or not release.outline_version_id:
        return []
    nodes = ordered_outline_nodes(
        session,
        outline_version_id=release.outline_version_id,
        knowledge_points_only=True,
    )
    if not nodes:
        return []

    current_idx: int | None = None
    if current_node_key:
        target = str(current_node_key)
        for index, node in enumerate(nodes):
            if str(node.outline_node_id) == target or _node_key(node) == target:
                current_idx = index
                break
    if current_idx is None:
        current_idx = -1  # 当前节点不在课件前序中：从头推荐

    # 历史遗留：当前节点之前的薄弱节点（已越过但未掌握），按前序倒序取最近
    # max_next 个（离当前越近越优先补）。
    legacy_weak: list[Any] = []
    if current_idx >= 0:
        for node in reversed(nodes[:current_idx]):
            if _node_is_weak(
                session, student_id=student_id, course_id=course_id,
                node_key=_node_key(node),
            ):
                legacy_weak.append(node)
                if len(legacy_weak) >= max_next:
                    break

    # 后续候选：当前节点之后的节点（前序）
    following = nodes[current_idx + 1: current_idx + 1 + max_next]

    index_by_outline = {
        node.outline_node_id: index for index, node in enumerate(nodes)
    }
    rows: list[dict[str, Any]] = []
    for node in [*legacy_weak, *following]:
        position = index_by_outline[node.outline_node_id]
        rows.append({
            "outline_node_id": node.outline_node_id,
            "knowledge_graph_node_id": node.knowledge_graph_node_id,
            "title": node.title or node.outline_node_id,
            "position": position,
            "is_weak": _node_is_weak(
                session, student_id=student_id, course_id=course_id,
                node_key=_node_key(node),
            ),
            "is_locked": False,
        })
    # 薄弱优先（稳定排序：同组内保持前序）
    rows.sort(key=lambda row: (not row["is_weak"], row["position"]))
    return rows[:max_next]


__all__ = ["plan_next_nodes"]