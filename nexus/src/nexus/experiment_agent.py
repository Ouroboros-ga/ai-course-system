"""T4 自主安装/试跑/修复循环（N3/SR5 核心）。

同一 Nexus 的实验执行图（不是新产品入口或第二个顶层主管）：
- `build_experiment_agent(backend, checkpointer, model)` 返回 Deep Agents
  编译图；原生文件与 execute 工具仅在此图启用，模型拿不到宿主路径或
  控制凭据（backend 只持 run_id＋控制服务 HTTP 身份）；
- 实例级隔离：全局 openai HarnessProfile（禁 execute/task）绝不动；
  实验图用独立 provider 键（`nexus-experiment`）装配——excluded_tools
  合并是并集语义，per-model 覆盖无法重新开放 execute，provider 分流是
  唯一实例级机制（见模块注释与测试锁定）；
- 提示约束只描述任务（自行安装/观察退出码/修依赖继续；不逐步报批；
  不改指标/数据凑 PASS，不删失败记录）；
- 长运行由独立 run 生命周期驱动：意图先落盘（run 行＋attempt），恢复先
  查已完成 operation（attempt 只在完成后追加，天然不重放）；单 run 单
  执行者（进程内锁）；HTTP/SSE 断开不杀任务（后台任务持有图执行）；
- 环境路线：repo2docker 配置检出时只记录路线并 fail-closed（构建器未
  落地前不等同基础镜像安装，T7-B 验收）；requirements/脚本项目走预置
  Python 基础容器内 pip/conda，不自写依赖求解。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger("nexus.experiment_agent")

EXPERIMENT_PROVIDER = "nexus-experiment"

# repo2docker 支持的仓库配置（检出即走构建路线；构建器未落地前该路线
# fail-closed，见 select_environment_route）。
REPO2DOCKER_MARKERS = frozenset({
    "environment.yml", "environment.yaml", "apt.txt", "Dockerfile",
    ".binder/environment.yml", ".binder/apt.txt", ".binder/Dockerfile",
})

_EXIT_CODE_RE = re.compile(r"exit code (\d+)")

# 原生文件工具（经 BaseSandbox funnel 到 execute，进控制服务即 operation）。
# T5-1 修正：attempt 按工具调用记录（与 control operation 1:1），不只记
# execute——否则 Console 的尝试列表是真子集（线上实证：7 个 op 只记 3）。
_FILE_TOOL_NAMES = frozenset({
    "write_file", "read_file", "edit_file", "ls", "glob", "grep", "delete",
})


def _register_experiment_profile() -> None:
    """注册实验图独立 provider profile（幂等 merge 语义）。

    只禁 task/子代理（Ask 防绕行口径一致）；execute 与文件工具在此
    provider 下不受限——它们只活在 run 绑定的沙箱 backend 上。
    全局 "openai" profile（主聊天三模式）绝不在此触碰。
    """
    from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

    register_harness_profile(
        EXPERIMENT_PROVIDER,
        HarnessProfile(
            excluded_tools=frozenset({"task"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _experiment_profile_registered() -> bool:
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    return EXPERIMENT_PROVIDER in _HARNESS_PROFILES


def ensure_experiment_profile() -> None:
    """幂等确保实验 profile 已注册（main lifespan 启动时调用一次）。"""
    if not _experiment_profile_registered():
        _register_experiment_profile()


class _ExperimentChatOpenAI(ChatOpenAI):
    """实验图专用模型：API 调用与 ChatOpenAI 完全一致，仅 LangSmith provider
    改为独立键，使全局 openai HarnessProfile（禁 execute/task）不命中。

    这是实例级装配的钥匙：excluded_tools 合并为并集，per-model 覆盖救不了
    execute；provider 分流后实验图命中独立 profile（仅禁 task），主聊天
    三模式继续命中 openai（禁 execute/task）。模型 id/base_url 不变，
    发往 LLM 的请求与主聊天同模型同端点。
    """

    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = EXPERIMENT_PROVIDER
        return params


def build_experiment_llm(model: str | None = None):
    """按配置构建实验图 LLM（与主聊天同模型同端点，仅 provider 键分流）。

    model：服务端 allowlist 内的模型 id（调用方已校验）；None → 默认模型。
    """
    from nexus.agent import build_llm
    from nexus.config import llm_default_model
    from nexus.config import get_settings

    llm = build_llm(model)
    if llm is None:
        return None
    settings = get_settings()
    default = llm_default_model(settings)
    return _ExperimentChatOpenAI(
        model=(model or default),
        api_key=settings.deepseek_api_key,
        base_url=settings.llm_base_url,
        temperature=0.2,
        streaming=False,
    )


EXPERIMENT_SYSTEM_PROMPT = """你是 CodeNexus 的实验执行器，正在用户已批准一次的实验授权范围内工作。
本次授权覆盖：自动安装依赖、修改依赖与启动脚本、重建任务容器、下载公开数据与重试。
你只能在当前任务沙箱内操作；宿主路径、控制凭据、其他任务对你不可见，也不得探查。

工作方式：
1. 先看 README 与环境声明（requirements.txt / environment.yml / pyproject.toml），
   自行决定安装步骤；
2. 观察每条命令的退出码与日志尾，失败就查错误、修依赖或命令后继续尝试；
3. 同一错误无进展时换策略（换源、换版本、换启动方式），不要原样重放同一命令；
4. 所有尝试都会被如实记录（命令、退出码、日志引用）；绝不为了得到 PASS 而修改
   指标、数据、随机种子或删除失败记录；没有指标依据时只报运行成功，不宣称复现论文；
5. 公开数据下载与环境重建属于本次授权，不需要也不得再请求批准。
6. 长命令可能交还 operation 引用（未出退出码）：用 describe_operation 续查
   增量输出，卡住用 interrupt_operation 中断后继续；绝不把"未出退出码"
   当失败原样重发。

环境路线由启动器按仓库声明选定并记录，本轮只在给定路线内工作。"""


def build_experiment_agent(backend: Any, checkpointer: Any = None, model: Any = None) -> Any:
    """构建实验执行图：批准后执行器传入 run 绑定的 Backend。

    backend：run 绑定的 BaseSandbox（HttpSandboxBackend；原生文件/execute
    工具经它进沙箱）。model：str 模型 id｜BaseChatModel 实例｜None（默认）。
    返回编译图（同一 Nexus 的实验执行图，非新产品入口）。
    """
    from deepagents import create_deep_agent
    from langchain.agents.middleware import TodoListMiddleware
    from langgraph.checkpoint.memory import InMemorySaver

    from nexus.agent import build_summarization_middleware

    ensure_experiment_profile()
    if model is None or isinstance(model, str):
        llm = build_experiment_llm(model)
    else:
        llm = model
    if llm is None:
        raise RuntimeError("LLM_NOT_CONFIGURED: NEXUS_DEEPSEEK_API_KEY is empty")
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    run_id = getattr(backend, "_run_id", "") or ""
    return create_deep_agent(
        model=llm,
        tools=_operation_tools(run_id, backend) if run_id else [],
        backend=backend,
        system_prompt=EXPERIMENT_SYSTEM_PROMPT,
        middleware=[
            TodoListMiddleware(),
            build_summarization_middleware(llm),
        ],
        checkpointer=saver,
    )


def _operation_tools(run_id: str, backend: Any) -> list[Any]:
    """F3：实验图窄范围操作工具（只操作当前 run，不碰他人/宿主）。

    - describe_operation：在途增量续查（探针采信终态即补记 attempt）；
    - interrupt_operation：中断卡住的命令（确认停止＋尾部输出，实验继续）。
    归属：operation_id 须属于本 run 意图账本，否则拒绝（防跨 run 操作）。
    """
    from langchain_core.tools import tool

    def _belongs(operation_id: str) -> bool:
        try:
            from nexus import experiment_operations as operations_module

            for intent in operations_module.list_run_intents(run_id):
                if str(intent.get("operation_id") or "") == operation_id:
                    return True
        except Exception:  # noqa: BLE001 - 账本不可读即拒绝
            return False
        return False

    @tool
    async def describe_operation(operation_id: str, cursor: int = 0) -> str:
        """续查一个在途操作的增量输出与状态（长命令等待/中断前先看这里）。"""
        operation_id = (operation_id or "").strip()[:128]
        if not operation_id or not _belongs(operation_id):
            return f"拒绝：{operation_id or '空 id'} 不属于当前实验，不可查询他人操作。"
        try:
            observed = await backend.query_operation(operation_id, cursor=cursor,
                                                     probe=True)
        except Exception as error:  # noqa: BLE001
            return f"查询失败（{type(error).__name__}）：{error}"[:500]
        status = str(observed.get("status") or "unknown")
        if status in ("succeeded", "failed", "cancelled"):
            _record_terminal_observation(run_id, backend, operation_id, observed)
        lines = [
            f"operation {operation_id}：{status}",
            f"exit={observed.get('exit_code')}",
        ]
        increment = str(observed.get("increment") or observed.get("output_tail") or "")
        if increment:
            lines.append("增量输出：\n" + increment[-2000:])
        if observed.get("declared_exit") is not None:
            lines.append(f"自述 EXIT:{observed.get('declared_exit')}"
                         f"（设施确认：{observed.get('facility_confirmed')}）")
        if observed.get("note"):
            lines.append(f"备注：{observed.get('note')}")
        return "\n".join(lines)[:3000]

    @tool
    async def interrupt_operation(operation_id: str) -> str:
        """中断一个卡住的命令（确认停止后继续排错；实验不终止）。"""
        operation_id = (operation_id or "").strip()[:128]
        if not operation_id or not _belongs(operation_id):
            return f"拒绝：{operation_id or '空 id'} 不属于当前实验，不可中断他人操作。"
        try:
            result = await backend.cancel_operation(operation_id)
        except Exception as error:  # noqa: BLE001
            code = getattr(error, "code", type(error).__name__)
            return f"中断失败（{code}）：{error}"[:500]
        status = str(result.get("status") or "unknown")
        if status in ("succeeded", "failed", "cancelled"):
            _record_terminal_observation(run_id, backend, operation_id, result)
        if result.get("unconfirmed"):
            return (f"operation {operation_id} 已取消但未确认停止"
                    f"（{result.get('code')}）：容器已回收待重建，原始原因保留；"
                    "换命令继续，勿重发原命令。")
        tail = str(result.get("output_tail") or "")[-1500:]
        return (f"operation {operation_id} 已中断并确认停止。尾部输出：\n{tail}\n"
                "继续排错（换依赖/命令/启动方式），不要原样重发被中断的命令。")

    return [describe_operation, interrupt_operation]


def _record_terminal_observation(
    run_id: str, backend: Any, operation_id: str, observed: dict[str, Any],
) -> None:
    """F3：工具观测到终态即补记 attempt（与 funnel 落盘互斥，去重守卫）。"""
    try:
        from nexus import experiment_runs as runs_module

        run = runs_module.get_run(run_id)
        if run is None or run.get("status") != "running":
            return
        existing = {str(a.get("operation_id") or "")
                    for a in run.get("attempts", [])}
        if operation_id in existing:
            return
        exit_code = observed.get("exit_code")
        command = ""
        try:
            from nexus import experiment_operations as operations_module

            intent = operations_module.get_intent(run_id, operation_id)
            command = str((intent or {}).get("command") or operation_id)
        except Exception:  # noqa: BLE001
            command = operation_id
        try:
            from nexus import experiment_contracts as contracts_module

            op_kind = contracts_module.classify_operation(command)
        except Exception:  # noqa: BLE001
            op_kind = "target"
        tail = str(observed.get("increment")
                   or observed.get("output_tail") or "")[-2000:]
        runs_module.record_attempt(
            run_id, actual_command=command or operation_id,
            config_changes={"kind": "execute", "op_kind": op_kind,
                            "observed_via": "operation_tool"},
            operation_id=operation_id,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            log_ref=tail)
        try:
            from nexus import experiment_operations as operations_module

            operations_module.set_intent_status(
                run_id, operation_id, str(observed.get("status") or "failed"),
                exit_code=exit_code if isinstance(exit_code, int) else None,
                output_tail=tail)
        except Exception:  # noqa: BLE001
            pass
    except Exception as error:  # noqa: BLE001 - 补记失败只记日志
        logger.warning("terminal observation backfill failed for %s: %s",
                       operation_id, type(error).__name__)


def select_environment_route(workspace_files: list[str]) -> dict[str, str]:
    """按工作区声明选择环境路线（只选择＋记录，不构建）。

    repo2docker 标记命中 → route=repo2docker（构建器未落地，执行核
    fail-closed，T7-B 验收时翻转）；否则 route=base_container（预置 Python
    基础容器内 pip/conda）。
    """
    names = {str(name).strip().lstrip("./") for name in workspace_files or []}
    hit = sorted(names & REPO2DOCKER_MARKERS)
    if hit:
        return {"route": "repo2docker",
                "reason": f"检出 repo2docker 配置：{', '.join(hit)}（构建器未落地，不等同基础镜像安装）"}
    return {"route": "base_container",
            "reason": "常规 requirements/脚本项目：预置 Python 基础容器内安装"}


def parse_exit_code(tool_content: str) -> int | None:
    """从 execute 工具结果文本解析退出码（`[Command ... with exit code N]`）。"""
    match = _EXIT_CODE_RE.search(tool_content or "")
    return int(match.group(1)) if match else None


def file_tool_summary(name: str, args: dict[str, Any]) -> str:
    """原生文件工具调用摘要（attempt 命令列，只读呈现）。"""
    args = args if isinstance(args, dict) else {}
    for key in ("file_path", "path", "pattern", "command"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return f"{name} {value.strip()[:120]}"
    return name


def file_tool_exit(msg: Any) -> int | None:
    """原生文件工具结果→退出码：ToolMessage status 成功 0、失败 1、未知 None。"""
    status = str(getattr(msg, "status", "") or "").lower()
    if status == "success":
        return 0
    if status == "error":
        return 1
    return None


def attribute_operation(
    backend: Any, command: str, used_ids: set[str],
) -> str:
    """把工具结果归因到 control operation（T5-1 精确版）。

    优先按命令文本匹配未认领的提交（execute 的 tool 参数与提交命令逐字
    一致；funnel 脚本按最近未认领回退）；并行批量下匹配不上的返回空串，
    不冒充——错的对账 id 比缺失更有害。调用方把返回的 id 记入 used_ids。
    """
    log = list(getattr(backend, "submitted_ops", None) or [])
    cleaned = (command or "").strip()
    if cleaned and not cleaned.startswith("["):
        for op_id, submitted in log:
            if op_id in used_ids:
                continue
            if cleaned == (submitted or "").strip() or cleaned in (submitted or ""):
                used_ids.add(op_id)
                return op_id
    for op_id, _submitted in reversed(log):
        if op_id not in used_ids:
            used_ids.add(op_id)
            return op_id
    if log:
        # 日志齐全但全部已认领（并行错位）：返回空串，不冒充。
        return ""
    return str(getattr(backend, "last_operation_id", "") or "")


def set_terminal_status(run_id: str, status: str, detail: str = "") -> dict[str, Any] | None:
    """终态落盘（ cancelled/succeeded/failed 互斥，不覆盖已有终态）。

    T5-1 修正：用户取消后图内后续异常/收尾不得把 cancelled 改写成 failed——
    已终态的行直接返回现态。调用方（执行者/取消者）据此返回一致结论。
    注意取消旗与 status 分离存储：取消者置旗时行仍为 running，图的后到
    failed 同样不得覆盖（线上实证的竞态）。
    F2：进入终态即强制释放执行租约（完成/取消/失败均释放；清理动作同样记录）。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        return None
    if run["status"] in ("cancelled", "succeeded", "failed"):
        return run
    if status != "cancelled" and bool(run.get("cancel_requested")):
        # 取消旗已置位而行仍为 running：收敛到 cancelled（完成用户意图），
        # 不悬空 running，更不写成 failed。
        result = runs_module.set_status(run_id, "cancelled", detail or "用户已取消。")
    else:
        result = runs_module.set_status(run_id, status, detail)
    try:
        from nexus import experiment_operations as operations_module

        operations_module.force_release_run(run_id)
    except Exception:  # noqa: BLE001 - 租约释放失败不推翻终态
        logger.warning("lease force-release failed for %s", run_id)
    return result


# 单 run 单执行者（进程内锁；跨进程/重启的执行者唯一性由 run 状态机保证：
# 只有 status=running 的 run 可被认领，认领即 CAS 式 single-flight，见下）。
_RUN_LOCKS: dict[str, asyncio.Lock] = {}
_RUN_LOCKS_GUARD = asyncio.Lock()


async def _lock_for(run_id: str) -> asyncio.Lock:
    async with _RUN_LOCKS_GUARD:
        lock = _RUN_LOCKS.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            _RUN_LOCKS[run_id] = lock
        return lock


def _backend_from_settings(run_id: str):
    """由服务端配置构造 run 绑定 Backend；未配置抛 ExperimentSandboxError。

    §2：携带 run 的授权 scope_hash 与提案冻结的 resources（控制面据此
    幂等校验与派生容器限额）。
    """
    from nexus import experiment_runs as runs_module
    from nexus.config import get_settings
    from nexus.experiment_sandbox import ExperimentSandboxError, HttpSandboxBackend

    settings = get_settings()
    base_url = (getattr(settings, "repro_control_url", "") or "").rstrip("/")
    token = getattr(settings, "repro_control_token", "") or ""
    if not base_url:
        raise ExperimentSandboxError(
            "SANDBOX_NOT_CONFIGURED",
            "执行控制服务未配置（NEXUS_REPRO_CONTROL_URL 为空）；实验未执行。",
        )
    scope_hash = ""
    resources: dict[str, Any] = {}
    initial_seq = 0
    run = runs_module.get_run(run_id)
    if run is not None:
        scope_hash = str(run.get("scope_hash") or "")
        # F2：序号由持久意图派生（现 attempt 数），Backend 重建不归零。
        try:
            initial_seq = max(0, int(run.get("attempt_no") or 0))
        except (TypeError, ValueError):
            initial_seq = 0
        try:
            from nexus import proposals as proposals_module

            proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
            if proposal is not None:
                resources = dict((proposal.get("scope") or {}).get("resources") or {})
        except Exception:  # noqa: BLE001 - 提案不可读不阻断（资源走部署默认）
            resources = {}
    return HttpSandboxBackend(run_id=run_id, base_url=base_url, token=token,
                              scope_hash=scope_hash, resources=resources,
                              initial_seq=initial_seq)


async def execute_bound_run(
    *, run_id: str, owner: str, session_id: str,
    backend: Any = None, model: Any = None, checkpointer: Any = None,
) -> dict[str, Any]:
    """执行 run 绑定的实验图（长运行生命周期入口）。

    - 意图先落盘：run 行在核销时已建；attempt 只在 operation 完成后追加，
      恢复不重放（已完成的不再提交）；
    - 单执行者：同 run 并发进入返回 already_running；
    - HTTP/SSE 断开不杀任务：调用方（批准执行入口）只负责调度，后台任务
      持有图执行直到终态；
    - 取消：启动前/结束后检查 cancel 旗；执行中的取消由控制服务操作取消
      完成（T5 接 Console 取消链），此处只做状态诚实化。
    返回终态摘要（status/attempt_no/exit 等），异常一律 fail-closed 落盘。
    """
    from nexus import experiment_runs as runs_module

    # F2：跨进程执行权（拿不到租约只观察，不执行；内存锁只防同进程）。
    holder = f"exec-{uuid.uuid4().hex[:8]}"
    fencing = ""
    try:
        from nexus import experiment_operations as operations_module

        lease = operations_module.acquire_lease(run_id, holder)
        if not lease.get("acquired"):
            current = runs_module.get_run(run_id)
            return {"status": (current or {}).get("status", "running"),
                    "deduped": True, "run_id": run_id,
                    "detail": f"执行权正由 {lease.get('holder', '')} 持有，仅观察，不重复启动。"}
        fencing = str(lease.get("fencing") or "")
    except Exception as error:  # noqa: BLE001 - 租约故障 fail-closed（不启动）
        logger.warning("lease acquire failed for %s: %s", run_id, type(error).__name__)
        current = runs_module.get_run(run_id)
        return {"status": (current or {}).get("status", "running"),
                "deduped": True, "run_id": run_id,
                "detail": "执行权账本不可用，未启动（可重试认领）。"}
    lock = await _lock_for(run_id)
    if lock.locked():
        current = runs_module.get_run(run_id)
        try:
            from nexus import experiment_operations as operations_module

            operations_module.release_lease(run_id, holder, fencing)
        except Exception:  # noqa: BLE001
            pass
        return {"status": (current or {}).get("status", "running"),
                "deduped": True, "run_id": run_id,
                "detail": "该运行已有执行者，不重复启动。"}
    async with lock:
        try:
            return await _execute_under_lock(
                run_id=run_id, owner=owner, session_id=session_id,
                backend=backend, model=model, checkpointer=checkpointer,
                fencing=fencing)
        finally:
            try:
                from nexus import experiment_operations as operations_module

                operations_module.release_lease(run_id, holder, fencing)
            except Exception:  # noqa: BLE001
                pass


async def _execute_under_lock(
    *, run_id: str, owner: str, session_id: str,
    backend: Any, model: Any, checkpointer: Any, fencing: str = "",
) -> dict[str, Any]:
    from langchain_core.messages import AIMessage

    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        return {"status": "error", "code": "RUN_NOT_FOUND", "run_id": run_id}
    if (owner or "") != run["owner"] or (session_id or "") != run["session_id"]:
        return {"status": "error", "code": "RUN_FORBIDDEN", "run_id": run_id}
    if run["status"] == "cancelled" or runs_module.is_cancel_requested(run_id):
        runs_module.set_status(run_id, "cancelled", "用户已取消，实验未启动。")
        return {"status": "cancelled", "run_id": run_id}
    if run["status"] != "running":
        return {"status": run["status"], "run_id": run_id,
                "attempt_no": run["attempt_no"], "deduped": True}
    # T7 执行前核验门（纵深防御：执行核已验，此处再验当前提案快照；
    # 旧提案无 License/未固定同样拦，fail-closed 落盘，不启动沙箱）。
    _gate_scope: dict[str, Any] = {}
    _gate_license: dict[str, Any] = {"spdx": "", "status": "unknown"}
    _gate_repo_url = ""
    _gate_revision = ""
    try:
        from nexus import license_policy as license_policy_module
        from nexus import proposals as proposals_module

        _proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
        if _proposal is not None and _proposal.get("kind") == "autonomous_experiment":
            _gate_scope = dict(_proposal.get("scope") or {})
            _gate_license = dict(_proposal.get("license") or _gate_license)
            _gate_repo_url = str(_gate_scope.get("repo_url") or "")
            _gate_revision = str(_gate_scope.get("repo_revision") or "")
        gate = license_policy_module.verify_execution_gate(
            scope=_gate_scope, license_info=_gate_license)
        if not gate["ok"]:
            runs_module.set_status(run_id, "failed", f"{gate['code']}: {gate['detail']}")
            return {"status": "failed", "run_id": run_id, "code": gate["code"]}
    except Exception as error:  # noqa: BLE001 - 门自身异常 fail-closed
        if isinstance(error, Exception) and "RUN_" in type(error).__name__:
            raise
        # verify 本身纯函数不抛；此处仅防提案读取异常。
        logger.warning("execution gate check failed for %s: %s", run_id, type(error).__name__)
        runs_module.set_status(run_id, "failed", f"GATE_UNAVAILABLE: {type(error).__name__}")
        return {"status": "failed", "run_id": run_id, "code": "GATE_UNAVAILABLE"}
    active_backend = backend
    if active_backend is None:
        try:
            active_backend = _backend_from_settings(run_id)
        except Exception as error:  # noqa: BLE001 - 未配置 fail-closed 落盘
            runs_module.set_status(
                run_id, "failed",
                f"{getattr(error, 'code', type(error).__name__)}: {error}")
            return {"status": "failed", "run_id": run_id,
                    "code": getattr(error, "code", "SANDBOX_NOT_CONFIGURED")}
    # 路线选择：列工作区声明（一次真实 ls），记录为首个 attempt。
    try:
        listing = await _list_workspace(active_backend)
    except Exception as error:  # noqa: BLE001
        runs_module.set_status(run_id, "failed", f"沙箱不可达：{type(error).__name__}")
        return {"status": "failed", "run_id": run_id, "code": "SANDBOX_UNAVAILABLE"}
    route = select_environment_route(listing)
    runs_module.record_attempt(
        run_id, actual_command="ls /workspace",
        config_changes={"route": route["route"], "reason": route["reason"],
                        "kind": "execute", "op_kind": "probe"},
        exit_code=0, log_ref="; ".join(listing[:20]))
    if route["route"] == "repo2docker":
        runs_module.set_status(
            run_id, "failed",
            f"ROUTE_NOT_DELIVERED: {route['reason']}（T7-B 验收时接入构建器）")
        return {"status": "failed", "run_id": run_id, "code": "ROUTE_NOT_DELIVERED"}
    thread_id = f"exp-{run_id}"
    runs_module.set_graph_thread(run_id, thread_id)
    # F2：绑定本次租约令牌并轮换控制面 fencing（旧持有者的迟到提交自此
    # 被拒；旧控制面无端点则降级旧语义＋日志留痕；其余轮换失败 fail-closed）。
    if fencing and hasattr(active_backend, "set_fencing"):
        try:
            active_backend.set_fencing(fencing)
            if hasattr(active_backend, "rotate_fencing"):
                await active_backend.rotate_fencing()
        except Exception as error:  # noqa: BLE001
            code = getattr(error, "code", type(error).__name__)
            if code == "FENCING_UNSUPPORTED":
                logger.warning("control plane without fencing for %s: %s",
                               run_id, code)
                try:
                    active_backend.set_fencing("")
                except Exception:  # noqa: BLE001
                    pass
            else:
                runs_module.set_status(
                    run_id, "failed", f"FENCING_ROTATE_FAILED: {code}（可重试认领）")
                return {"status": "failed", "run_id": run_id,
                        "code": "FENCING_ROTATE_FAILED"}
    try:
        agent = build_experiment_agent(active_backend, checkpointer, model)
    except Exception as error:  # noqa: BLE001
        runs_module.set_status(run_id, "failed", f"实验图构建失败：{type(error).__name__}")
        return {"status": "failed", "run_id": run_id, "code": "GRAPH_BUILD_FAILED"}
    scope_objective = ""
    try:
        from nexus import proposals as proposals_module

        proposal = proposals_module.get_proposal(run.get("proposal_id", ""))
        scope_objective = str((proposal or {}).get("objective", ""))
        # T7 门已验，此处复用门快照的仓库/修订（提案不可读则沿用门值）。
        if proposal is not None and proposal.get("kind") == "autonomous_experiment":
            _gate_scope = dict(proposal.get("scope") or _gate_scope)
            _gate_repo_url = str(_gate_scope.get("repo_url") or _gate_repo_url)
            _gate_revision = str(_gate_scope.get("repo_revision") or _gate_revision)
    except Exception:  # noqa: BLE001 - 提案不可读不阻断（scope 已冻结在 run）
        scope_objective = ""
    last_exit: int | None = None
    executed = 0
    # 命令归因：AIMessage.tool_calls（call_id→command）＋ ToolMessage
    # （tool_call_id→结果）配对；attempt 只记已完成的 operation。
    # T5-1：原生文件工具同样记录（它们经 funnel 产生 control operation）；
    # 每次落盘前检查取消旗——取消后立即收尾，不再提交新操作。
    pending_commands: dict[str, str] = {}
    file_summaries: dict[str, str] = {}
    used_operation_ids: set[str] = set()
    try:
        pin_line = ""
        if _gate_repo_url and _gate_revision:
            pin_line = (
                f"仓库 {_gate_repo_url} 必须 checkout 到 commit {_gate_revision} "
                "（已固定的配方修订；不得用分支 HEAD 替代，执行后以 git rev-parse "
                "核对，配方按此修订记录）。"
            )
        async for _stream_mode, payload in agent.astream(
                {"messages": [{"role": "user", "content": (
                    f"实验目标：{scope_objective or '按批准 scope 执行'}。"
                    f"{pin_line}"
                    "先看 README 与环境声明，然后安装、试跑，失败就地修复继续。")}]} ,
                {"configurable": {"thread_id": thread_id}},
                stream_mode=["updates"]):
            if runs_module.is_cancel_requested(run_id):
                set_terminal_status(run_id, "cancelled", "执行期间用户取消。")
                return {"status": "cancelled", "run_id": run_id,
                        "attempt_no": executed}
            for _node, delta in (payload or {}).items():
                messages = delta.get("messages") if isinstance(delta, dict) else None
                if not messages:
                    continue
                for msg in messages:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls or []:
                            call_name = call.get("name") or ""
                            if call_name == "execute":
                                pending_commands[str(call.get("id") or "")] = str(
                                    (call.get("args") or {}).get("command", ""))
                            elif call_name in _FILE_TOOL_NAMES:
                                file_summaries[str(call.get("id") or "")] = \
                                    file_tool_summary(call_name, call.get("args"))
                        continue
                    name = getattr(msg, "name", "") or ""
                    if name != "execute" and name not in _FILE_TOOL_NAMES:
                        continue
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    executed += 1
                    if name == "execute":
                        last_exit = parse_exit_code(content)
                        attempt_exit = last_exit
                        attempt_kind = "execute"
                        command = pending_commands.pop(
                            str(getattr(msg, "tool_call_id", "") or ""), "")
                    else:
                        # 文件工具只记 attempt（与 control operation 1:1 对账），
                        # 不参与终态判定——否则"命令失败后读一次文件收尾"会被
                        # 误判为执行成功（诚实性要求：exit 0 ≠ 复现成功）。
                        attempt_exit = file_tool_exit(msg)
                        attempt_kind = "file_tool"
                        command = file_summaries.pop(
                            str(getattr(msg, "tool_call_id", "") or ""), name)
                    # 对账 id 经提交日志精确归因（并行批量下不冒充）。
                    operation_id = attribute_operation(
                        active_backend, command or f"[{name}]", used_operation_ids)
                    # F1：服务端保存操作分类（启发式确定性；模型不可改写）。
                    # kind 保留旧值兼容（execute/file_tool）；op_kind 新增
                    # probe/environment/diagnostic/target/verification/file_tool。
                    from nexus import experiment_contracts as contracts_module

                    _op_kind = contracts_module.classify_operation(
                        command or f"[{name}]",
                        "file_tool" if attempt_kind == "file_tool" else "")
                    # F3：在途会话操作不记完成 attempt（只记终态；终态由
                    # describe/interrupt 工具或恢复认领补记，此处跳过）。
                    if attempt_kind == "execute" and _intent_in_flight(
                            run_id, operation_id):
                        continue
                    runs_module.record_attempt(
                        run_id, actual_command=command or f"[{name}]",
                        config_changes={"kind": attempt_kind,
                                        "op_kind": _op_kind},
                        operation_id=operation_id,
                        exit_code=attempt_exit, log_ref=content[-2000:])
    except Exception as error:  # noqa: BLE001 - 图异常 fail-closed 落盘
        logger.warning("experiment graph failed for %s: %s", run_id, type(error).__name__)
        ended = set_terminal_status(run_id, "failed", f"实验图异常：{type(error).__name__}")
        return {"status": (ended or {}).get("status", "failed"), "run_id": run_id,
                "code": "GRAPH_FAILED"}
    if runs_module.is_cancel_requested(run_id):
        set_terminal_status(run_id, "cancelled", "执行期间用户取消。")
        return {"status": "cancelled", "run_id": run_id, "attempt_no": executed}
    if executed == 0:
        set_terminal_status(run_id, "failed", "模型未执行任何命令（零尝试）。")
        return {"status": "failed", "run_id": run_id, "code": "NO_COMMANDS"}
    # F3：仍有在途会话操作 → 不强制终态（交还运行态，可恢复认领/继续观察；
    # 租约随本调用释放，源码见 execute_bound_run finally）。
    pending = _inflight_session_ops(run_id)
    if pending:
        runs_module.set_status(
            run_id, "running",
            f"图执行结束但 {len(pending)} 个操作仍在运行中（已交还；"
            "describe 续查 / interrupt 中断 / resume 认领）。")
        return {"status": "running", "run_id": run_id,
                "attempt_no": executed, "pending_operations": pending}
    terminal_exit = _last_terminal_exit(run_id)
    if terminal_exit is None:
        terminal_exit = last_exit
    if terminal_exit == 0:
        set_terminal_status(run_id, "succeeded", "末次命令退出码 0（指标 verdict 属 T6）。")
        return {"status": "succeeded", "run_id": run_id, "attempt_no": executed}
    set_terminal_status(run_id, "failed", f"末次命令退出码 {terminal_exit}（日志与配方已保留）。")
    return {"status": "failed", "run_id": run_id, "code": "LAST_COMMAND_FAILED"}


async def _list_workspace(backend: Any) -> list[str]:
    """列工作区顶层声明（路由选择用的一次真实读取）。"""
    result = await backend.aexecute("ls -a /workspace")
    names = [line.strip().split()[-1] for line in (result.output or "").splitlines()
             if line.strip()]
    return [n for n in names if n not in (".", "..")]


def _intent_in_flight(run_id: str, operation_id: str) -> bool:
    """F3：意图是否在途（submitted/running/reconciling/prepared 即未终态）。

    账本不可读即按已完成处理（不阻塞旧路径；新路径的意图必已登记）。
    """
    try:
        from nexus import experiment_operations as operations_module

        intent = operations_module.get_intent(run_id, operation_id)
    except Exception:  # noqa: BLE001
        return False
    if intent is None:
        return False
    return str(intent.get("status") or "") not in (
        "succeeded", "failed", "cancelled", "timed_out")


def _inflight_session_ops(run_id: str) -> list[str]:
    """F3：仍在途的操作 id（意图未终态且 attempt 未落盘；图收尾用）。"""
    try:
        from nexus import experiment_runs as runs_module
        from nexus import experiment_operations as operations_module

        run = runs_module.get_run(run_id)
        if run is None:
            return []
        recorded = {str(a.get("operation_id") or "")
                    for a in run.get("attempts", [])}
        return [str(i.get("operation_id") or "")
                for i in operations_module.list_run_intents(run_id)
                if str(i.get("status") or "") not in (
                    "succeeded", "failed", "cancelled", "timed_out")
                and str(i.get("operation_id") or "") not in recorded]
    except Exception:  # noqa: BLE001
        return []


def _last_terminal_exit(run_id: str) -> int | None:
    """F3：已落盘 attempt 的末次目标类退出码（含工具补记；图收尾用）。"""
    try:
        from nexus import experiment_runs as runs_module

        run = runs_module.get_run(run_id)
        if run is None:
            return None
        for attempt in reversed(run.get("attempts", [])):
            if str((attempt.get("config_changes") or {}).get("kind") or "") == "file_tool":
                continue
            if attempt.get("exit_code") is not None:
                return int(attempt["exit_code"])
    except Exception:  # noqa: BLE001
        return None
    return None


async def cancel_bound_run(
    run_id: str, user_id: str, *, backend: Any = None,
) -> dict[str, Any]:
    """取消 run 绑定的实验（用户 Cancel 语义）。

    置取消旗 → 控制服务取消当前操作 → 回收确认后终态 cancelled。
    控制服务不可达/未配置 → 返回 error（CONTROL_UNAVAILABLE），绝不伪装
    cancelled；届时取消旗仍保留，恢复可达后重试。
    模型排错时终止自己的卡住命令走 operation 级取消，不经过本入口（不触发
    “取消整个实验”的第二次确认语义）。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        return {"status": "error", "code": "RUN_NOT_FOUND", "run_id": run_id}
    if (user_id or "") != run["owner"]:
        return {"status": "error", "code": "RUN_FORBIDDEN", "run_id": run_id}
    if run["status"] != "running":
        return {"status": run["status"], "run_id": run_id,
                "already_terminal": True}
    try:
        runs_module.request_cancel(run_id, user_id)
    except runs_module.RunError as error:
        return {"status": "error", "code": error.code, "run_id": run_id}
    active_backend = backend
    if active_backend is None:
        try:
            active_backend = _backend_from_settings(run_id)
        except Exception as error:  # noqa: BLE001
            return {"status": "error",
                    "code": getattr(error, "code", "CONTROL_UNAVAILABLE"),
                    "run_id": run_id,
                    "detail": "控制服务未配置；取消旗已置位，可达后重试。"}
    try:
        result = await active_backend.cancel()
    except Exception as error:  # noqa: BLE001 - 不可达不伪装终态
        logger.warning("bound run cancel unreachable for %s: %s",
                       run_id, type(error).__name__)
        return {"status": "error", "code": "CONTROL_UNAVAILABLE",
                "run_id": run_id,
                "detail": "控制服务不可达；取消旗已置位，恢复后重试。"}
    if str((result or {}).get("status") or "") == "cancelled":
        runs_module.set_status(run_id, "cancelled", "用户取消，进程已回收确认。")
        return {"status": "cancelled", "run_id": run_id,
                "already_terminal": False}
    return {"status": "error", "code": "CANCEL_UNCONFIRMED", "run_id": run_id,
            "detail": f"取消未确认（{result})；取消旗已置位。"}


async def resume_bound_run(
    *, run_id: str, owner: str, session_id: str,
    backend: Any = None,
) -> dict[str, Any]:
    """F2：认领 running run 并对账在途意图（恢复入口第一步：只查不交）。

    - 归属/终态校验（终态直接返回，不碰控制面）；
    - 拿不到租约只观察（返回现态＋持有者，不执行）；
    - 逐条非终态意图 query 对账：终态证据→回写 attempt 并继续计数；
      running→接管计数；unknown/不可达→reconciling（禁重交）；
    - prepared 意图（已知未提交）留给图继续时提交；
    - 对账后序号对齐（backend.reset_seq），调用方据 returned
      `needs_continue` 决定是否后台继续图执行。
    返回 {"status", "recovery_status", "adopted_terminal", "adopted_running",
           "unknown", "pending_prepared", "needs_continue", ...}。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        return {"status": "error", "code": "RUN_NOT_FOUND", "run_id": run_id}
    if (owner or "") != run["owner"]:
        return {"status": "error", "code": "RUN_FORBIDDEN", "run_id": run_id}
    if (session_id or "") != run["session_id"]:
        return {"status": "error", "code": "RUN_SESSION_MISMATCH",
                "run_id": run_id}
    if run["status"] != "running":
        return {"status": run["status"], "run_id": run_id,
                "already_terminal": True, "needs_continue": False}
    from nexus import experiment_operations as operations_module

    holder = f"resume-{uuid.uuid4().hex[:8]}"
    lease = operations_module.acquire_lease(run_id, holder)
    if not lease.get("acquired"):
        return {"status": "running", "run_id": run_id,
                "recovery_status": run.get("recovery_status") or "",
                "needs_continue": False,
                "detail": f"执行权正由 {lease.get('holder', '')} 持有，仅观察。"}
    try:
        runs_module.set_recovery(run_id, "recovering", "认领恢复中：先对账在途意图。")
        active_backend = backend
        if active_backend is None:
            try:
                active_backend = _backend_from_settings(run_id)
            except Exception:  # noqa: BLE001 - 控制面未配置：如实不可恢复
                active_backend = None
        intents = operations_module.list_run_intents(run_id)
        adopted_terminal = 0
        adopted_running = 0
        unknown = 0
        pending_prepared = 0
        for intent in intents:
            istatus = str(intent.get("status") or "")
            if istatus in ("succeeded", "failed", "cancelled", "timed_out"):
                continue
            if istatus == "prepared":
                pending_prepared += 1
                continue
            operation_id = str(intent.get("operation_id") or "")
            if active_backend is None:
                operations_module.set_intent_status(
                    run_id, operation_id, "reconciling")
                unknown += 1
                continue
            try:
                remote = await active_backend.query_operation(operation_id)
            except Exception:  # noqa: BLE001 - 查询失败按未知处理，不重交
                operations_module.set_intent_status(
                    run_id, operation_id, "reconciling")
                unknown += 1
                continue
            decision = operations_module.reconcile_decision(intent, remote)
            if decision == "adopt_terminal":
                rstatus = str(remote.get("status") or "")
                exit_code = remote.get("exit_code")
                tail = str(remote.get("output_tail") or "")
                operations_module.set_intent_status(
                    run_id, operation_id, rstatus
                    if rstatus in ("succeeded", "failed", "cancelled")
                    else "failed",
                    exit_code=exit_code if isinstance(exit_code, int) else None,
                    output_tail=tail)
                try:
                    from nexus import experiment_contracts as contracts_module

                    op_kind = contracts_module.classify_operation(
                        str(intent.get("command") or ""))
                except Exception:  # noqa: BLE001
                    op_kind = "target"
                try:
                    runs_module.record_attempt(
                        run_id, actual_command=str(intent.get("command") or ""),
                        config_changes={"kind": "execute", "op_kind": op_kind,
                                        "resumed": True},
                        operation_id=operation_id,
                        exit_code=exit_code if isinstance(exit_code, int) else None,
                        log_ref=tail)
                except Exception:  # noqa: BLE001 - 补记失败不推翻对账结论
                    logger.warning("resume attempt backfill failed for %s", operation_id)
                adopted_terminal += 1
            elif decision == "adopt_running":
                operations_module.set_intent_status(
                    run_id, operation_id, "running")
                adopted_running += 1
            else:
                operations_module.set_intent_status(
                    run_id, operation_id, "reconciling")
                unknown += 1
        # 序号对齐：补记的 attempt 已占号，后续新命令不得复用旧 id。
        try:
            fresh = runs_module.get_run(run_id)
            if active_backend is not None and hasattr(active_backend, "reset_seq"):
                active_backend.reset_seq(int((fresh or {}).get("attempt_no") or 0))
        except Exception:  # noqa: BLE001
            pass
        if active_backend is None and (
                adopted_running or unknown or pending_prepared):
            reason = ("控制面不可达，在途意图无法对账；已保存材料："
                      f"终态接管 {adopted_terminal} 条。不可自动恢复。")
            runs_module.set_recovery(run_id, "unrecoverable", reason)
            return {"status": "running", "run_id": run_id,
                    "recovery_status": "unrecoverable",
                    "adopted_terminal": adopted_terminal,
                    "adopted_running": adopted_running, "unknown": unknown,
                    "pending_prepared": pending_prepared,
                    "needs_continue": False, "detail": reason}
        if unknown and not adopted_running and not adopted_terminal \
                and not pending_prepared:
            reason = ("在途意图状态未知（控制面无记录/不可达），未重复执行；"
                      "可重试认领。")
            runs_module.set_recovery(run_id, "", reason)
            return {"status": "running", "run_id": run_id,
                    "recovery_status": "",
                    "adopted_terminal": adopted_terminal,
                    "adopted_running": adopted_running, "unknown": unknown,
                    "pending_prepared": pending_prepared,
                    "needs_continue": False, "detail": reason}
        needs = bool(adopted_running or pending_prepared or adopted_terminal)
        reason = (f"对账完成：终态接管 {adopted_terminal} 条、接管运行中 "
                  f"{adopted_running} 条、待提交 {pending_prepared} 条、"
                  f"未知 {unknown} 条；"
                  + ("继续图执行。" if needs else "无待办，不启动新图。"))
        runs_module.set_recovery(run_id, "recovering", reason)
        return {"status": "running", "run_id": run_id,
                "recovery_status": "recovering",
                "adopted_terminal": adopted_terminal,
                "adopted_running": adopted_running, "unknown": unknown,
                "pending_prepared": pending_prepared,
                "needs_continue": needs, "detail": reason}
    finally:
        try:
            operations_module.release_lease(run_id, holder,
                                            str(lease.get("fencing") or ""))
        except Exception:  # noqa: BLE001
            pass


class OperationCancelError(Exception):
    """操作级取消域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


async def cancel_run_operation(
    *, run_id: str, operation_id: str, fencing: str = "",
    backend: Any = None,
) -> dict[str, Any]:
    """F3：取消本 run 的单个在途操作（HTTP 端点路径；工具走 backend 直调）。

    - 归属：run 本人 running（跨用户/终态拒绝）；operation 须属本 run 意图
      账本（未知 id → OPERATION_UNKNOWN，不重放）；
    - fencing 绑定到 backend 后下传（旧 token 由控制面拒绝）；
    - 终态观测经与工具同一补记路径落盘（去重）。
    """
    from nexus import experiment_runs as runs_module

    run = runs_module.get_run(run_id)
    if run is None:
        raise OperationCancelError("RUN_NOT_FOUND", "运行不存在或已不可恢复")
    if run.get("status") != "running":
        return {"status": run["status"], "run_id": run_id,
                "already_terminal": True, "needs_continue": False}
    try:
        from nexus import experiment_operations as operations_module

        belongs = any(
            str(i.get("operation_id") or "") == operation_id
            for i in operations_module.list_run_intents(run_id))
    except Exception:  # noqa: BLE001 - 账本不可读即拒绝
        belongs = False
    if not belongs:
        raise OperationCancelError(
            "OPERATION_UNKNOWN", f"{operation_id} 不属于本运行，不重放。")
    if backend is None:
        raise OperationCancelError("CONTROL_UNAVAILABLE", "控制面未配置。")
    if hasattr(backend, "set_fencing"):
        try:
            backend.set_fencing(fencing)
        except Exception:  # noqa: BLE001
            pass
    try:
        result = await backend.cancel_operation(operation_id)
    except Exception as error:  # noqa: BLE001
        code = getattr(error, "code", type(error).__name__)
        if code in ("OPERATION_NOT_INTERRUPTIBLE", "FENCING_REJECTED"):
            raise OperationCancelError(code, str(error)) from error
        raise OperationCancelError("CONTROL_UNAVAILABLE",
                                   f"控制面不可达：{code}") from error
    status = str(result.get("status") or "unknown")
    if status in ("succeeded", "failed", "cancelled"):
        _record_terminal_observation(run_id, backend, operation_id, result)
    return {"run_id": run_id, "operation_id": operation_id,
            "status": status,
            "unconfirmed": bool(result.get("unconfirmed", False)),
            "code": str(result.get("code") or ""),
            "output_tail": str(result.get("output_tail") or "")[-2000:],
            "interrupt_note": str(result.get("interrupt_note") or "")}
