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
- 长重放（pip 安装可达分钟级）走异步：入口只置 verifying 标记并调度
  后台任务即返；调用方轮询同一端点（幂等）或 run 详情拿结论。后台任务
  持有重放直到落盘，HTTP 断开不杀任务（与 T4 长运行同哲学）。
- 单 run 单验证者（进程内锁＋verifying 集合）；服务重启时 lifespan 把
  残留 verifying 复位为空（内存任务随进程消失，不伪装结论，可重试）。
- Ask/Auto 契约：重放会调用实验沙箱（装依赖＋执行命令），与 Ask
  “不调用实验沙箱”互斥——入口（main.clean-verify）强制
  research_execution_mode=auto（未知 400，非 auto 403），与执行门同口径。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from nexus.experiment_sandbox import HttpSandboxBackend as _HttpSandboxBackendBase

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

    backend：HttpSandboxBackend（aexecute 真异步；op id 须跨重放唯一，
    见 _ReplayBackend nonce 后缀——控制面"同 id 不运行两次"，复用 id
    会 409 误杀）；step_timeout_s 单步上限（超时如实抛
    CLEAN_STEP_TIMEOUT，不记 verdict，不回收沙箱——回收会把沙箱打成
    终态，后续重放 409 RUN_TERMINAL；容器复用，ids 唯一即无冲突）。
    返回 {"verdict", "matched", "total", "results": [...]}。
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
        match = step["exit_code"] is not None and int(observed) == int(step["exit_code"])
        logger.info("clean replay step #%s exit expected=%s observed=%s match=%s",
                    step["attempt_no"], step["exit_code"], observed, match)
        results.append({
            "attempt_no": step["attempt_no"],
            "command": step["command"][:500],
            "expected": step["exit_code"],
            "observed": int(observed),
            "match": match,
        })
    matched = sum(1 for r in results if r["match"])
    verdict = "passed" if matched == len(results) else "failed"
    return {"verdict": verdict, "matched": matched, "total": len(results),
            "results": results}


def _backend_for_clean(clean_id: str) -> Any:
    """由服务端配置构造干净沙箱绑定 Backend（与实验图同源配置）。

    op id 带 per-replay nonce 后缀（_ReplayBackend）：控制面"同 id
    不运行两次"，重试复用 id 会 409 误杀；nonce 保证每次重放 ids 唯一。
    """
    import uuid

    from nexus.config import get_settings
    from nexus.experiment_sandbox import ExperimentSandboxError

    settings = get_settings()
    base_url = (getattr(settings, "repro_control_url", "") or "").rstrip("/")
    token = getattr(settings, "repro_control_token", "") or ""
    if not base_url:
        raise ExperimentSandboxError(
            "SANDBOX_NOT_CONFIGURED",
            "执行控制服务未配置（NEXUS_REPRO_CONTROL_URL 为空）；干净验证未执行。",
        )
    return _ReplayBackend(run_id=clean_id, base_url=base_url, token=token,
                          _nonce=uuid.uuid4().hex[:8])


class _ReplayBackend(_HttpSandboxBackendBase):
    """重放专用 Backend：op id 追加 per-replay nonce（控制面去重要求）。

    基类在模块导入时解析（experiment_sandbox 只依赖 deepagents/httpx，
    无 nexus 包内循环）。
    """

    def __init__(self, *args: Any, _nonce: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._replay_nonce = (_nonce or "").strip()[:16]

    def _new_operation_id(self) -> str:
        self._op_seq += 1
        suffix = f"-{self._replay_nonce}" if self._replay_nonce else ""
        return f"{self._run_id}-op-{self._op_seq:04d}{suffix}"


async def run_clean_verification(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 300,
) -> dict[str, Any]:
    """干净B编排（同步版，测试/脚本用；HTTP 入口请用 start_clean_verification）。

    语义与异步版一致，区别是当前协程内等到落盘。归属→终态→冻结提案→
    幂等→重放→落盘→回收。
    """
    outcome = await _guarded_verify(
        run_id=run_id, user_id=user_id, backend=backend,
        step_timeout_s=step_timeout_s)
    if outcome.get("deduped"):
        return outcome
    return outcome


# 单 run 单验证者（进程内锁；verifying 集合做快速去重，见 start）。
_CLEAN_LOCKS: dict[str, asyncio.Lock] = {}
_CLEAN_LOCKS_GUARD = asyncio.Lock()
_VERIFYING: set[str] = set()


async def _lock_for(run_id: str) -> asyncio.Lock:
    async with _CLEAN_LOCKS_GUARD:
        lock = _CLEAN_LOCKS.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            _CLEAN_LOCKS[run_id] = lock
        return lock


async def start_clean_verification(
    *, run_id: str, user_id: str, step_timeout_s: int = 900,
) -> dict[str, Any]:
    """干净B入口（异步）：校验门→置 verifying→调度后台→即返。

    - 已有 passed/failed 结论直接返回（deduped，不重放）；
    - verifying 中重复触发返回 verifying（deduped，不重复调度）；
    - 新调度返回 verifying（deduped False）。调用方轮询同一端点或
      run 详情（console 快照带 clean_status）拿终态结论。
    后台完成落盘 passed/failed；重放失败（超时/中断/异常）复位为空
    （报告仍 not_run，可重试，不伪装结论）。
    """
    from nexus import experiment_runs as runs_module
    from nexus import proposals as proposals_module

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
    async with _CLEAN_LOCKS_GUARD:
        if run_id in _VERIFYING or str(
                (runs_module.get_run(run_id) or {}).get("clean_status") or "") == "verifying":
            return {"run_id": run_id, "clean_verification": "verifying",
                    "deduped": True}
        _VERIFYING.add(run_id)
    runs_module.set_clean_verdict(run_id, "verifying", "干净验证运行中（全新沙箱重放）。")

    async def _guarded() -> None:
        try:
            await _complete_clean_verification(
                run_id=run_id, user_id=user_id, step_timeout_s=step_timeout_s)
        except CleanError as error:
            logger.warning("clean verification failed for %s: %s: %s",
                           run_id, error.code, error)
            try:
                runs_module.set_clean_verdict(run_id, "", f"干净验证异常（{error.code}），可重试。")
            except Exception:  # noqa: BLE001 - 落盘失败只记日志
                logger.warning("clean reset persist failed for %s", run_id)
            finally:
                async with _CLEAN_LOCKS_GUARD:
                    _VERIFYING.discard(run_id)
        except Exception as error:  # noqa: BLE001 - 后台任务绝不裸抛
            logger.warning("clean verification failed for %s: %s",
                           run_id, type(error).__name__)
            try:
                runs_module.set_clean_verdict(run_id, "", f"干净验证异常（{type(error).__name__}），可重试。")
            except Exception:  # noqa: BLE001 - 落盘失败只记日志
                logger.warning("clean reset persist failed for %s", run_id)
            finally:
                async with _CLEAN_LOCKS_GUARD:
                    _VERIFYING.discard(run_id)

    try:
        asyncio.get_running_loop().create_task(_guarded())
    except RuntimeError as error:
        async with _CLEAN_LOCKS_GUARD:
            _VERIFYING.discard(run_id)
        runs_module.set_clean_verdict(run_id, "", "调度器无运行循环，可重试。")
        raise CleanError("CLEAN_SCHEDULER_UNAVAILABLE",
                         f"无运行循环可调度干净验证：{error}") from error
    return {"run_id": run_id, "clean_verification": "verifying",
            "deduped": False}


async def _complete_clean_verification(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 900,
) -> dict[str, Any]:
    """后台完成：重放→落盘→日志产物→回收（锁内串行；失败复位为空，可重试）。"""
    from nexus import experiment_runs as runs_module

    lock = await _lock_for(run_id)
    async with lock:
        try:
            outcome = await _guarded_verify(
                run_id=run_id, user_id=user_id, backend=backend,
                step_timeout_s=step_timeout_s, _skip_verifying_check=True)
        finally:
            async with _CLEAN_LOCKS_GUARD:
                _VERIFYING.discard(run_id)
        # 验证日志产物（best-effort：verdict 已落盘，日志写失败不推翻结论）。
        try:
            from nexus import artifact_client

            run = runs_module.get_run(run_id) or {"run_id": run_id}
            log_md = render_clean_log_markdown(run, outcome)
            await artifact_client.write_artifact_via_backend(
                artifact_type="markdown",
                title=f"干净验证日志 · {run_id[:12]}",
                content=log_md, user_id=user_id, run_id=run_id)
        except Exception as error:  # noqa: BLE001
            logger.warning("clean log artifact write failed for %s: %s",
                           run_id, type(error).__name__)
        return outcome


async def _guarded_verify(
    *, run_id: str, user_id: str, backend: Any = None,
    step_timeout_s: int = 900, _skip_verifying_check: bool = False,
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
    if not _skip_verifying_check and stored_verdict == "verifying":
        return {"run_id": run_id, "clean_verification": "verifying",
                "deduped": True}
    clean_id = clean_sandbox_id(run_id)
    active_backend = backend
    if active_backend is None:
        try:
            active_backend = _backend_for_clean(clean_id)
        except ExperimentSandboxError as error:
            raise CleanError("CLEAN_SANDBOX_UNAVAILABLE",
                             f"{getattr(error, 'code', type(error).__name__)}: {error}") from error
    try:
        outcome = await replay_steps(run=run, backend=active_backend,
                                     step_timeout_s=step_timeout_s)
    except CleanError as error:
        # 重放未完成（超时/中断）：复位为空（报告仍 not_run，可重试），
        # 不伪装 passed/failed。
        runs_module.set_clean_verdict(
            run_id, "", f"干净验证未完成（{error.code}），可重试。")
        raise
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
