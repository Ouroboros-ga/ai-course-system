"""T5 实验运行恢复与控制台读模型（最小 SR4 Runtime 侧）。

- 恢复语义：重启后已有 operation 运行中 → 只接管查询（adopt），绝不
  再次 submit；attempt 只在 operation 完成后追加，恢复按已完成 attempt
  的 operation_id 续查，不重放未知命令；
- 控制服务失联 → console_status=reconciling（存储快照仍为 running，
  不冒称为 failed/cancelled）；
- 写路径（attempt/状态/取消旗）复用 experiment_runs 的 PG＋内存双存储；
  LangGraph 图状态仍走 checkpointer。本模块不建通用任务调度框架。
"""

from __future__ import annotations

from typing import Any

CONSOLE_RUNNING = "running"
CONSOLE_RECONCILING = "reconciling"


def _project_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    """单个 attempt 的控制台投影：编号/命令摘要/时长/日志尾/退出码/结果。"""
    exit_code = attempt.get("exit_code")
    started = attempt.get("started_at")
    finished = attempt.get("finished_at")
    duration = None
    try:
        if started is not None and finished is not None:
            duration = max(0.0, float(finished) - float(started))
    except (TypeError, ValueError):
        duration = None
    command = str(attempt.get("actual_command") or "")
    if exit_code is None:
        result = "running"
    elif int(exit_code) == 0:
        result = "succeeded"
    else:
        result = "failed"
    return {
        "attempt_no": int(attempt.get("attempt_no", 0) or 0),
        "operation_id": str(attempt.get("operation_id") or ""),
        "command_summary": command[:120],
        "duration_s": duration,
        "log_tail": str(attempt.get("log_ref") or "")[-2000:],
        "exit_code": exit_code,
        "result": result,
    }


def console_snapshot(run_id: str, *, control_reachable: bool = True,
                     adopted: dict[str, Any] | None = None) -> dict[str, Any]:
    """控制台快照（只读投影，不触发任何执行）。

    console_status：终态如实；running＋控制可达→running；running＋控制
    失联→reconciling（存储 status 保持 running，调用方不得据此改库）。
    adopted：接管查询结果（adopt_running_operation）——只用于展示活跃
    operation 与远程状态，不改库、不 submit。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        return {"run_id": run_id, "status": "unknown",
                "console_status": "unknown", "attempt_no": 0,
                "attempts": [], "active_operation": "", "detail": "",
                "clean_status": "", "clean_note": "",
                "recovery_status": "", "completion_reason": "",
                "recipe_hash": "", "recipe_status": ""}
    attempts = [_project_attempt(a) for a in run.get("attempts", [])]
    active = ""
    for projected in reversed(attempts):
        if projected["result"] == "running" and projected["operation_id"]:
            active = projected["operation_id"]
            break
    status = run["status"]
    if status == "running" and not control_reachable:
        console_status = CONSOLE_RECONCILING
    else:
        console_status = status
    adopted_op = str((adopted or {}).get("operation_id") or "")
    if adopted_op:
        active = adopted_op
    return {
        "run_id": run["run_id"],
        "status": status,
        "console_status": console_status,
        "attempt_no": run["attempt_no"],
        "attempts": attempts,
        "active_operation": active,
        "adopted_operation_id": adopted_op,
        "remote_operation_status": str((adopted or {}).get("status") or ""),
        "resubmitted": bool((adopted or {}).get("resubmitted")),
        "detail": run.get("detail", ""),
        # SR6：干净B结论直通（""=未验证/verifying=运行中/passed/failed）；
        # 只读投影，报告与 UI 据此展示，不在此处计算。
        "clean_status": run.get("clean_status", "") or "",
        "clean_note": run.get("clean_note", "") or "",
        # F2：恢复状态直通（""=未恢复过/recovering/recovered/unrecoverable；
        # 完成原因见 completion_reason；UI 可不消费新枚举）。
        "recovery_status": run.get("recovery_status", "") or "",
        "completion_reason": run.get("completion_reason", "") or "",
        # F5：冻结配方引用直通（内容见 run 关联产物）。
        "recipe_hash": run.get("recipe_hash", "") or "",
        "recipe_status": run.get("recipe_status", "") or "",
    }


async def adopt_running_operation(
    run_id: str, *, backend: Any, user_id: str = "", session_id: str = "",
) -> dict[str, Any]:
    """接管运行中的 operation（只查不交）。

    - 归属校验（传 user_id 即验；跨用户 FORBIDDEN，不泄露存在性以外的信息）；
    - 终态 run 直接返回终态，不碰控制服务；
    - 取未完成 attempt 的 operation_id（无则取尾部已有 id；仍无则无可接管），
      经 backend.query_operation() 续查；查询失败（失联/未知）如实返回
      unknown——任何路径都不 submit 新 operation。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        raise runs_module.RunError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if user_id and (user_id or "") != run["owner"]:
        raise runs_module.RunError("RUN_FORBIDDEN", "无权操作他人的运行")
    if session_id and (session_id or "") != run["session_id"]:
        raise runs_module.RunError("RUN_SESSION_MISMATCH", "运行与当前会话不一致")
    if run["status"] != "running":
        return {"run_id": run_id, "status": run["status"],
                "operation_id": "", "resubmitted": False}
    target = ""
    for attempt in reversed(run.get("attempts", [])):
        op_id = str(attempt.get("operation_id") or "")
        if not op_id:
            continue
        if attempt.get("exit_code") is None:
            target = op_id
            break
        if not target:
            target = op_id
    if not target:
        tail = (run.get("attempts", []) or [{}])[-1]
        target = str(tail.get("operation_id") or "")
    if not target:
        return {"run_id": run_id, "status": "running",
                "operation_id": "", "resubmitted": False}
    try:
        remote = await backend.query_operation(target)
    except Exception:
        return {"run_id": run_id, "status": "unknown",
                "operation_id": target, "resubmitted": False}
    return {"run_id": run_id,
            "status": str(remote.get("status") or "unknown"),
            "operation_id": target, "resubmitted": False}


async def console_snapshot_for(
    run_id: str, *, backend: Any = None, cursors: dict[str, int] | None = None,
) -> dict[str, Any]:
    """控制台快照（生产入口）：running run 先接管查询（只查不交）再投影。

    - backend 可用且 run 运行中 → adopt_running_operation 续查（零 submit）；
      查询失败/不可达 → console_status=reconciling，存储保持 running；
    - backend 未配置（控制面未接）→ 运行中一律 reconciling，不冒称 running；
    - 终态 run 不触碰控制面。
    F3：cursors 为 {operation_id: 已消费字节}，对活跃会话操作返回增量
    （`log_increments`）；探针采信的终态经与工具同一补记路径落盘（去重）。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    adopted: dict[str, Any] | None = None
    reachable = True
    if run is not None and run.get("status") == "running":
        if backend is None:
            reachable = False
        else:
            try:
                adopted = await adopt_running_operation(run_id, backend=backend)
                reachable = str(adopted.get("status") or "") != "unknown"
            except Exception:  # noqa: BLE001 - 接管失败按不可达处理，不改库
                adopted = None
                reachable = False
    snapshot = console_snapshot(run_id, control_reachable=reachable, adopted=adopted)
    increments: dict[str, Any] = {}
    active_op = str(snapshot.get("active_operation") or "")
    if backend is not None and active_op and run is not None \
            and run.get("status") == "running" and reachable:
        try:
            cursor = 0
            if isinstance(cursors, dict):
                try:
                    cursor = max(0, int((cursors or {}).get(active_op) or 0))
                except (TypeError, ValueError):
                    cursor = 0
            observed = await backend.query_operation(
                active_op, cursor=cursor, probe=True)
            if str(observed.get("status") or "") in (
                    "succeeded", "failed", "cancelled"):
                try:
                    from nexus import experiment_agent as agent_module

                    agent_module._record_terminal_observation(
                        run_id, backend, active_op, observed)
                except Exception:  # noqa: BLE001 - 补记失败不影响快照
                    pass
                snapshot = console_snapshot(run_id, control_reachable=reachable,
                                            adopted={
                                                "operation_id": active_op,
                                                "status": str(observed.get("status") or ""),
                                                "resubmitted": False})
                active_op = ""
            else:
                increments[active_op] = {
                    "increment": str(observed.get("increment") or ""),
                    "offset": observed.get("offset", cursor),
                    "reset": bool(observed.get("reset", False)),
                    "status": str(observed.get("status") or "running"),
                }
        except Exception:  # noqa: BLE001 - 增量失败只记空，不改快照
            pass
    snapshot["log_increments"] = increments
    return snapshot
