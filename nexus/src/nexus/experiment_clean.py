"""SR6 干净B：在全新沙箱中重放冻结配方（确定性重放，不经 LLM）。

- 重放对象是已终态 run 的冻结配方步骤（attempt 记录的实际命令序列，
  与 T6 报告配方同源同过滤）；模型不参与，不发明、不修改、不跳过命令。
- 沙箱是全新的（`{run_id}-clean1`，与原 run 沙箱零复用；工作区从空开始，
  无残留文件、无已装依赖），隔离语义沿控制服务（独立容器/网络/资源）。
- 判定：逐条比对退出码（重放 observed vs 记录 expected），全等→passed，
  任一不等→failed；重放中超时/控制面中断→如实抛错（不持久化 verdict，
  不伪装通过）。
- verdict 持久化进 run 行（clean_status/clean_note/clean_checked_at），
  报告生成时自动带出（clean 参数显式传入仍优先）。
- Ask/Auto 契约：重放会调用实验沙箱（装依赖＋执行命令），与 Ask
  “不调用实验沙箱”互斥——入口（main.clean-verify）强制
  research_execution_mode=auto（未知 400，非 auto 403），与执行门同口径。
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("nexus.experiment_clean")

CLEAN_SANDBOX_SUFFIX = "-clean1"
CLEANABLE_RUN_STATUSES = ("succeeded", "failed")
CLEAN_PASS_STATUSES = ("passed", "failed")


class CleanError(Exception):
    """干净B域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def clean_sandbox_id(run_id: str) -> str:
    """干净B沙箱 id（原 run 派生，`{run}-clean1`，截断保 64 上限）。"""
    base = (run_id or "").strip()[: 64 - len(CLEAN_SANDBOX_SUFFIX)]
    return f"{base}{CLEAN_SANDBOX_SUFFIX}"


def replayable_steps(run: dict[str, Any]) -> list[dict[str, Any]]:
    """可重放步骤（与 T6 报告配方同源同过滤：非空＋排除路由探针）。"""
    attempts = list(run.get("attempts", []) or [])
    steps: list[dict[str, Any]] = []
    for attempt in attempts:
        command = str(attempt.get("actual_command") or "")
        if not command or command.startswith("ls /workspace"):
            continue
        steps.append({
            "attempt_no": attempt.get("attempt_no", 0),
            "command": command,
            "exit_code": attempt.get("exit_code"),
        })
    return steps


async def replay_steps(
    *, run: dict[str, Any], backend: Any, step_timeout_s: int = 300,
) -> dict[str, Any]:
    """在给定 backend（已绑定干净沙箱 id）中按序重放并比对退出码。

    backend：HttpSandboxBackend（aexecute 真异步）；step_timeout_s 单步
    上限（超时→CLEAN_STEP_TIMEOUT，不记 verdict）。返回
    {"verdict", "matched", "total", "results": [...]}。
    """
    steps = replayable_steps(run)
    if not steps:
        raise CleanError("CLEAN_NO_REPLAYABLE_STEPS",
                         "本次运行没有可重放的执行命令，无法做干净验证。")
    from nexus.experiment_sandbox import ExperimentSandboxError

    results: list[dict[str, Any]] = []
    for step in steps:
        try:
            response = await backend.aexecute(
                step["command"], timeout=max(60, int(step_timeout_s or 300)))
        except ExperimentSandboxError as error:
            raise CleanError("CLEAN_REPLAY_INTERRUPTED",
                             f"重放中断（{error.code}）：{error}") from error
        observed = response.exit_code
        if observed is None:
            raise CleanError(
                "CLEAN_STEP_TIMEOUT",
                f"步骤#{step['attempt_no']} 超时未出退出码（`{step['command'][:80]}`）；"
                "未知≠通过，未持久化结论。")
        results.append({
            "attempt_no": step["attempt_no"],
            "command": step["command"][:500],
            "expected": step["exit_code"],
            "observed": int(observed),
            "match": step["exit_code"] is not None and int(observed) == int(step["exit_code"]),
        })
    matched = sum(1 for r in results if r["match"])
    verdict = "passed" if matched == len(results) else "failed"
    return {"verdict": verdict, "matched": matched, "total": len(results),
            "results": results}


def _backend_for_clean(clean_id: str) -> Any:
    """由服务端配置构造干净沙箱绑定 Backend（与实验图同源配置）。"""
    from nexus.config import get_settings
    from nexus.experiment_sandbox import ExperimentSandboxError, HttpSandboxBackend

    settings = get_settings()
    base_url = (getattr(settings, "repro_control_url", "") or "").rstrip("/")
    token = getattr(settings, "repro_control_token", "") or ""
    if not base_url:
        raise ExperimentSandboxError(
            "SANDBOX_NOT_CONFIGURED",
            "执行控制服务未配置（NEXUS_REPRO_CONTROL_URL 为空）；干净验证未执行。",
        )
    return HttpSandboxBackend(run_id=clean_id, base_url=base_url, token=token)


async def run_clean_verification(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 300,
) -> dict[str, Any]:
    """干净B编排：归属→终态→冻结提案→幂等→重放→落盘→回收。

    - 只接受本人终态 succeeded/failed 的 run（running→RUN_NOT_FINISHED，
      cancelled→RUN_CANCELLED——取消无可结论的结果，不验证）；
    - 已有 passed/failed 结论直接返回（deduped；attempt 终态后不可变，
      结论天然稳定）；
    - 新鲜沙箱执行完即 cancel 回收（best-effort，失败只记日志）。
    """
    from nexus import experiment_runs as runs_module
    from nexus import proposals as proposals_module
    from nexus.experiment_sandbox import ExperimentSandboxError

    run = runs_module.get_run(run_id)
    if run is None:
        raise CleanError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if (user_id or "") != run["owner"]:
        raise CleanError("RUN_FORBIDDEN", "无权操作他人的运行")
    if run["status"] not in CLEANABLE_RUN_STATUSES:
        if run["status"] == "cancelled":
            raise CleanError("RUN_CANCELLED", "运行已取消，无可结论的结果")
        raise CleanError(
            "RUN_NOT_FINISHED", f"运行尚未结束（现态 {run['status']}），不得做干净验证")
    proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
    if proposal is None or proposal.get("kind") != "autonomous_experiment":
        raise CleanError("RUN_PROPOSAL_UNAVAILABLE", "绑定的自主提案不可读，无法验证")
    stored_verdict = str(run.get("clean_status") or "")
    if stored_verdict in CLEAN_PASS_STATUSES:
        return {
            "run_id": run_id,
            "clean_verification": stored_verdict,
            "clean_note": str(run.get("clean_note") or ""),
            "deduped": True,
        }
    clean_id = clean_sandbox_id(run_id)
    active_backend = backend
    if active_backend is None:
        try:
            active_backend = _backend_for_clean(clean_id)
        except ExperimentSandboxError as error:
            raise CleanError("CLEAN_SANDBOX_UNAVAILABLE",
                             f"{getattr(error, 'code', type(error).__name__)}: {error}") from error
    outcome = await replay_steps(run=run, backend=active_backend,
                                 step_timeout_s=step_timeout_s)
    matched, total = outcome["matched"], outcome["total"]
    note = (f"干净沙箱 {clean_id} 重放 {total} 步，退出码一致 {matched}/{total}；"
            f"结论 {outcome['verdict']}（确定性比对，非 LLM 判定）。")
    runs_module.set_clean_verdict(run_id, outcome["verdict"], note)
    try:
        await active_backend.cancel()
    except Exception as error:  # noqa: BLE001 - 回收 best-effort
        logger.warning("clean sandbox recycle cancel failed for %s: %s",
                       clean_id, type(error).__name__)
    return {
        "run_id": run_id,
        "clean_verification": outcome["verdict"],
        "clean_note": note,
        "clean_sandbox_id": clean_id,
        "matched": matched,
        "total": total,
        "results": outcome["results"],
        "checked_at": time.time(),
        "deduped": False,
    }


def render_clean_log_markdown(run: dict[str, Any],
                              outcome: dict[str, Any]) -> str:
    """干净验证日志 Markdown（产物留痕：重放了什么、对上没有）。"""
    lines = [
        f"# 干净验证日志 · {run.get('run_id', '')}",
        "",
        f"结论：**{outcome.get('clean_verification', '')}**"
        f"（{outcome.get('matched', 0)}/{outcome.get('total', 0)} 步退出码一致）",
        f"干净沙箱：`{outcome.get('clean_sandbox_id', '')}`（一次性，重放后已回收）",
        "",
        "## 逐条比对",
        "",
    ]
    for item in outcome.get("results") or []:
        mark = "一致" if item.get("match") else "**不一致**"
        lines.append(
            f"- #{item.get('attempt_no', '')} `{item.get('command', '')}`"
            f"：记录 exit={item.get('expected', '—')}，重放 exit={item.get('observed', '—')} → {mark}")
    lines += ["",
              "判定口径：退出码全等即 passed，任一不等即 failed；"
              "指标本身仍以报告为准，本日志只证明配方在干净环境可重复执行。",
              ""]
    return "\n".join(lines)
