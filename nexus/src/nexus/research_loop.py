"""F7 研究循环：模型驱动、平台护栏（预算/取消/停止条件/交付核对）。

- 循环由模型驱动（plan → advance → submit → complete），平台只做守卫：
  预算用尽/取消/终态即停，不无限循环；
- advance 一次只交办一个子问题（返回问题＋完成标准＋namespace＋剩余预算），
  并扣 rounds/subtasks 配额；submit 回收结果（只收摘要＋引用＋缺口＋冲突）；
- complete 按 delivery_checklist 逐项核对（不看 Todo 全勾）；未达项返回
  unmet，不强制关闭；
- 工具与 HTTP 端点共用同一平台函数（research_state），语义一致。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger("nexus.research_loop")


def _owner() -> str:
    from nexus.request_scope import current_user_id

    return current_user_id() or ""


def _session() -> str:
    from nexus.request_scope import current_session_id

    return current_session_id() or ""


def public_task_view(task: dict[str, Any]) -> dict[str, Any]:
    """任务对外视图（含预算余量＋交付核对，不含内部明细）。"""
    from nexus import research_state as state_module

    budget = task.get("budget") or {}
    used = task.get("used") or {}
    budget_left = {}
    for used_key, budget_key in (("rounds", "max_rounds"),
                                 ("subtasks", "max_subtasks"),
                                 ("evidence_calls", "max_evidence_calls")):
        try:
            budget_left[used_key] = max(
                0, int(budget.get(budget_key, 0)) - int(used.get(used_key, 0)))
        except (TypeError, ValueError):
            budget_left[used_key] = 0
    return {
        "task_id": task.get("task_id", ""),
        "parent_task_id": task.get("parent_task_id", ""),
        "status": task.get("status", ""),
        "brief": task.get("brief", {}),
        "questions": task.get("questions", []),
        "budget": budget,
        "budget_left": budget_left,
        "findings": task.get("findings", []),
        "evidence_ids": task.get("evidence_ids", []),
        "gaps": task.get("gaps", []),
        "conflicts": task.get("conflicts", []),
        "experiment_run_ids": task.get("experiment_run_ids", []),
        "report_artifact_id": task.get("report_artifact_id", ""),
        "namespace": task.get("namespace", ""),
        "cancel_requested": bool(task.get("cancel_requested", False)),
        "detail": task.get("detail", ""),
        "checklist": state_module.delivery_checklist(task),
        "created_at": task.get("created_at", 0),
        "updated_at": task.get("updated_at", 0),
    }


def _error(code: str, detail: str) -> dict[str, Any]:
    return {"status": "error", "code": code, "detail": detail}


@tool
async def plan_research_task(
    objective: str,
    dimensions: str = "",
    data_range: str = "",
    time_range: str = "",
    delivery_format: str = "",
    questions: list[str] | None = None,
) -> dict[str, Any]:
    """创建持续研究任务（含 Brief 解析；只建任务、不执行）。

    参数：
    - objective：研究目标（一句话，必填）；
    - dimensions：分析维度（逗号/顿号分隔，≤8；空即单问题任务）；
    - data_range/time_range：数据/时间范围声明（原文保留，供核对）；
    - delivery_format：交付格式要求（如“比较表＋综述 Word”，原文保留）；
    - questions：子问题文本列表（可选；空即按维度派生）。
    """
    from nexus import research_state as state_module

    owner, session_id = _owner(), _session()
    if not owner or not session_id:
        return _error("SCOPE_MISSING", "缺少用户/会话上下文，无法创建任务。")
    parsed_questions = [{"text": str(item)} for item in (questions or [])
                        if str(item or "").strip()][:12]
    try:
        task = state_module.create_task(
            owner=owner, session_id=session_id, objective=objective,
            dimensions=dimensions, data_range=data_range, time_range=time_range,
            delivery_format=delivery_format, questions=parsed_questions)
    except state_module.ResearchError as error:
        return _error(error.code, str(error))
    return {"status": "success", "task": public_task_view(task)}


@tool
async def advance_research_task(task_id: str) -> dict[str, Any]:
    """取下一个子问题交办（一次一个；扣预算；预算/取消/终态即停）。

    返回 assignment{question_id/text/criteria/namespace/budget_left}，
    或停止信号 {stopped: reason}（no_pending/budget_exhausted/cancelled/
    terminal）。交办后经 task researcher 委派，完成后用
    submit_research_result 回收。
    """
    from nexus import research_state as state_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文。")
    try:
        assigned = state_module.assign_next_question(
            (task_id or "").strip(), owner)
    except state_module.ResearchError as error:
        return _error(error.code, str(error))
    task = assigned["task"]
    if assigned.get("stopped"):
        reason = str(assigned["stopped"])
        detail = {
            "terminal": f"任务已终态（{task['status']}），不再交办。",
            "cancelled": "任务已取消，停止交办。",
            "budget_exhausted": f"预算已用尽（{task.get('detail', '')}），停止交办。",
            "no_pending": "无待交办子问题；回收结果或交付核对。",
        }.get(reason, reason)
        return {"status": "stopped", "reason": reason, "detail": detail,
                "task": public_task_view(task)}
    question = assigned["question"] or {}
    budget = task.get("budget") or {}
    used = task.get("used") or {}
    return {
        "status": "success",
        "assignment": {
            "question_id": str(question.get("id") or ""),
            "text": str(question.get("text") or ""),
            "criteria": str(question.get("criteria") or ""),
            "namespace": task.get("namespace", ""),
            "budget_left": {
                "rounds": max(0, int(budget.get("max_rounds", 0))
                              - int(used.get("rounds", 0))),
                "subtasks": max(0, int(budget.get("max_subtasks", 0))
                                - int(used.get("subtasks", 0))),
                "evidence_calls": max(
                    0, int(budget.get("max_evidence_calls", 0))
                    - int(used.get("evidence_calls", 0))),
            },
        },
        "task": public_task_view(task),
    }


@tool
async def submit_research_result(
    task_id: str,
    question_id: str,
    summary: str,
    evidence_ids: list[str] | None = None,
    gaps: list[str] | None = None,
    conflicts: list[str] | None = None,
) -> dict[str, Any]:
    """回收子任务结果（只收摘要＋引用＋缺口＋冲突，不收全文）。

    evidence_ids 须可解析（本会话登记或持久化证据）；非法即拒绝。
    引用 ID 合法不等于支持结论——综合仍须核对主张与原文。
    """
    from nexus import research_state as state_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文。")
    try:
        task = state_module.submit_finding(
            task_id=(task_id or "").strip(), owner=owner,
            question_id=(question_id or "").strip(), summary=summary or "",
            evidence_ids=list(evidence_ids or []),
            gaps=list(gaps or []), conflicts=list(conflicts or []))
    except state_module.ResearchError as error:
        return _error(error.code, str(error))
    return {"status": "success", "task": public_task_view(task)}


@tool
async def complete_research_task(task_id: str, report_artifact_id: str = "",
                                 close_as_partial: bool = False) -> dict[str, Any]:
    """交付核对并关闭任务（逐项检查，不看 Todo 全勾）。

    全达标 → succeeded；有未达项 → 返回 unmet（不强制关闭），或
    close_as_partial=True 时记 partial 关闭（缺口保留在任务中）。
    """
    from nexus import research_state as state_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文。")
    try:
        task = state_module.get_task((task_id or "").strip())
        if task is None or task["owner"] != owner:
            return _error("TASK_NOT_FOUND", "研究任务不存在或无权操作。")
        if task["status"] in state_module.TASK_TERMINAL:
            return {"status": "success", "closed": task["status"],
                    "task": public_task_view(task)}
        if (report_artifact_id or "").strip():
            task = state_module.set_report(
                task["task_id"], owner, (report_artifact_id or "").strip())
        checklist = state_module.delivery_checklist(task)
        unmet = [item for item in checklist if not item.get("met")]
        if not unmet:
            task = state_module.set_status(task["task_id"], owner,
                                           state_module.TASK_SUCCEEDED,
                                           "交付核对全达标。")
            return {"status": "success", "closed": "succeeded",
                    "task": public_task_view(task)}
        if close_as_partial:
            task = state_module.set_status(
                task["task_id"], owner, state_module.TASK_PARTIAL,
                "缺口保留下关闭："
                + "；".join(f"{item['item']}({item['detail']})" for item in unmet)[:500])
            return {"status": "success", "closed": "partial",
                    "unmet": unmet, "task": public_task_view(task)}
        return {"status": "need_more_work", "unmet": unmet,
                "detail": "交付核对未全达标；补齐后重试，或 close_as_partial 关闭。",
                "task": public_task_view(task)}
    except state_module.ResearchError as error:
        return _error(error.code, str(error))


@tool
async def link_experiment_run(task_id: str, run_id: str) -> dict[str, Any]:
    """关联实验运行到研究任务（实验是分支，不是必经路径）。

    仅自主实验 run 可关联（归属一致）；preset Worker 走其真实 job 标识。
    """
    from nexus import research_state as state_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文。")
    try:
        task = state_module.link_experiment(
            (task_id or "").strip(), owner, (run_id or "").strip())
    except state_module.ResearchError as error:
        return _error(error.code, str(error))
    return {"status": "success", "task": public_task_view(task)}


@tool
async def cancel_research_task(task_id: str) -> dict[str, Any]:
    """取消研究任务（置旗即停；已保存材料保留，可凭 namespace 恢复查看）。"""
    from nexus import research_state as state_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文。")
    try:
        task = state_module.request_cancel((task_id or "").strip(), owner)
    except state_module.ResearchError as error:
        return _error(error.code, str(error))
    return {"status": "success", "task": public_task_view(task)}


@tool
async def get_research_task(task_id: str) -> dict[str, Any]:
    """读取研究任务（含预算余量＋交付核对；中断恢复查看入口）。"""
    from nexus import research_state as state_module

    owner = _owner()
    if not owner:
        return _error("SCOPE_MISSING", "缺少用户上下文。")
    task = state_module.get_task((task_id or "").strip())
    if task is None or task["owner"] != owner:
        return _error("TASK_NOT_FOUND", "研究任务不存在或无权查看。")
    return {"status": "success", "task": public_task_view(task)}
