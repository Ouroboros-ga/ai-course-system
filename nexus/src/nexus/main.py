"""Nexus Runtime 服务入口：FastAPI + SSE。"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from nexus import __version__
from nexus.agent import (
    InvalidNexusMode,
    InvalidNexusModel,
    build_agent,
    normalize_mode,
    normalize_model_name,
)
from nexus.config import (
    get_settings,
    llm_available_models,
    llm_default_model,
    llm_models_manifest,
)
from nexus.persistence import sanitize_session_id, sanitize_user_id, thread_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nexus")

# M1-B2/T2：按（模式, 模型, 执行模式）索引的 agent 实例（同对共享同一 checkpointer）。
# 模型网关 P0：同一 thread 命名空间跨模型共享，切模型不断上下文。
# T2：Research 区分 ask/auto（工具面不同）；General 统一 ask。
_agents: dict[tuple[str, str, str], Any] = {}
# 两个模式共享的本地降级 saver：保证 memory 模式下同 session 切模式上下文连续
# （服务器上由 lifespan 注入 AsyncPostgresSaver，两者天然共享）。
_fallback_saver = InMemorySaver()
_pg_saver: Any = None
_pg_ctx: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001, ARG001
    """P1-C lifespan：DSN 配置时启用 AsyncPostgresSaver，否则保持 InMemory 降级。

    本地 DSN 为空 → 不连 PG、不建表，零外部依赖。服务器 DSN 配置 → 建独立
    schema + nexus_threads 表 + saver.setup()，重启后同 thread 可续聊。
    任何 PG 故障都 fail-open 回 InMemory 语义（对话可用但重启即清），绝不 500。
    """
    global _agents, _pg_saver, _pg_ctx
    settings = get_settings()
    # T4：实验图独立 provider profile 与 PG 无关，两种持久化模式都注册。
    try:
        from nexus.experiment_agent import ensure_experiment_profile

        ensure_experiment_profile()
    except Exception as error:  # noqa: BLE001 - 注册失败只记日志（首次构建时重试）
        logger.warning("experiment profile register failed: %s", error)
    dsn = settings.postgres_dsn.strip()
    if dsn:
        step = "init"
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            from nexus.persistence import dsn_with_schema, ensure_threads_table_async

            schema = settings.postgres_schema
            step = "ensure_schema_threads_table"
            await ensure_threads_table_async(dsn, schema)
            step = "ensure_approvals_table"
            from nexus.approvals import ensure_approvals_table

            await asyncio.to_thread(ensure_approvals_table, dsn, schema)
            step = "ensure_proposals_table"
            from nexus.proposals import ensure_proposals_table

            await asyncio.to_thread(ensure_proposals_table, dsn, schema)
            step = "ensure_experiment_runs_table"
            from nexus.experiment_runs import ensure_runs_table

            await asyncio.to_thread(ensure_runs_table, dsn, schema)
            step = "ensure_session_prefs_table"
            from nexus.execution_mode import ensure_prefs_table

            await asyncio.to_thread(ensure_prefs_table, dsn, schema)
            step = "saver_setup"
            cm = AsyncPostgresSaver.from_conn_string(dsn_with_schema(dsn, schema))
            saver = await cm.__aenter__()
            await saver.setup()
            _pg_ctx = cm
            _pg_saver = saver
            default_model = llm_default_model(settings)
            for mode, execution_mode in (
                ("research", "auto"), ("research", "ask"), ("general", "ask"),
            ):
                _agents[(mode, default_model, execution_mode)] = build_agent(
                    mode=mode, checkpointer=saver, model=default_model,
                    execution_mode=execution_mode,
                )
            logger.info("nexus persistence: postgres enabled (schema=%s)", schema)
        except Exception as error:  # noqa: BLE001 - PG 故障不阻断服务启动
            # 只记步骤与错误类/文本，不记 DSN（见 2026-09-03 CREATE 权排查教训：
            # CREATE SCHEMA 缺权与 CONNECT 缺权的 server 文本相同，按步骤区分）。
            logger.warning("nexus persistence fallback to memory at step=%s: %s", step, error)
            _pg_ctx = None
            _pg_saver = None
    yield
    if _pg_ctx is not None:
        try:
            await _pg_ctx.__aexit__(None, None, None)
        except Exception as error:  # noqa: BLE001
            logger.warning("nexus persistence shutdown error: %s", error)
        finally:
            _pg_ctx = None
            _pg_saver = None
            _agents.clear()


app = FastAPI(title="Nexus AI Runtime", version=__version__, lifespan=lifespan)


def get_agent(
    mode: str = "general", model: str | None = None,
    execution_mode: str | None = None,
) -> Any:
    """取（模式, 模型, 执行模式）agent 实例；model 为 None 即默认模型。

    model 入参应已由 _require_model 校验；此处再做一次归一是纵深防御
    （normalize_model_name 对清单外 id 抛 InvalidNexusModel，绝不静默建实例）。

    T2 Ask/Auto：Research 实例键区分 Ask/Auto（工具面不同）；General 统一
    归一 ask（无实验执行权，传 auto 也不放行）。execution_mode 缺省 Ask
    （安全默认）。
    """
    from nexus import execution_mode as execution_mode_module

    mode = normalize_mode(mode)
    settings = get_settings()
    model = normalize_model_name(model, llm_available_models(settings), llm_default_model(settings))
    try:
        execution_key = execution_mode_module.normalize_execution_mode(
            execution_mode, mode) if execution_mode is not None else "ask"
    except execution_mode_module.InvalidExecutionMode:
        execution_key = "ask"
    if mode == "general":
        execution_key = "ask"
    key = (mode, model, execution_key)
    agent = _agents.get(key)
    if agent is None:
        # 兼容旧二元键桩（单测注入的假图不区分 Ask/Auto；生产键恒三元）。
        agent = _agents.get((mode, model))
    if agent is None:
        try:
            agent = build_agent(
                mode=mode,
                checkpointer=_pg_saver if _pg_saver is not None else _fallback_saver,
                model=model,
                execution_mode=execution_key,
            )
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        _agents[key] = agent
    return agent


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    api_key = get_settings().api_key
    if api_key and authorization != f"Bearer {api_key}":
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(default="default", max_length=128)
    # M1-B1（D2）：mode 与 context 不再被 pydantic 静默丢弃。
    # NX-G1（v1.3 A1）：mode 严格归一在 _require_mode；None 缺字段→general，
    # 未知词（含空串/空白）→ 400 INVALID_NEXUS_MODE；非 str 类型由本 schema
    # 以 422 拒绝。context 形状 M2 才消费（course_id）。
    # NX-G2：approval_id 是服务端签发的执行票据（批准后前端回传），经请求
    # 上下文注入工具——模型不可通过工具参数伪造，工具侧只做服务端核销。
    # 模型网关 P0：model 为服务端 allowlist 内的模型 id；缺字段→默认模型，
    # 未知 id 由 _require_model 以 400 拒绝（不在此静默回落）。
    # NX-A1：attachment_ids 为本次对话引用的附件（Backend 已验主+绑定会话，
    # Runtime 只读执行上下文；模型不可通过工具参数越权）。
    mode: str | None = Field(default=None, max_length=32)
    context: dict[str, Any] | None = Field(default=None)
    approval_id: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    # T2 Research Ask/Auto（前端规格 §2.1）：research_execution_mode=ask|auto，
    # 只在 Research 展示；Ask 与 Auto 唯一差别是实验代码沙箱执行权限。
    # 缺字段→默认 Ask（不从旧 Auto 偏好偷偷升级）；未知值 400
    # INVALID_RESEARCH_EXECUTION_MODE；General 兼容合法值但不产生执行授权。
    # 模型不能经工具参数修改本字段——只走请求顶层（工具侧各自校验）。
    research_execution_mode: str | None = Field(default=None, max_length=16)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    # NX-A1：附件元数据清单（Backend 验主+绑定后构建，随 payload 透传）。
    # 模型必须知道附件 id/文件名才能调用 read_attachment——只透传 id 时
    # 模型无从得知附件存在（2026-09-06 线上验收发现），故注入消息上下文。
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=5)
    # NX-LB3：请求幂等键（Backend 透传）。Runtime 以 (thread, crid) 去重：
    # 同键重试不重复调用模型/工具；不同请求竞争同会话写者 409 SESSION_BUSY。
    client_request_id: str = Field(default="", max_length=64)


def _attachment_note(attachments: list[dict[str, Any]] | None) -> str:
    """把附件清单渲染为用户消息前缀注记；空清单返回空串。"""
    if not attachments:
        return ""
    lines = ["[系统注记｜本次对话已绑定附件，read_attachment 工具可读，引用须带原文 locator]"]
    for a in attachments[:5]:
        if not isinstance(a, dict) or not a.get("attachment_id"):
            continue
        lines.append(
            "- id={id} 文件={fn} 类型={mime} 大小={size}B ocr={ocr} vision={vision}".format(
                id=str(a.get("attachment_id"))[:16],
                fn=str(a.get("filename") or "")[:80],
                mime=str(a.get("mime") or "")[:40],
                size=str(a.get("size_bytes") or 0)[:12],
                ocr=str(a.get("ocr") or "")[:16] or "unknown",
                vision=str(a.get("vision") or "")[:16] or "unknown",
            )
        )
    lines.append("[/系统注记]")
    return "\n".join(lines) + "\n\n"


def _require_mode(raw: str | None) -> str:
    """NX-G1：在启动模型/SSE 前拒绝非法 mode（v1.3 A1 冻结语义）。

    静默回落会把调用方拼写错误伪装成正常回答；未知值必须以机器可读码
    失败，让前端给出"模式无效"的确定恢复提示。
    """
    try:
        return normalize_mode(raw)
    except InvalidNexusMode as error:
        raise HTTPException(status_code=400, detail=f"INVALID_NEXUS_MODE:{error.raw!r}") from error


def _require_model(raw: str | None) -> str:
    """模型网关 P0：在启动模型前拒绝清单外模型 id。

    None 缺字段→默认模型；未知 id（含空串/空白）→ 400 INVALID_NEXUS_MODEL。
    清单唯一来源是服务端配置（config.llm_available_models），前端下拉只是
    该清单的投影，不得作为授权依据。
    """
    settings = get_settings()
    try:
        return normalize_model_name(raw, llm_available_models(settings), llm_default_model(settings))
    except InvalidNexusModel as error:
        raise HTTPException(status_code=400, detail=f"INVALID_NEXUS_MODEL:{error.raw!r}") from error


def _require_execution_mode(raw: str | None, mode: str) -> str | None:
    """T2：校验本次显式传入的执行模式（未知值 400，不读偏好兜底）。

    返回归一值（ask|auto）或 None（未传——调用方再按 resolve_effective 解析
    effective；未传不从旧 Auto 偏好偷偷升级，默认 Ask）。
    """
    from nexus import execution_mode as execution_mode_module

    if raw is None:
        return None
    try:
        return execution_mode_module.normalize_execution_mode(raw, mode)
    except execution_mode_module.InvalidExecutionMode as error:
        raise HTTPException(
            status_code=400, detail=f"INVALID_RESEARCH_EXECUTION_MODE:{error.raw!r}"
        ) from error


def _config_for(session_id: str, user_id: str | None = None) -> dict[str, Any]:
    """用户命名空间隔离的 thread 寻址；thread_id 本身不做授权，授权在后端代理层。"""
    return {"configurable": {"thread_id": thread_for(session_id, user_id)}}


async def _touch_thread(
    thread_id: str, user_id: str | None, session_id: str, title: str | None = None
) -> None:
    """upsert 线程活跃时间（仅 PG 启用时，best-effort）。"""
    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if not dsn or _pg_saver is None:
        return
    try:
        from nexus.persistence import touch_thread_sync

        await asyncio.to_thread(
            touch_thread_sync, dsn, settings.postgres_schema, thread_id, user_id, session_id, title
        )
    except Exception as error:  # noqa: BLE001
        logger.warning("touch_thread async failed: %s", error)


def _title_from_message(message: str) -> str:
    """会话标题：首条用户消息压平截断（60 字符）。"""
    flattened = " ".join((message or "").split())
    return flattened[:60]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# NX-H1：计划 revision 的进程内单调计数器（按 thread 键控）。重启后从 1
# 重新计数——前端恢复路径以 checkpoint 真值整体替换基线（planState.js），
# 流内事件只接受严格更大的 revision，因此计数器重置不会造成乱序粘住。
_plan_revisions: dict[str, int] = {}


def _next_plan_revision(thread_id: str) -> int:
    _plan_revisions[thread_id] = _plan_revisions.get(thread_id, 0) + 1
    return _plan_revisions[thread_id]


def _project_plan(session_id: str, thread_id: str, todos: Any) -> dict[str, Any] | None:
    """todos（graph state）→ 计划快照；无有效条目返回 None（不 emit）。"""
    from nexus.planning import plan_snapshot

    return plan_snapshot(session_id, todos, revision=_next_plan_revision(thread_id))


def _summarize_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content[:600]
    try:
        return json.dumps(content, ensure_ascii=False)[:600]
    except (TypeError, ValueError):
        return str(content)[:600]


# M1-B4（D4）：按工具从 JSON 结果中抽取结构化条目；条目边界截断，
# 不再对整个 JSON 做 600 字符腰斩（腰斩产物前端 JSON.parse 必失败）。
# CR4：search_cs_knowledge / search_course_materials 的条目经 "items" 显式
# 抽取——展示层截断（_ITEM_STR_MAX）只影响界面呈现，模型消费的 ToolMessage
# content 为完整 JSON（含正文与 reference_id），不受影响。
_ITEM_FIELD_BY_TOOL = {
    "web_search": "items",
    "search_arxiv_papers": "items",
    "search_cs_knowledge": "items",
    "search_course_materials": "items",
    "plan_reproduction": "plan",
    "run_reproduction": "job",
    "write_artifact": "artifact",
    # NX-R1a：证据卡结构化条目（卡片字符串字段仍受 _ITEM_STR_MAX 截断，
    # 模型消费的 ToolMessage content 为完整 JSON，不受影响）。
    "collect_paper_evidence": "evidences",
    "write_research_report": "artifact",
}
_ITEM_MAX_COUNT = 20
_ITEM_STR_MAX = 300


def _structured_tool_items(name: str, content: str) -> list[Any] | None:
    """从工具 JSON 输出抽取条目列表；非 JSON/未知形状返回 None（走旧兜底）。"""
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    field = _ITEM_FIELD_BY_TOOL.get(name or "", "items")
    raw = data.get(field)
    if field in ("plan", "job", "artifact") and isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return None

    def _cap(value: Any) -> Any:
        if isinstance(value, str):
            return value[:_ITEM_STR_MAX]
        if isinstance(value, dict):
            return {k: _cap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_cap(v) for v in value[:_ITEM_MAX_COUNT]]
        return value

    return [_cap(item) for item in raw[:_ITEM_MAX_COUNT]]


def _tool_result_payload(msg: ToolMessage) -> dict[str, Any]:
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    items = _structured_tool_items(msg.name or "", text)
    payload: dict[str, Any] = {
        "name": msg.name or "",
        "status": msg.status or "success",
        # 可解析为结构化条目时保留完整合法 JSON（前端 parse 必成功）；
        # 否则维持 600 字符字符串兜底，与既有消费方兼容。
        "content": text if items is not None else _summarize_tool_content(msg.content),
    }
    if items is not None:
        payload["items"] = items
    return _with_job_ids(payload, text)


def _with_job_ids(payload: dict[str, Any], text: str) -> dict[str, Any]:
    """NX-LB3：作业事件额外携带 run_id/job_id（服务端不得由"当前显示会话"
    决定归属）。解析失败静默跳过——只做归属标注，不改变内容语义。"""
    try:
        data = json.loads(text) if isinstance(text, str) else None
    except (TypeError, ValueError):
        return payload
    if not isinstance(data, dict):
        return payload
    job = data.get("job")
    if isinstance(job, dict) and job.get("job_id"):
        payload["job_id"] = str(job["job_id"])[:64]
    run_id = data.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        payload["run_id"] = run_id.strip()[:64]
    elif isinstance(data.get("approval_id"), str) and data["approval_id"].strip():
        # linkage 语义：run_id 即 approval_id（一批准一运行）。
        payload["run_id"] = data["approval_id"].strip()[:64]
    return payload


# ---------------------------------------------------------------------------
# NX-LB3：同会话并发/幂等控制（Runtime 单写者门 + 请求幂等注册表）。
#
# - 同一线程（user×session）一次只允许一个活动 graph 写入：不同请求竞争
#   返回 409 SESSION_BUSY（不排队）；主对话与浮窗请求共用此门。
# - client_request_id 重试不重复调用模型/工具：进行中 → 409 携带原请求
#   状态；已完成 → /chat 直接返回已存结果（deduped），/stream 回放一段
#   说明性 done 事件（内容请从会话历史恢复）。
# - 首版不建复杂排队器；断流≠执行失败，注册表提供有限状态恢复语义。
# 注册表为进程内存：重启后如实丢失（重试将重新执行），不伪造"进行中"。
# ---------------------------------------------------------------------------

_MAX_REQUEST_REGISTRY = 400

_active_threads: set[str] = set()
# (thread_id, client_request_id) -> {"status": running|done|failed,
#                                   "request_id", "started_at",
#                                   "result"(done 时 /chat 回放), "error"}
_request_registry: dict[tuple[str, str], dict[str, Any]] = {}
_registry_order: list[tuple[str, str]] = []


def _registry_remember(key: tuple[str, str], entry: dict[str, Any]) -> None:
    if key not in _request_registry:
        _registry_order.append(key)
        while len(_registry_order) > _MAX_REQUEST_REGISTRY:
            _request_registry.pop(_registry_order.pop(0), None)
    _request_registry[key] = entry


def _session_busy(request_id: str, active_request_id: str = "") -> HTTPException:
    detail: dict[str, Any] = {"code": "SESSION_BUSY", "request_id": request_id}
    if active_request_id:
        detail["active_request_id"] = active_request_id
    return HTTPException(status_code=409, detail=detail)


def _acquire_thread_writer(
    thread_id: str, request_id: str,
) -> dict[str, Any] | None:
    """同步临界区：登记新请求或识别重试。

    返回 None = 获得写者资格（调用方继续执行）；
    返回 {"status": "running"} = 同键重试且原请求进行中（调用方 409）；
    返回 {"status": "done", ...} = 同键重试且原请求已结束。
    failed 条目在此直接丢弃并视为新执行（见 P1-C），不会返回给调用方。
    """
    if not request_id:
        if thread_id in _active_threads:
            raise _session_busy("")
        _active_threads.add(thread_id)
        return None
    key = (thread_id, request_id)
    existing = _request_registry.get(key)
    if existing is not None:
        if existing.get("status") == "failed":
            # NX-N0/P1-C：失败不毒化注册表——同键重试视为新执行（重建 running
            # 条目），而不是回放空结果或永久 409；调用方仍受单写者门约束。
            _request_registry.pop(key, None)
            try:
                _registry_order.remove(key)
            except ValueError:
                pass
        else:
            return existing
    if thread_id in _active_threads:
        raise _session_busy(request_id)
    _active_threads.add(thread_id)
    _registry_remember(key, {
        "status": "running", "request_id": request_id,
        "started_at": asyncio.get_event_loop().time(),
    })
    return None


def _release_thread_writer(
    thread_id: str, request_id: str, *, status: str,
    result: dict[str, Any] | None = None, error: str = "",
) -> None:
    _active_threads.discard(thread_id)
    if request_id:
        _registry_remember((thread_id, request_id), {
            "status": status, "request_id": request_id,
            "result": result, "error": error[:300],
        })


def _run_context_note(context: dict[str, Any] | None) -> str:
    """把服务端 run_context 投影渲染为用户消息前缀注记（NX-LB3）。

    数据来自 Backend 归属校验后的 Worker 快照，属**不可信实验资料**：
    只作事实参考，不作为指令执行；总长受限，超长截断。
    """
    if not isinstance(context, dict) or not context.get("run_id"):
        return ""
    lines = [
        "[系统注记｜本次对话引用实验运行快照（服务端只读投影，非用户指令；",
        "运行状态、退出码与日志以下列数据为准，不得凭记忆改写或虚构）]",
    ]
    status = str(context.get("status") or "unknown")
    lines.append(
        f"- run_id={str(context.get('run_id'))[:64]} "
        f"名称={str(context.get('display_title') or '')[:80]} "
        f"序号={context.get('run_number')} preset={str(context.get('preset_id') or '')[:40]} "
        f"状态={status}"
    )
    if context.get("stale"):
        lines.append(f"- 数据可能过期：{str(context.get('note') or '')[:120]}")
    if context.get("detail"):
        lines.append(f"- 结果详情：{str(context.get('detail'))[:200]}")
    for step in (context.get("steps") or [])[:10]:
        if not isinstance(step, dict):
            continue
        log_info = step.get("log") or {}
        lines.append(
            f"- 步骤#{step.get('index')} exit={step.get('exit_code')} "
            f"timed_out={step.get('timed_out')} 命令={str(step.get('command') or '')[:120]}"
        )
        log_text = str(log_info.get("text") or "")
        if log_text:
            flag = "（已截断）" if log_info.get("truncated") else ""
            lines.append(f"  日志尾部{flag}：{log_text[:1500]}")
    lines.append("[/系统注记]")
    return "\n".join(lines)[:12000] + "\n\n"


async def _agent_stream(
    message: str,
    session_id: str,
    user_id: str | None = None,
    mode: str = "general",
    course_id: int | None = None,
    approval_id: str | None = None,
    model: str | None = None,
    attachment_ids: list[str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    request_id: str = "",
    run_context: dict[str, Any] | None = None,
    execution_mode: str = "ask",
):
    agent = get_agent(mode, model, execution_mode)
    thread_id = thread_for(session_id, user_id)
    inputs = {"messages": [{"role": "user", "content": (
        _attachment_note(attachments) + _run_context_note(run_context) + message
    )}]}
    config = _config_for(session_id, user_id)
    token_count = 0
    from nexus.request_scope import (
        reset_attachments,
        reset_execution_scope,
        reset_experiment_gate,
        reset_scope,
        set_attachments,
        set_execution_scope,
        set_experiment_gate,
        set_scope,
    )

    scope_tokens = set_scope(user_id, course_id)
    exec_tokens = set_execution_scope(session_id, approval_id)
    gate_tokens = set_experiment_gate(mode, execution_mode)
    attach_token = set_attachments(attachment_ids)

    async def _tag(payload: dict[str, Any]) -> dict[str, Any]:
        # NX-LB3：事件携带归属（session_id/request_id），前端不靠"当前显示
        # 会话"推断事件归属；旧客户端忽略新字段不受影响。
        return {"session_id": session_id, "request_id": request_id, **payload}

    try:
        # stream_mode 必须是列表形式：单字符串模式下 astream 产出单值，
        # 列表模式才产出 (mode, payload) 元组。
        async for stream_mode, payload in agent.astream(
            inputs, config, stream_mode=["messages", "updates"]
        ):
            if stream_mode == "messages":
                chunk, _meta = payload
                if isinstance(chunk, AIMessageChunk):
                    content = chunk.content
                    if isinstance(content, str) and content:
                        token_count += len(content)
                        yield _sse("token", await _tag({"content": content}))
            elif stream_mode == "updates":
                for _node, delta in (payload or {}).items():
                    if not isinstance(delta, dict):
                        continue
                    # NX-H1：计划投影——write_todos 的 Command 更新直接落在
                    # tools 节点 delta 的 todos 键；从真实 state update 投影，
                    # 禁止从模型自然语言解析假进度。
                    if "todos" in delta:
                        snapshot = _project_plan(session_id, thread_id, delta.get("todos"))
                        if snapshot is not None:
                            yield _sse("plan", await _tag(snapshot))
                    messages = delta.get("messages")
                    if not messages:
                        continue
                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            for call in msg.tool_calls or []:
                                yield _sse("tool_call", await _tag(
                                    {"name": call.get("name"), "args": call.get("args")}))
                        elif isinstance(msg, ToolMessage):
                            yield _sse("tool_result", await _tag(
                                _tool_result_payload(msg)))
    except asyncio.CancelledError:
        # M1-B6：客户端断开导致流被取消——如实中断，绝不补发假 done。
        _release_thread_writer(thread_id, request_id, status="failed",
                               error="client disconnected")
        raise
    except Exception as error:  # noqa: BLE001 - Agent 循环异常必须显式到流尾
        # M1-B3（D5）：done/error 互斥；错误码优先用工具/上游语义码。
        code = str(getattr(error, "code", "") or type(error).__name__)[:64]
        _release_thread_writer(thread_id, request_id, status="failed",
                               error=f"{code}: {error}")
        yield _sse("error", await _tag({"code": code, "message": str(error)[:300]}))
        return
    finally:
        reset_scope(scope_tokens)
        reset_execution_scope(exec_tokens)
        reset_experiment_gate(gate_tokens)
        reset_attachments(attach_token)
        # 写者资格兜底释放（正常/失败/取消路径已显式释放；此处防生成器
        # 在任何未捕获路径上关闭后泄漏门锁）。
        _active_threads.discard(thread_id)
    _release_thread_writer(thread_id, request_id, status="done")
    yield _sse("done", await _tag({
        "session_id": session_id, "token_count": token_count,
        "research_execution_mode": execution_mode,
    }))


def _tool_surface() -> dict[str, list[str]] | None:
    """已构建 agent 的执行器工具注册表（M0-B1 巡检口径，M1 起按模式上报）。

    模型网关 P0：键为 "mode@model:execution"，只含已实际构建的实例。不同模型
    同模式的工具面应一致；出现分歧即回归信号（某模型实例构建走了不同分支）。
    T2：Research 区分 ask/auto（Ask 不绑定 run_reproduction）。
    """
    if not _agents:
        return None
    surfaces: dict[str, list[str]] = {}
    for raw_key, agent in _agents.items():
        # 兼容旧二元键桩（单测注入）；生产键恒 (mode, model, execution)。
        if len(raw_key) == 3:
            mode, model, execution_mode = raw_key
        else:  # pragma: no cover - 仅旧测试桩形状
            mode, model = raw_key
            execution_mode = "ask"
        try:
            surfaces[f"{mode}@{model}:{execution_mode}"] = sorted(
                agent.nodes["tools"].bound.tools_by_name.keys())
        except AttributeError:
            continue
    return surfaces or None


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if not _agents and settings.deepseek_api_key:
        # 部署后无需先发起对话即可核对工具面；构建失败不阻断健康检查。
        try:
            get_agent("research")
            get_agent("general")
        except Exception:  # noqa: BLE001
            pass
    return {
        "status": "ok",
        "version": __version__,
        "llm_configured": bool(settings.deepseek_api_key),
        "searxng_configured": bool(settings.searxng_url),
        "ddgs_enabled": settings.ddgs_enabled,
        "repro_worker_configured": bool(settings.repro_worker_url),
        "persistence": "postgres" if (dsn and _pg_saver is not None) else "memory",
        "postgres_configured": bool(dsn),
        "compact": "summarization-middleware",
        "tool_surface": _tool_surface(),
        # 模型网关 P0：前端模型下拉的唯一数据源。available 为服务端 allowlist
        # 投影；新增模型改配置即出现在下拉，前端零改动。
        "models": llm_models_manifest(settings),
        # NX-G3：依赖健康快照（配置事实 ≠ 健康）。每项 {status, checked_at,
        # ttl_s}；status ∈ ok/unconfigured/degraded/unknown。只存状态与时间，
        # 不回传密钥与原始日志（v1.3 A4）。
        "checks": await _dependency_checks(),
    }


_PROBE_TIMEOUT_S = 2.0
# (status, checked_at_epoch)
_probe_cache: dict[str, tuple[str, float]] = {}


async def _probe_http(name: str, url: str, ttl_s: int) -> dict[str, Any]:
    """单依赖探测（含 TTL 缓存）：任何 HTTP 响应 = 可达(ok)；连接失败 =
    degraded；调用方保证 url 非空。探测只做轻量 GET，不带任何凭据。"""
    import time as _time

    now = _time.time()
    cached = _probe_cache.get(name)
    if cached is not None and now - cached[1] < ttl_s:
        return {"status": cached[0], "checked_at": cached[1], "ttl_s": ttl_s}
    status = "degraded"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            await client.get(url)
        status = "ok"
    except Exception:  # noqa: BLE001 - 探针失败只记状态，不抛
        status = "degraded"
    _probe_cache[name] = (status, now)
    return {"status": status, "checked_at": now, "ttl_s": ttl_s}


async def _dependency_checks() -> dict[str, Any]:
    """NX-G3 effective capability 的服务端输入：manifest ∩ mode 之外的
    "依赖 health/config" 一半。另一半（mode/权限/审批）在消费侧计算。"""
    import time as _time

    settings = get_settings()
    try:
        ttl_s = max(5, int(settings.health_probe_ttl_s))
    except Exception:  # noqa: BLE001
        ttl_s = 60
    now = _time.time()
    checks: dict[str, Any] = {
        "llm": {
            "status": "ok" if settings.deepseek_api_key else "unconfigured",
            "checked_at": now,
            "ttl_s": ttl_s,
        },
    }
    if settings.searxng_url:
        checks["searxng"] = await _probe_http(
            "searxng", f"{settings.searxng_url.rstrip('/')}/", ttl_s
        )
    else:
        checks["searxng"] = {"status": "unconfigured", "checked_at": now, "ttl_s": ttl_s}
    if settings.repro_worker_url:
        checks["repro_worker"] = await _probe_http(
            "repro_worker", f"{settings.repro_worker_url.rstrip('/')}/health", ttl_s
        )
    else:
        checks["repro_worker"] = {"status": "unconfigured", "checked_at": now, "ttl_s": ttl_s}
    internal_url = (settings.backend_internal_url or "").rstrip("/")
    if internal_url and settings.backend_internal_token:
        # 无凭据探测内部端点：任何 HTTP 响应（401/422 亦可）即证明可达；
        # 连不上才记 degraded。不发任何业务参数。
        checks["backend_internal"] = await _probe_http(
            "backend_internal",
            f"{internal_url}/api/v1/nexus-internal/cs-knowledge",
            ttl_s,
        )
    else:
        checks["backend_internal"] = {
            "status": "unconfigured", "checked_at": now, "ttl_s": ttl_s,
        }
    return checks


def _sanitize_approval_id(request: ChatRequest) -> str | None:
    """NX-G2：票据只取请求顶层字段（模型工具参数不可注入），限长截断。"""
    raw = (request.approval_id or "").strip()
    if not raw:
        return None
    return raw[:64]


def _sanitize_attachment_ids(request: ChatRequest) -> list[str]:
    """NX-A1：附件引用只取请求顶层字段（Backend 已验主+绑定，去重保序）。"""
    clean: list[str] = []
    for raw in request.attachment_ids or []:
        aid = (raw or "").strip()[:16]
        if aid and aid not in clean:
            clean.append(aid)
    return clean[:5]


def _sanitize_request_id(request: ChatRequest) -> str:
    """NX-LB3：幂等键只取请求顶层字段，限长截断（空串=不启用幂等）。"""
    return (request.client_request_id or "").strip()[:64]


def _server_run_context(request: ChatRequest) -> dict[str, Any] | None:
    """NX-LB3：只消费 Backend 生成的白名单投影（键由代理层重建，非客户端原文）。"""
    raw = (request.context or {}).get("run_context")
    return raw if isinstance(raw, dict) else None


def _replay_done_stream(session_id: str, request_id: str, entry: dict[str, Any]) -> StreamingResponse:
    """幂等重试且原请求已结束：回放说明性 done（不重复执行、不重放 token 流）。"""

    async def _gen():
        yield _sse("done", {
            "session_id": session_id,
            "request_id": request_id,
            "deduped": True,
            "status": entry.get("status", "done"),
            "note": "该请求已完成（幂等重试，未重复执行）；请从会话历史恢复内容。",
        })

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/nexus/chat/stream", dependencies=[Depends(require_api_key)])
async def chat_stream(
    request: ChatRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> StreamingResponse:
    mode = _require_mode(request.mode)
    model = _require_model(request.model)
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    # T2 Ask/Auto：显式值严格校验（未知 400）；未传默认 Ask（不偷升级）；
    # 显式合法值保存会话偏好（刷新恢复由客户端显式发送）。
    from nexus import execution_mode as execution_mode_module

    _require_execution_mode(request.research_execution_mode, mode)
    effective, _was_explicit = execution_mode_module.resolve_effective(
        request.research_execution_mode, mode,
        user_id=user_id or "", session_id=session_id,
    )
    get_agent(mode, model, effective)
    thread_id = thread_for(session_id, user_id)
    request_id = _sanitize_request_id(request)
    # NX-LB3：单写者门 + 幂等去重（先于任何执行；同步临界区，无排队器）。
    existing = _acquire_thread_writer(thread_id, request_id)
    if existing is not None:
        if existing.get("status") == "running":
            raise _session_busy(request_id, request_id)
        return _replay_done_stream(session_id, request_id, existing)
    await _touch_thread(thread_id, user_id, session_id, _title_from_message(request.message))
    return StreamingResponse(
        _agent_stream(
            request.message,
            session_id,
            user_id,
            mode,
            _context_course_id(request),
            _sanitize_approval_id(request),
            model,
            _sanitize_attachment_ids(request),
            request.attachments,
            request_id=request_id,
            run_context=_server_run_context(request),
            execution_mode=effective,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _context_course_id(request: ChatRequest) -> int | None:
    """从请求 context 提取课程 ID（M2：course_id 只信代理层转发的请求上下文）。"""
    raw = (request.context or {}).get("course_id")
    try:
        course_id = int(raw)
    except (TypeError, ValueError):
        return None
    return course_id if course_id > 0 else None


@app.post("/api/v1/nexus/chat", dependencies=[Depends(require_api_key)])
async def chat(
    request: ChatRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    mode = _require_mode(request.mode)
    model = _require_model(request.model)
    from nexus import execution_mode as execution_mode_module

    _require_execution_mode(request.research_execution_mode, mode)
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    effective, _was_explicit = execution_mode_module.resolve_effective(
        request.research_execution_mode, mode,
        user_id=user_id or "", session_id=session_id,
    )
    agent = get_agent(mode, model, effective)
    config = _config_for(session_id, user_id)
    thread_id = thread_for(session_id, user_id)
    request_id = _sanitize_request_id(request)
    # NX-LB3：单写者门 + 幂等去重（先于任何执行；同步临界区）。
    existing = _acquire_thread_writer(thread_id, request_id)
    if existing is not None:
        if existing.get("status") == "running":
            raise _session_busy(request_id, request_id)
        result = dict(existing.get("result") or {})
        result.setdefault("session_id", session_id)
        result["request_id"] = request_id
        result["deduped"] = True
        result["note"] = "幂等重试：返回已保存的原始结果，未重复执行。"
        return result
    tool_events: list[dict[str, Any]] = []
    from nexus.request_scope import (
        reset_attachments,
        reset_execution_scope,
        reset_experiment_gate,
        reset_scope,
        set_attachments,
        set_execution_scope,
        set_experiment_gate,
        set_scope,
    )

    scope_tokens = set_scope(user_id, _context_course_id(request))
    exec_tokens = set_execution_scope(session_id, _sanitize_approval_id(request))
    gate_tokens = set_experiment_gate(mode, effective)
    attach_token = set_attachments(_sanitize_attachment_ids(request))
    inputs = {
        "messages": [
            {"role": "user", "content": (
                _attachment_note(request.attachments)
                + _run_context_note(_server_run_context(request))
                + request.message
            )}
        ]
    }
    final_status = "done"
    result: dict[str, Any] | None = None
    # stream_mode 必须是列表形式：单字符串模式下 astream 产出单值，
    # 列表模式才产出 (mode, payload) 元组（与 _agent_stream 一致）。
    try:
        async for stream_mode, payload in agent.astream(inputs, config, stream_mode=["updates"]):
            for _node, delta in (payload or {}).items():
                messages = delta.get("messages") if isinstance(delta, dict) else None
                if not messages:
                    continue
                for msg in messages:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls or []:
                            tool_events.append({"name": call.get("name"), "args": call.get("args")})
                    elif isinstance(msg, ToolMessage):
                        tool_events.append(
                            {"name": msg.name or "", "status": msg.status or "success"}
                        )
        state = await agent.aget_state(config)
        final_message = ""
        for msg in reversed(state.values.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                final_message = msg.content if isinstance(msg.content, str) else str(msg.content)
                break
        # NX-H1：同步响应同样携带计划快照（真实 state 投影；无计划为 null）。
        plan = _project_plan(session_id, thread_id, state.values.get("todos"))
        await _touch_thread(thread_id, user_id, session_id, _title_from_message(request.message))
        result = {
            "session_id": session_id,
            "request_id": request_id,
            "message": final_message,
            "tool_events": tool_events,
            "plan": plan,
            "research_execution_mode": effective,
        }
    except Exception:
        final_status = "failed"
        raise
    finally:
        reset_scope(scope_tokens)
        reset_execution_scope(exec_tokens)
        reset_experiment_gate(gate_tokens)
        reset_attachments(attach_token)
        # NX-N0/P1-C：写者获取后的全部路径统一释放——模型异常、状态读取、
        # 计划投影、线程触达任一失败都不泄漏门锁；失败记 failed 供同键重试。
        _release_thread_writer(thread_id, request_id, status=final_status, result=result)
    return result


def _persisted() -> bool:
    return get_settings().postgres_dsn.strip() != "" and _pg_saver is not None


def _serialize_history(messages: list[Any]) -> list[dict[str, str]]:
    """checkpoint 消息 → 前端历史投影：只保留 user / 最终 assistant 文本。

    ToolMessage 与带 tool_calls 的中间 AI 消息不进历史（工具过程在对话时
    已以 tool_call/tool_result 呈现，历史聚焦对话内容本身）。
    """
    out: list[dict[str, str]] = []
    for msg in messages[-200:]:
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            out.append({"role": "user", "content": content[:4000]})
        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content.strip():
                out.append({"role": "assistant", "content": content[:4000]})
    return out


@app.get("/api/v1/nexus/sessions", dependencies=[Depends(require_api_key)])
async def list_sessions(
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """当前用户的会话列表（C2）：session_id + 标题 + 最近活跃时间。

    会话归属由 Backend 反代注入的 ``X-Nexus-User-Id`` 决定；未启用持久化时
    如实返回空列表（memory 模式重启即清，无历史可列）。
    """
    settings = get_settings()
    if not _persisted():
        return {"persistence": "memory", "sessions": []}
    from nexus.persistence import list_user_threads_sync

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    try:
        sessions = await asyncio.to_thread(
            list_user_threads_sync, settings.postgres_dsn.strip(), settings.postgres_schema, user_id
        )
    except Exception as error:  # noqa: BLE001 - 列表失败不阻断对话主链路
        logger.warning("list_sessions failed: %s", error)
        sessions = []
    return {"persistence": "postgres", "sessions": sessions}


@app.get(
    "/api/v1/nexus/sessions/{session_id}/messages",
    dependencies=[Depends(require_api_key)],
)
async def session_messages(
    session_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """单会话历史消息（C2/C3）：从 checkpoint 投影 user/assistant 文本。

    NX-N0/H2：读取失败是明确错误（503 CHECKPOINT_READ_FAILED），不是"无
    历史"——调用方保留缓存并标恢复失败、可重试；真正无历史才返回空列表。
    """
    agent = get_agent()
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(session_id)
    config = _config_for(session_id, user_id)
    try:
        state = await agent.aget_state(config)
    except Exception as error:  # noqa: BLE001 - 读取失败必须显式失败
        logger.warning("session_messages aget_state failed: %s", error)
        raise HTTPException(
            status_code=503, detail="CHECKPOINT_READ_FAILED"
        ) from error
    values = state.values or {}
    return {
        "session_id": session_id,
        "messages": _serialize_history(list(values.get("messages") or [])),
    }


@app.get(
    "/api/v1/nexus/plan/{session_id}",
    dependencies=[Depends(require_api_key)],
)
async def plan_snapshot_endpoint(
    session_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """NX-H1 计划恢复读取（只读）：从命名空间化 checkpoint 投影最近计划。

    复用 sessions/messages 的鉴权链（require_api_key + 反代注入的用户身份
    → thread_for 命名空间）；只返回最小白名单字段（plan_snapshot），不暴露
    checkpoint 原文。纯读取，不触发任何执行；无 checkpoint/无计划 → plan=null。
    NX-N0/H2：读取失败是明确错误（503 CHECKPOINT_READ_FAILED），不是
    plan:null——调用方保留缓存并标恢复失败、可重试；真正无计划才清空。
    """
    agent = get_agent()
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(session_id)
    config = _config_for(session_id, user_id)
    try:
        state = await agent.aget_state(config)
    except Exception as error:  # noqa: BLE001 - 读取失败必须显式失败
        logger.warning("plan_snapshot aget_state failed: %s", error)
        raise HTTPException(
            status_code=503, detail="CHECKPOINT_READ_FAILED"
        ) from error
    values = state.values or {}
    snapshot = _project_plan(
        session_id, config["configurable"]["thread_id"], values.get("todos")
    )
    return {"session_id": session_id, "plan": snapshot}


async def _fetch_repro_job(job_id: str) -> dict[str, Any]:
    """从 Worker 拉取作业记录（fail-closed：不可达/404 如实区分）。"""
    settings = get_settings()
    base = (settings.repro_worker_url or "").rstrip("/")
    if not base:
        raise ReproJobError("REPRO_WORKER_NOT_CONFIGURED", "Worker 未配置")
    headers = (
        {"Authorization": f"Bearer {settings.repro_worker_token}"}
        if settings.repro_worker_token
        else {}
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{base}/jobs/{job_id}", headers=headers)
    except Exception as error:  # noqa: BLE001 - Worker 不可达
        logger.warning("repro job fetch failed: %s", type(error).__name__)
        raise ReproJobError("REPRO_WORKER_UNAVAILABLE", f"Worker 不可达（{type(error).__name__}）") from error
    if response.status_code == 404:
        raise ReproJobError("JOB_NOT_FOUND", "作业不存在")
    try:
        return response.json()
    except ValueError as error:
        raise ReproJobError("WORKER_BAD_RESPONSE", "Worker 返回非 JSON") from error


async def _fetch_run_linkage(
    job_id: str, user_id: str | None
) -> tuple[dict[str, Any] | None, str]:
    """NX-LB2：经 Backend 内部端点取 run linkage（含冻结配置快照）。

    返回 (linkage, status)，status ∈ ok / not_found / unavailable：
    - ok：读到 linkage 行；
    - not_found：Backend 明确无此 linkage（老直批作业/他人/内部未配置的
      本地开发态）→ 调用方走 legacy preset 判定；
    - unavailable：已配置但读取失败（超时/非 200/坏 JSON）→ 调用方不得
      回退默认基线（NX-N0/P1-B），只能给无比较结论。
    """
    from nexus.artifact_client import _settings_ready

    ready = _settings_ready()
    if ready is None or not user_id:
        return None, "not_found"
    url, token = ready
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{url}/api/v1/nexus-internal/repro-runs/by-job/{job_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Nexus-User-Id": user_id,
                },
            )
    except Exception as error:  # noqa: BLE001
        logger.warning("run linkage fetch failed: %s", type(error).__name__)
        return None, "unavailable"
    if response.status_code == 404:
        return None, "not_found"
    if response.status_code != 200:
        logger.warning("run linkage unexpected status: %s", response.status_code)
        return None, "unavailable"
    try:
        data = response.json().get("data")
    except ValueError:
        return None, "unavailable"
    if not isinstance(data, dict) or not data:
        return None, "unavailable"
    return data, "ok"


class ReproJobError(Exception):
    """作业获取/状态错误：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


async def _writeback_metric_verdict(job_id: str, verdict: str, summary: str) -> None:
    """审查 F6：把报告链的真实指标判定回写 Worker metric 阶段。

    best-effort：失败只记日志，不阻断报告生成（metric 阶段将停留在
    pending，属可接受的诚实降级）；幂等由 Worker 侧 already_final 保证。
    """
    settings = get_settings()
    base = (settings.repro_worker_url or "").rstrip("/")
    if not base:
        return
    headers = (
        {"Authorization": f"Bearer {settings.repro_worker_token}"}
        if settings.repro_worker_token
        else {}
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{base}/jobs/{job_id}/metric",
                json={"verdict": verdict, "summary": summary[:500]},
                headers=headers,
            )
    except Exception as error:  # noqa: BLE001 - 回写失败不影响报告
        logger.warning("repro metric writeback failed: %s", type(error).__name__)


@app.post(
    "/api/v1/nexus/repro/jobs/{job_id}/report",
    dependencies=[Depends(require_api_key)],
)
async def repro_job_report(
    job_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """复现报告生成（M4-B3，确定性）：

    1. 从 Worker 拉取作业记录（未完成 → 409 如实返回当前状态）；
    2. 纯函数构建报告并按预设期望指标判定 PASS/FAIL（**不经 LLM**）；
    3. 把 report.md / report.json 以发起人身份写入 Artifact（复用 M3 链路）。
    """
    from nexus import repro_report
    from nexus.artifact_client import write_artifact_via_backend
    from nexus.tools.reproduction import REPRO_PRESETS

    job_id = sanitize_session_id(job_id)
    user_id = sanitize_user_id(x_nexus_user_id)
    try:
        job = await _fetch_repro_job(job_id)
    except ReproJobError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND if error.code == "JOB_NOT_FOUND" else status.HTTP_503_SERVICE_UNAVAILABLE, detail=error.code) from error
    if job.get("status") != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=f"JOB_NOT_FINISHED:{job.get('status', 'unknown')}",
        )
    preset = REPRO_PRESETS.get(str(job.get("preset_id", "")).lower())
    # NX-LB2：有 linkage 且冻结快照声明 exploratory → 探索性结论（只记实测，
    # 不做通过判定）；明确无 linkage 走 legacy preset 判定（行为不变）。
    # NX-N0/P1-B：linkage 不可读（unavailable）≠ 无 linkage——缺配置时不得
    # 回退 verified 默认基线，只能给无比较结论，且不回写任何判定。
    linkage, linkage_status = await _fetch_run_linkage(job_id, user_id)
    if linkage_status == "unavailable":
        report = repro_report.build_report(
            job=job, preset=preset,
            metric_policy={"basis": "unknown",
                           "reason": "配置快照不可读（linkage 读取失败）"})
        logger.info("linkage unreadable for job %s: no-comparison report", job_id)
    else:
        metric_policy = ((linkage or {}).get("config_snapshot") or {}).get("metric_policy")
        report = repro_report.build_report(job=job, preset=preset, metric_policy=metric_policy)
    if report["verdict"] == "EXPLORATORY":
        # Worker /metric 只接受 PASS/FAIL/INCOMPLETE：探索性无可比基线，
        # 不回写（metric 停留 pending 属诚实降级），报告产物照常生成。
        logger.info("exploratory report for job %s: skip metric writeback", job_id)
    elif report["verdict"] == "INCOMPLETE" and linkage_status == "unavailable":
        # P1-B：不可读不是"未达标"，回写 INCOMPLETE 会伪装成一次真实比较；
        # metric 停留 pending，报告正文已说明原因。
        logger.info("unavailable-linkage report for job %s: skip metric writeback", job_id)
    else:
        # F6：真实比较已完成，best-effort 回写 Worker metric 阶段（失败不阻断报告）。
        await _writeback_metric_verdict(
            job_id,
            report["verdict"],
            f"报告链判定 {report['verdict']}（{len(report['comparison'])} 项可比对指标）",
        )
    markdown = repro_report.render_report_markdown(report)
    payload_json = repro_report.render_report_json(report)
    base_title = f"复现报告 · {report['preset_id']}".strip() or "复现报告"

    artifacts: list[dict[str, Any]] = []
    # NX-LB5：报告产物关联运行（run 详情据此投影已授权 Artifact 引用）。
    run_linkage_id = str((linkage or {}).get("run_id") or "")
    for artifact_type, title, content in (
        ("markdown", base_title, markdown),
        ("markdown", f"{base_title}（原始数据 JSON）", payload_json),
    ):
        written = await write_artifact_via_backend(
            artifact_type=artifact_type, title=title, content=content, user_id=user_id,
            run_id=run_linkage_id,
        )
        if written.get("status") != "success":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"REPORT_ARTIFACT_WRITE_FAILED:{written.get('detail', '')[:120]}",
            )
        artifacts.append(written["artifact"])
    return {
        "job_id": job_id,
        "verdict": report["verdict"],
        "metrics_observed": report["metrics_observed"],
        "comparison": report["comparison"],
        "metric_note": report.get("metric_note", ""),
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# NX-G2：服务端执行审批端点族（v1.3 A3 Hard Workflow）
#
# 提案由 run_reproduction 工具在对话内创建；批准/查询/手工执行走以下端点，
# 身份一律取反代注入的 X-Nexus-User-Id（服务端登录态），不接受模型伪造。
# 产品事件最小化：只返回审批公开投影（状态/计划摘要/预算/有效期/job 引用），
# 无 Prompt、思维与原始工具参数。
# ---------------------------------------------------------------------------


class ApprovalDecision(BaseModel):
    decision: str = Field(default="approved", max_length=16)


class ApprovalExecute(BaseModel):
    approval_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(default="default", max_length=128)
    # T2 Ask/Auto 执行门：启动必须 Research+Auto+本人批准。缺字段（旧客户端）
    # 时旧 preset 票据保持兼容，自主票据 fail-closed 拒绝；未知值 400。
    mode: str | None = Field(default=None, max_length=32)
    research_execution_mode: str | None = Field(default=None, max_length=16)


def _public_approval_view(
    row: dict[str, Any] | None, preset: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if row is None:
        return None
    from nexus.tools.reproduction import _public_approval

    return _public_approval(row, preset)


def _preset_for_approval(row: dict[str, Any]) -> dict[str, Any] | None:
    from nexus.tools.reproduction import REPRO_PRESETS

    return REPRO_PRESETS.get(str(row.get("preset_id", "")).lower())


@app.get(
    "/api/v1/nexus/approvals/{approval_id}",
    dependencies=[Depends(require_api_key)],
)
async def approval_status(
    approval_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """查询审批状态（本人；跨用户 404，不泄露归属）。

    404 语义合并"不存在/他人的/重启后内存丢失"——调用方一律视为不可恢复，
    需重新提案，不凭回答编造状态。
    """
    from nexus import approvals

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    row = approvals.get_approval(sanitize_session_id(approval_id))
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="APPROVAL_NOT_FOUND")
    return {"approval": _public_approval_view(row, _preset_for_approval(row))}


@app.post(
    "/api/v1/nexus/approvals/{approval_id}/decide",
    dependencies=[Depends(require_api_key)],
)
async def approval_decide(
    approval_id: str,
    body: ApprovalDecision,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """本人批准/拒绝（幂等；过期/终态/跨用户按码拒绝，不执行任何操作）。"""
    from nexus import approvals

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    try:
        row = approvals.decide_approval(
            sanitize_session_id(approval_id), user_id, body.decision.strip().lower()
        )
    except approvals.ApprovalError as error:
        status_map = {
            "APPROVAL_NOT_FOUND": 404,
            "APPROVAL_FORBIDDEN": 403,
            "APPROVAL_EXPIRED": 409,
            "APPROVAL_STATE_CONFLICT": 409,
            "APPROVAL_BAD_DECISION": 422,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 409), detail=error.code
        ) from error
    return {"approval": _public_approval_view(row, _preset_for_approval(row))}


@app.post(
    "/api/v1/nexus/repro/execute",
    dependencies=[Depends(require_api_key)],
)
async def repro_execute_approved(
    body: ApprovalExecute,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """手工执行入口：凭已批准票据提交 Worker（与聊天工具共用同一核销核心）。

    前端审批卡"批准并执行"调此端点——不经 LLM，避免模型是否重调工具的
    不确定性。幂等：同一票据重试返回原 job。
    """
    from nexus import approvals
    from nexus.tools.reproduction import execute_approved_reproduction

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    session_id = sanitize_session_id(body.session_id)
    approval_id = sanitize_session_id(body.approval_id)
    row = approvals.get_approval(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="APPROVAL_NOT_FOUND")
    preset_id = str(row.get("preset_id", ""))
    # T2 Ask/Auto 门：mode 未知→400；执行模式未知→400；缺字段时旧 preset
    # 票据兼容，自主票据由执行核 fail-closed。
    mode = _require_mode(body.mode) if body.mode is not None else None
    if body.research_execution_mode is not None:
        _require_execution_mode(body.research_execution_mode, mode or "research")
    try:
        return await execute_approved_reproduction(
            approval_id=approval_id,
            user_id=user_id,
            session_id=session_id,
            preset_id=preset_id,
            mode=mode,
            research_execution_mode=body.research_execution_mode,
        )
    except approvals.ApprovalError as error:
        status_map = {
            "APPROVAL_NOT_FOUND": 404,
            "APPROVAL_FORBIDDEN": 403,
            "APPROVAL_SESSION_MISMATCH": 403,
            "APPROVAL_NOT_APPROVED": 409,
            "APPROVAL_EXPIRED": 409,
            "APPROVAL_PLAN_CHANGED": 409,
            "APPROVAL_PROPOSAL_CHANGED": 409,
            "APPROVAL_KIND_MISMATCH": 409,
            "APPROVAL_SCOPE_MISSING": 409,
            "EXPERIMENT_EXECUTION_DISABLED": 403,
            "APPROVAL_RUN_UNAVAILABLE": 503,
            "RUN_FORBIDDEN": 403,
            "RUN_SESSION_MISMATCH": 403,
            "RUN_NOT_FOUND": 404,
            "RUN_TERMINAL": 409,
            # T7 执行前核验门（需经 intake 固定 revision/确认 License 后建新提案）。
            "REVISION_NOT_PINNED": 409,
            "LICENSE_UNVERIFIED": 409,
            "LICENSE_NOT_ALLOWED": 409,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 409), detail=error.code
        ) from error


# ---------------------------------------------------------------------------
# T5：自主 run 控制台读模型＋取消（Backend provider 分支的 Runtime 侧）。
# 前端不直连控制服务；Backend 经本端点拿快照/执行取消（服务令牌＋用户身份）。
# ---------------------------------------------------------------------------


async def _aprobe_console_reachable(run_id: str) -> bool:
    """控制服务可达性探针（轻量 lifecycle 查询；任何失败即不可达）。"""
    try:
        from nexus.experiment_agent import _backend_from_settings

        backend = _backend_from_settings(run_id)
    except Exception:
        return False
    try:
        await backend.sandbox_status()
        return True
    except Exception:
        return False


@app.get(
    "/api/v1/nexus/repro/runs/{run_id}/console",
    dependencies=[Depends(require_api_key)],
)
async def repro_run_console(
    run_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """T5：自主 run 控制台快照（只读投影，不触发任何执行）。

    本人 run 才可见（跨用户/不存在一律 404，不区分）；控制失联时
    console_status=reconciling（存储快照仍为 running，不冒称终态）。
    """
    from nexus import experiment_runs as runs_module
    from nexus import experiment_store as store_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    run = runs_module.get_run(sanitize_session_id(run_id))
    if run is None or (user_id or "") != run["owner"]:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    snapshot = store_module.console_snapshot(
        run["run_id"], control_reachable=await _aprobe_console_reachable(run["run_id"]))
    return {"snapshot": snapshot}


@app.post(
    "/api/v1/nexus/repro/runs/{run_id}/cancel",
    dependencies=[Depends(require_api_key)],
)
async def repro_run_cancel(
    run_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """T5：取消自主 run（用户 Cancel 语义：置旗＋操作取消＋回收确认）。

    回收确认后终态 cancelled；控制不可达/未配置 → 503（不伪装取消）。
    """
    from nexus import experiment_agent as agent_module
    from nexus import experiment_runs as runs_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    run = runs_module.get_run(sanitize_session_id(run_id))
    if run is None or (user_id or "") != run["owner"]:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    result = await agent_module.cancel_bound_run(run["run_id"], user_id)
    if result.get("status") == "error":
        status_map = {
            "RUN_NOT_FOUND": 404,
            "RUN_FORBIDDEN": 403,
            "CONTROL_UNAVAILABLE": 503,
            "CANCEL_UNCONFIRMED": 502,
        }
        raise HTTPException(
            status_code=status_map.get(str(result.get("code") or ""), 409),
            detail=str(result.get("code") or "CANCEL_FAILED"),
        )
    return result


@app.post(
    "/api/v1/nexus/repro/runs/{run_id}/report",
    dependencies=[Depends(require_api_key)],
)
async def repro_run_report(
    run_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """T6：自主 run 报告＋配方生成（确定性拼装，不经 LLM）。

    本人终态（succeeded/failed）run 才可生成；产物经既有 Artifact 链写入并
    关联本 run；两个产物落盘后才回收可变工作区。跨用户/不存在一律 404。
    """
    from nexus import experiment_report as report_module
    from nexus import experiment_runs as runs_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    run = runs_module.get_run(sanitize_session_id(run_id))
    if run is None or (user_id or "") != run["owner"]:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    try:
        from nexus.experiment_agent import _backend_from_settings

        backend: Any = _backend_from_settings(run["run_id"])
    except Exception:
        backend = None
    try:
        return await report_module.generate_run_report(
            run_id=run["run_id"], user_id=user_id, backend=backend)
    except report_module.ReportError as error:
        status_map = {
            "RUN_NOT_FOUND": 404,
            "RUN_FORBIDDEN": 403,
            "RUN_NOT_FINISHED": 409,
            "RUN_CANCELLED": 409,
            "RUN_PROPOSAL_UNAVAILABLE": 409,
            "REPORT_ARTIFACT_WRITE_FAILED": 502,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 409), detail=error.code
        ) from error


class CleanVerifyRequest(BaseModel):
    """SR6 干净B请求体：重放调用实验沙箱，只接受 Auto（Ask 403）。"""

    research_execution_mode: str | None = Field(default=None, max_length=16)

    model_config = {"extra": "forbid"}


@app.post(
    "/api/v1/nexus/repro/runs/{run_id}/formats",
    dependencies=[Depends(require_api_key)],
)
async def repro_run_formats(
    run_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """SR6：自主 run 正式格式产物（Word .docx＋LaTeX .tex，确定性转换）。

    与报告同门（本人终态 run）；内容与 T6 Markdown 同源同版本；不经 LLM、
    不触碰沙箱（纯渲染，Ask 下可用）。跨用户/不存在一律 404。
    """
    from nexus import experiment_report as report_module
    from nexus import experiment_runs as runs_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    run = runs_module.get_run(sanitize_session_id(run_id))
    if run is None or (user_id or "") != run["owner"]:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    try:
        return await report_module.generate_run_formats(
            run_id=run["run_id"], user_id=user_id)
    except report_module.FormatError as error:
        status_map = {
            "RUN_NOT_FOUND": 404,
            "RUN_FORBIDDEN": 403,
            "RUN_NOT_FINISHED": 409,
            "RUN_CANCELLED": 409,
            "RUN_PROPOSAL_UNAVAILABLE": 409,
            "FORMAT_BUILD_FAILED": 502,
            "FORMAT_ARTIFACT_WRITE_FAILED": 502,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 409), detail=error.code
        ) from error


@app.post(
    "/api/v1/nexus/repro/runs/{run_id}/clean-verify",
    dependencies=[Depends(require_api_key)],
)
async def repro_run_clean_verify(
    run_id: str,
    body: CleanVerifyRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """SR6：自主 run 干净B验证（全新沙箱重放冻结配方，比对退出码）。

    只接受本人终态（succeeded/failed）run；结论幂等（已有 passed/failed
    直接返回，不重放）；新鲜沙箱用后即回收。重放调用实验沙箱——执行门
    强制 Auto（未知 400，非 auto 403，与 Ask/Auto 契约同口径）。
    跨用户/不存在一律 404。
    """
    from nexus import experiment_clean as clean_module
    from nexus import experiment_runs as runs_module

    mode = (body.research_execution_mode or "ask").strip().lower()
    if mode not in ("ask", "auto"):
        raise HTTPException(status_code=400, detail="INVALID_RESEARCH_EXECUTION_MODE")
    if mode != "auto":
        raise HTTPException(status_code=403, detail="CLEAN_EXECUTION_DISABLED")
    user_id = sanitize_user_id(x_nexus_user_id) or ""
    run = runs_module.get_run(sanitize_session_id(run_id))
    if run is None or (user_id or "") != run["owner"]:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    try:
        outcome = await clean_module.run_clean_verification(
            run_id=run["run_id"], user_id=user_id)
    except clean_module.CleanError as error:
        status_map = {
            "RUN_NOT_FOUND": 404,
            "RUN_FORBIDDEN": 403,
            "RUN_NOT_FINISHED": 409,
            "RUN_CANCELLED": 409,
            "RUN_PROPOSAL_UNAVAILABLE": 409,
            "CLEAN_NO_REPLAYABLE_STEPS": 409,
            "CLEAN_SANDBOX_UNAVAILABLE": 503,
            "CLEAN_REPLAY_INTERRUPTED": 502,
            "CLEAN_STEP_TIMEOUT": 504,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 409), detail=error.code
        ) from error
    # 验证日志产物（best-effort： verdict 已落盘，日志写失败不推翻结论）。
    from nexus import artifact_client

    log_md = clean_module.render_clean_log_markdown(run, outcome)
    written = await artifact_client.write_artifact_via_backend(
        artifact_type="markdown", title=f"干净验证日志 · {run['run_id'][:12]}",
        content=log_md, user_id=user_id, run_id=run["run_id"])
    artifacts: list[dict[str, Any]] = []
    if written.get("status") == "success":
        artifacts.append(written["artifact"])
    return {**outcome, "artifacts": artifacts,
            "log_artifact_written": bool(artifacts)}


# ---------------------------------------------------------------------------
# NX-LB1/LB2：preset 投影＋结构化提案＋审批待办（Runtime 自有域编排）


# ---------------------------------------------------------------------------
# NX-LB1/LB2：preset 投影＋结构化提案＋审批待办（Runtime 自有域编排）
#
# 身份一律取反代注入的 X-Nexus-User-Id（服务端登录态）；parent run 归属经
# Backend 内部 run 详情校验（Runtime 不持有 run 表）。
# 产品事件最小化：只返回方案/计划摘要/预算/有效期，无 Prompt 与思维。
# ---------------------------------------------------------------------------


class ProposalCreate(BaseModel):
    preset_id: str = Field(default="", max_length=64)
    session_id: str = Field(default="default", max_length=128)
    parent_run_id: str = Field(default="", max_length=64)
    objective: str = Field(default="", max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    client_request_id: str = Field(default="", max_length=64)
    # T2 自主提案：kind 缺省 preset；kind=autonomous_experiment 时消费
    # scope（ExperimentScope），不要求 preset_id。
    kind: str = Field(default="preset", max_length=32)
    scope: dict[str, Any] | None = Field(default=None)


class ProposalPatch(BaseModel):
    expected_version: int = Field(ge=1)
    objective: str | None = Field(default=None, max_length=500)
    parameters: dict[str, Any] | None = None
    # T2：自主提案改 scope（preset 提案传 scope 422）。
    scope: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


class ProposalRequestApproval(BaseModel):
    expected_version: int = Field(ge=1)


async def _fetch_parent_run(
    run_id: str, user_id: str
) -> dict[str, Any] | None:
    """经 Backend 内部端点取本人的 parent run 全行（404→None，不抛）。"""
    from nexus.artifact_client import _settings_ready

    ready = _settings_ready()
    if ready is None or not user_id:
        return None
    url, token = ready
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{url}/api/v1/nexus-internal/repro-runs/{run_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Nexus-User-Id": user_id,
                },
            )
    except Exception as error:  # noqa: BLE001
        logger.warning("parent run fetch failed: %s", type(error).__name__)
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json().get("data") or {}
    except ValueError:
        return None


def _proposal_error_status(code: str) -> int:
    return {
        "PROPOSAL_NOT_FOUND": 404,
        "PROPOSAL_FORBIDDEN": 403,
        "PROPOSAL_PRESET_UNSUPPORTED": 422,
        "PROPOSAL_PARAM_UNKNOWN": 422,
        "PROPOSAL_PARAM_TYPE": 422,
        "PROPOSAL_PARAM_OUT_OF_RANGE": 422,
        "PROPOSAL_DATA_UNSUPPORTED": 422,
        "PROPOSAL_VERSION_CONFLICT": 409,
        "PROPOSAL_LOCKED": 409,
        "PROPOSAL_PERSIST_FAILED": 503,
        "PROPOSAL_APPROVAL_CREATE_FAILED": 503,
        "PROPOSAL_PARENT_NOT_FOUND": 404,
        "PROPOSAL_KIND_UNSUPPORTED": 422,
        "PROPOSAL_KIND_MISMATCH": 422,
        "PROPOSAL_SCOPE_INVALID": 422,
    }.get(code, 422)


@app.get(
    "/api/v1/nexus/repro/presets",
    dependencies=[Depends(require_api_key)],
)
async def repro_presets() -> dict[str, Any]:
    """NX-LB1：可见 preset 投影（Backend 经内部 HTTP 拉取，不跨环境 import）。

    只读：display/论文/仓库/License/环境摘要/参数 schema/预算/指标与来源/
    能力限制；无凭据、内部路径、任意命令入口。
    """
    from nexus import proposals as proposals_module

    return {"presets": proposals_module.list_preset_projections()}


@app.post(
    "/api/v1/nexus/repro/proposals",
    dependencies=[Depends(require_api_key)],
)
async def repro_proposal_create(
    body: ProposalCreate,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """NX-LB2：建结构化提案草案（不执行；client_request_id 幂等）。

    T2：kind 缺省 preset；kind=autonomous_experiment 时消费 scope，
    不要求 preset_id。
    """
    from nexus import proposals as proposals_module
    from nexus.tools.reproduction import REPRO_PRESETS

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    session_id = sanitize_session_id(body.session_id)
    kind = (body.kind or "preset").strip()
    preset = None
    if kind == "autonomous_experiment":
        if (body.preset_id or "").strip():
            raise HTTPException(status_code=422, detail="PROPOSAL_KIND_MISMATCH")
    else:
        if kind != "preset":
            raise HTTPException(status_code=422, detail="PROPOSAL_KIND_UNSUPPORTED")
        preset = REPRO_PRESETS.get(body.preset_id.strip().lower())
        if preset is None:
            raise HTTPException(status_code=404, detail="PRESET_NOT_FOUND")
    parent_run: dict[str, Any] | None = None
    if body.parent_run_id.strip():
        parent_run = await _fetch_parent_run(body.parent_run_id.strip()[:64], user_id)
        if parent_run is None:
            raise HTTPException(status_code=404, detail="PROPOSAL_PARENT_NOT_FOUND")
    try:
        row = proposals_module.create_proposal(
            user_id=user_id,
            session_id=session_id,
            preset=preset,
            parent_run=parent_run,
            objective=body.objective,
            parameters=body.parameters,
            data=body.data,
            client_request_id=body.client_request_id,
            kind=kind,
            scope=body.scope,
        )
    except proposals_module.ProposalError as error:
        raise HTTPException(
            status_code=_proposal_error_status(error.code), detail=error.code
        ) from error
    return {"proposal": proposals_module.public_proposal_view(row),
            "deduped": bool(row.get("deduped"))}


@app.get(
    "/api/v1/nexus/repro/proposals/{proposal_id}",
    dependencies=[Depends(require_api_key)],
)
async def repro_proposal_detail(
    proposal_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """NX-LB2：提案完整方案＋校验结果＋与父运行/上一版本的 diff。"""
    from nexus import proposals as proposals_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    row = proposals_module.get_proposal(sanitize_session_id(proposal_id))
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="PROPOSAL_NOT_FOUND")
    view = proposals_module.public_proposal_view(row)
    diff_parent = None
    if row.get("parent_run_id"):
        parent = await _fetch_parent_run(row["parent_run_id"], user_id)
        if parent is not None:
            parent_snapshot = parent.get("config_snapshot") or {}
            diff_parent = {
                "parent_run_id": row["parent_run_id"],
                "parameters_changed": [
                    {"name": name,
                     "old": (parent_snapshot.get("parameters") or {}).get(name),
                     "new": (row.get("parameters") or {}).get(name)}
                    for name in sorted(set((parent_snapshot.get("parameters") or {}))
                                        | set(row.get("parameters") or {}))
                    if (parent_snapshot.get("parameters") or {}).get(name)
                    != (row.get("parameters") or {}).get(name)
                ],
                "steps_changed": list(parent_snapshot.get("steps") or [])
                != list(row.get("steps") or []),
            }
        else:
            diff_parent = {"parent_run_id": row["parent_run_id"], "unavailable": True,
                           "note": "父运行已不可恢复，不做差异比较"}
    history = row.get("history") or []
    diff_prev = None
    if len(history) >= 2:
        prev = history[-2]
        diff_prev = proposals_module.proposal_diff(
            {"version": prev.get("version"), "parameters": prev.get("parameters"),
             "steps": prev.get("steps"), "metric_policy": {"basis": prev.get("metric_basis")},
             "objective": "", "plan_hash": prev.get("plan_hash")},
            {"version": row["version"], "parameters": row["parameters"],
             "steps": row["steps"], "metric_policy": row["metric_policy"],
             "objective": row.get("objective", ""), "plan_hash": row["plan_hash"]},
        )
    return {"proposal": view, "diff_parent": diff_parent, "diff_previous": diff_prev}


@app.patch(
    "/api/v1/nexus/repro/proposals/{proposal_id}",
    dependencies=[Depends(require_api_key)],
)
async def repro_proposal_patch(
    proposal_id: str,
    body: ProposalPatch,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """NX-LB2：改提案（乐观锁；仅 draft；旧批准随 hash 失效）。

    未声明字段 → 422（extra=forbid）；版本冲突 → 409；已执行锁定 → 409。
    """
    from nexus import proposals as proposals_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    try:
        result = proposals_module.patch_proposal(
            sanitize_session_id(proposal_id), user_id=user_id,
            expected_version=body.expected_version,
            objective=body.objective, parameters=body.parameters,
            scope=body.scope,
        )
    except proposals_module.ProposalError as error:
        raise HTTPException(
            status_code=_proposal_error_status(error.code), detail=error.code
        ) from error
    result["proposal"] = proposals_module.public_proposal_view(result["proposal"])
    return result


@app.post(
    "/api/v1/nexus/repro/proposals/{proposal_id}/request-approval",
    dependencies=[Depends(require_api_key)],
)
async def repro_proposal_request_approval(
    proposal_id: str,
    body: ProposalRequestApproval,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """NX-LB2/LB4： pin 住版本+hash 生成/复用审批（不直接执行）。

    与工具路径共用同一核心（proposals.request_approval_for_proposal），
    不复制两套审批引擎；执行时重验版本+hash（提案被改则旧票拒绝）。
    """
    from nexus import proposals as proposals_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    try:
        result = proposals_module.request_approval_for_proposal(
            sanitize_session_id(proposal_id), user_id=user_id,
            expected_version=body.expected_version)
    except proposals_module.ProposalError as error:
        raise HTTPException(
            status_code=_proposal_error_status(error.code), detail=error.code
        ) from error
    return {"approval": result["approval"], "deduped": bool(result.get("deduped"))}


@app.get(
    "/api/v1/nexus/approvals",
    dependencies=[Depends(require_api_key)],
)
async def approvals_list(
    session_id: str = "",
    status: str = "pending",
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """NX-LB2：审批待办恢复（输入框浮窗用）：本人的待办＋提案摘要。

    status 仅支持 pending/approved/consumed/rejected/expired/all。
    """
    from nexus import approvals, proposals as proposals_module
    from nexus.tools.reproduction import REPRO_PRESETS, _public_approval

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    wanted = (status or "pending").strip().lower()
    if wanted not in ("pending", "approved", "consumed", "rejected", "expired", "all"):
        raise HTTPException(status_code=422, detail="APPROVAL_STATUS_UNSUPPORTED")
    rows = approvals.list_approvals(
        user_id=user_id,
        status=None if wanted == "all" else wanted,
        session_id=session_id.strip()[:128] or None,
    )
    items = []
    for row in rows:
        preset = REPRO_PRESETS.get(str(row.get("preset_id", "")).lower())
        item = _public_approval(row, preset) or {}
        if row.get("proposal_id"):
            proposal = proposals_module.get_proposal(row["proposal_id"])
            if proposal is not None and proposal["user_id"] == user_id:
                if (proposal.get("kind") == "autonomous_experiment"
                        or (not proposal.get("preset_id") and proposal.get("scope"))):
                    scope = proposal.get("scope") or {}
                    item["proposal"] = {
                        "proposal_id": proposal["proposal_id"],
                        "version": proposal["version"],
                        "kind": "autonomous_experiment",
                        "status": proposal["status"],
                        "objective": proposal.get("objective", ""),
                        "repo_url": (scope or {}).get("repo_url", ""),
                        "mode": (scope or {}).get("mode", ""),
                        "scope_hash": proposal.get("scope_hash", ""),
                    }
                else:
                    item["proposal"] = {
                        "proposal_id": proposal["proposal_id"],
                        "version": proposal["version"],
                        "status": proposal["status"],
                        "objective": proposal.get("objective", ""),
                        "parameters": proposal["parameters"],
                        "metric_basis": (proposal.get("metric_policy") or {}).get("basis", ""),
                        "plan_hash": proposal["plan_hash"],
                    }
            else:
                item["proposal"] = {"proposal_id": row["proposal_id"],
                                    "unavailable": True}
        items.append(item)
    return {"items": items}


class ExecutionModeBody(BaseModel):
    research_execution_mode: str = Field(min_length=1, max_length=16)


@app.put(
    "/api/v1/nexus/sessions/{session_id}/execution-mode",
    dependencies=[Depends(require_api_key)],
)
async def session_execution_mode_save(
    session_id: str,
    body: ExecutionModeBody,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """T2：保存用户明确选择的 Research 执行模式（Ask/Auto）。

    未知值 400；合法值落服务端会话偏好（刷新恢复由客户端显式发送，
    未传字段不偷升级）。
    """
    from nexus import execution_mode as execution_mode_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    session_id = sanitize_session_id(session_id)
    try:
        normalized = execution_mode_module.normalize_execution_mode(
            body.research_execution_mode, "research")
    except execution_mode_module.InvalidExecutionMode as error:
        raise HTTPException(
            status_code=400,
            detail=f"INVALID_RESEARCH_EXECUTION_MODE:{error.raw!r}",
        ) from error
    execution_mode_module.save_preference(user_id, session_id, normalized)
    return {"session_id": session_id,
            "research_execution_mode": normalized}


@app.get(
    "/api/v1/nexus/sessions/{session_id}/execution-mode",
    dependencies=[Depends(require_api_key)],
)
async def session_execution_mode_get(
    session_id: str,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    """T2：读取服务端会话偏好（无记录默认 Ask；纯读取，不触发执行）。"""
    from nexus import execution_mode as execution_mode_module

    user_id = sanitize_user_id(x_nexus_user_id) or ""
    session_id = sanitize_session_id(session_id)
    saved = execution_mode_module.get_preference(user_id, session_id)
    return {"session_id": session_id,
            "research_execution_mode": saved or "ask",
            "has_preference": saved is not None}
