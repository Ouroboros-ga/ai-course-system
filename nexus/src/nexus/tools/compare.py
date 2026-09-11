"""F8 受控对照工具（Research-only；只关联、不执行）。

对照不执行、不审批：arm 运行走既有批准/run 通道产生终态运行，
本工具只做关联（终态＋配方一致性门）与报告。Ask/Auto 均可见，
因为不产生任何执行动作。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


def _owner() -> str:
    from nexus.request_scope import current_user_id

    return current_user_id() or ""


def _session() -> str:
    from nexus.request_scope import current_session_id

    return current_session_id() or ""


def _error(code: str, detail: str) -> dict[str, Any]:
    return {"status": "error", "code": code, "detail": detail}


@tool
async def plan_compare(
    objective: str,
    data_ref: str,
    data_hash: str,
    metric_policy: dict[str, Any] | None = None,
    allowed_varied: list[str] | None = None,
    arms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """创建受控 A/B 对照（只建对照、不执行）。

    参数：
    - objective：对照目标（一句话，必填）；
    - data_ref/data_hash：共同数据引用＋hash（两组共享，只读复用）；
    - metric_policy：共同指标政策（对象，必填）；
    - allowed_varied：允许变化的参数名白名单；
    - arms：≥2 组，每组 {name, recipe_hash, recipe_artifact_id,
      varied_params}；varied_params 的键须在白名单内，且各组须可区分。
    """
    from nexus import experiment_compare as compare_module

    owner, session_id = _owner(), _session()
    if not owner or not session_id:
        return _error("SCOPE_MISSING", "缺少用户/会话上下文，无法创建对照。")
    try:
        compare = compare_module.create_compare(
            owner=owner, session_id=session_id, objective=objective,
            common={"data_ref": data_ref, "data_hash": data_hash,
                    "metric_policy": metric_policy or {}},
            allowed_varied=allowed_varied, arms=arms)
    except compare_module.CompareError as error:
        return _error(error.code, str(error))
    return {"status": "success",
            "compare": compare_module.public_compare_view(compare)}


@tool
async def link_compare_run(
    compare_id: str, arm_name: str, run_id: str,
) -> dict[str, Any]:
    """关联对照组的终态运行（只关联终态；配方不一致即拒绝）。

    运行须终态（succeeded/failed，失败也并列）；须自带冻结配方引用
    且与本组声明一致——排错改了方案会换 hash，旧组拒绝关联。
    指标只取运行存储报告的实测值，取不到即标缺失。
    """
    from nexus import experiment_compare as compare_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文，无法关联运行。")
    try:
        compare = await compare_module.link_arm_run(
            compare_id=compare_id, owner=owner,
            arm_name=arm_name, run_id=run_id)
    except compare_module.CompareError as error:
        return _error(error.code, str(error))
    return {"status": "success",
            "compare": compare_module.public_compare_view(compare)}


@tool
async def get_compare(compare_id: str) -> dict[str, Any]:
    """读受控对照（含并列报告；本人；他人不可见）。"""
    from nexus import experiment_compare as compare_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文，无法读取对照。")
    compare = compare_module.get_compare((compare_id or "").strip()[:64])
    if compare is None or owner != compare.get("owner", ""):
        return _error("COMPARE_NOT_FOUND", "对照不存在或已不可恢复。")
    return {"status": "success",
            "compare": compare_module.public_compare_view(compare)}


@tool
async def cancel_compare(compare_id: str) -> dict[str, Any]:
    """取消受控对照（置终态；已关联结果保留，不删除）。"""
    from nexus import experiment_compare as compare_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文，无法取消对照。")
    try:
        compare = compare_module.request_cancel(
            (compare_id or "").strip()[:64], owner)
    except compare_module.CompareError as error:
        return _error(error.code, str(error))
    return {"status": "success",
            "compare": compare_module.public_compare_view(compare)}
