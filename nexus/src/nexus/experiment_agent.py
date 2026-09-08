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
    return create_deep_agent(
        model=llm,
        tools=[],
        backend=backend,
        system_prompt=EXPERIMENT_SYSTEM_PROMPT,
        middleware=[
            TodoListMiddleware(),
            build_summarization_middleware(llm),
        ],
        checkpointer=saver,
    )


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
    """由服务端配置构造 run 绑定 Backend；未配置抛 ExperimentSandboxError。"""
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
    return HttpSandboxBackend(run_id=run_id, base_url=base_url, token=token)


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

    lock = await _lock_for(run_id)
    if lock.locked():
        current = runs_module.get_run(run_id)
        return {"status": (current or {}).get("status", "running"),
                "deduped": True, "run_id": run_id,
                "detail": "该运行已有执行者，不重复启动。"}
    async with lock:
        return await _execute_under_lock(
            run_id=run_id, owner=owner, session_id=session_id,
            backend=backend, model=model, checkpointer=checkpointer)


async def _execute_under_lock(
    *, run_id: str, owner: str, session_id: str,
    backend: Any, model: Any, checkpointer: Any,
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
        config_changes={"route": route["route"], "reason": route["reason"]},
        exit_code=0, log_ref="; ".join(listing[:20]))
    if route["route"] == "repo2docker":
        runs_module.set_status(
            run_id, "failed",
            f"ROUTE_NOT_DELIVERED: {route['reason']}（T7-B 验收时接入构建器）")
        return {"status": "failed", "run_id": run_id, "code": "ROUTE_NOT_DELIVERED"}
    thread_id = f"exp-{run_id}"
    runs_module.set_graph_thread(run_id, thread_id)
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
    except Exception:  # noqa: BLE001 - 提案不可读不阻断（scope 已冻结在 run）
        scope_objective = ""
    last_exit: int | None = None
    executed = 0
    # 命令归因：AIMessage.tool_calls（call_id→command）＋ ToolMessage
    # （tool_call_id→结果）配对；attempt 只记已完成的 operation。
    pending_commands: dict[str, str] = {}
    try:
        async for _stream_mode, payload in agent.astream(
                {"messages": [{"role": "user", "content": (
                    f"实验目标：{scope_objective or '按批准 scope 执行'}。"
                    "先看 README 与环境声明，然后安装、试跑，失败就地修复继续。")}]} ,
                {"configurable": {"thread_id": thread_id}},
                stream_mode=["updates"]):
            for _node, delta in (payload or {}).items():
                messages = delta.get("messages") if isinstance(delta, dict) else None
                if not messages:
                    continue
                for msg in messages:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls or []:
                            if call.get("name") == "execute":
                                pending_commands[str(call.get("id") or "")] = str(
                                    (call.get("args") or {}).get("command", ""))
                        continue
                    name = getattr(msg, "name", "") or ""
                    if name != "execute":
                        continue
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    executed += 1
                    last_exit = parse_exit_code(content)
                    command = pending_commands.pop(
                        str(getattr(msg, "tool_call_id", "") or ""), "")
                    runs_module.record_attempt(
                        run_id, actual_command=command or "[execute]",
                        exit_code=last_exit, log_ref=content[-2000:])
    except Exception as error:  # noqa: BLE001 - 图异常 fail-closed 落盘
        logger.warning("experiment graph failed for %s: %s", run_id, type(error).__name__)
        runs_module.set_status(run_id, "failed", f"实验图异常：{type(error).__name__}")
        return {"status": "failed", "run_id": run_id, "code": "GRAPH_FAILED"}
    if runs_module.is_cancel_requested(run_id):
        runs_module.set_status(run_id, "cancelled", "执行期间用户取消。")
        return {"status": "cancelled", "run_id": run_id, "attempt_no": executed}
    if executed == 0:
        runs_module.set_status(run_id, "failed", "模型未执行任何命令（零尝试）。")
        return {"status": "failed", "run_id": run_id, "code": "NO_COMMANDS"}
    if last_exit == 0:
        runs_module.set_status(run_id, "succeeded", "末次命令退出码 0（指标 verdict 属 T6）。")
        return {"status": "succeeded", "run_id": run_id, "attempt_no": executed}
    runs_module.set_status(run_id, "failed", f"末次命令退出码 {last_exit}（日志与配方已保留）。")
    return {"status": "failed", "run_id": run_id, "code": "LAST_COMMAND_FAILED"}


async def _list_workspace(backend: Any) -> list[str]:
    """列工作区顶层声明（路由选择用的一次真实读取）。"""
    result = await backend.aexecute("ls -a /workspace")
    names = [line.strip().split()[-1] for line in (result.output or "").splitlines()
             if line.strip()]
    return [n for n in names if n not in (".", "..")]
