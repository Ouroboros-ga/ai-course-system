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

# M1-B2：按（模式, 模型）索引的 agent 实例（同对共享同一 checkpointer）。
# 模型网关 P0：同一 thread 命名空间跨模型共享，切模型不断上下文。
_agents: dict[tuple[str, str], Any] = {}
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
            step = "saver_setup"
            cm = AsyncPostgresSaver.from_conn_string(dsn_with_schema(dsn, schema))
            saver = await cm.__aenter__()
            await saver.setup()
            _pg_ctx = cm
            _pg_saver = saver
            default_model = llm_default_model(settings)
            for mode in ("research", "general"):
                _agents[(mode, default_model)] = build_agent(
                    mode=mode, checkpointer=saver, model=default_model
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


def get_agent(mode: str = "general", model: str | None = None) -> Any:
    """取（模式, 模型）agent 实例；model 为 None 即默认模型。

    model 入参应已由 _require_model 校验；此处再做一次归一是纵深防御
    （normalize_model_name 对清单外 id 抛 InvalidNexusModel，绝不静默建实例）。
    """
    mode = normalize_mode(mode)
    settings = get_settings()
    model = normalize_model_name(model, llm_available_models(settings), llm_default_model(settings))
    key = (mode, model)
    agent = _agents.get(key)
    if agent is None:
        try:
            agent = build_agent(
                mode=mode,
                checkpointer=_pg_saver if _pg_saver is not None else _fallback_saver,
                model=model,
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
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


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


def _summarize_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content[:600]
    try:
        return json.dumps(content, ensure_ascii=False)[:600]
    except (TypeError, ValueError):
        return str(content)[:600]


# M1-B4（D4）：按工具从 JSON 结果中抽取结构化条目；条目边界截断，
# 不再对整个 JSON 做 600 字符腰斩（腰斩产物前端 JSON.parse 必失败）。
_ITEM_FIELD_BY_TOOL = {
    "web_search": "items",
    "search_arxiv_papers": "items",
    "plan_reproduction": "plan",
    "run_reproduction": "job",
    "write_artifact": "artifact",
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
    return payload


async def _agent_stream(
    message: str,
    session_id: str,
    user_id: str | None = None,
    mode: str = "general",
    course_id: int | None = None,
    approval_id: str | None = None,
    model: str | None = None,
    attachment_ids: list[str] | None = None,
):
    agent = get_agent(mode, model)
    inputs = {"messages": [{"role": "user", "content": message}]}
    config = _config_for(session_id, user_id)
    token_count = 0
    from nexus.request_scope import (
        reset_attachments,
        reset_execution_scope,
        reset_scope,
        set_attachments,
        set_execution_scope,
        set_scope,
    )

    scope_tokens = set_scope(user_id, course_id)
    exec_tokens = set_execution_scope(session_id, approval_id)
    attach_token = set_attachments(attachment_ids)
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
                        yield _sse("token", {"content": content})
            elif stream_mode == "updates":
                for _node, delta in (payload or {}).items():
                    messages = None
                    if isinstance(delta, dict):
                        messages = delta.get("messages")
                    if not messages:
                        continue
                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            for call in msg.tool_calls or []:
                                yield _sse("tool_call", {"name": call.get("name"), "args": call.get("args")})
                        elif isinstance(msg, ToolMessage):
                            yield _sse("tool_result", _tool_result_payload(msg))
    except asyncio.CancelledError:
        # M1-B6：客户端断开导致流被取消——如实中断，绝不补发假 done。
        raise
    except Exception as error:  # noqa: BLE001 - Agent 循环异常必须显式到流尾
        # M1-B3（D5）：done/error 互斥；错误码优先用工具/上游语义码。
        code = str(getattr(error, "code", "") or type(error).__name__)[:64]
        yield _sse("error", {"code": code, "message": str(error)[:300]})
        return
    finally:
        reset_scope(scope_tokens)
        reset_execution_scope(exec_tokens)
        reset_attachments(attach_token)
    yield _sse("done", {"session_id": session_id, "token_count": token_count})


def _tool_surface() -> dict[str, list[str]] | None:
    """已构建 agent 的执行器工具注册表（M0-B1 巡检口径，M1 起按模式上报）。

    模型网关 P0：键为 "mode@model"，只含已实际构建的实例。不同模型同模式
    的工具面应一致；出现分歧即回归信号（某模型实例构建走了不同分支）。
    """
    if not _agents:
        return None
    surfaces: dict[str, list[str]] = {}
    for (mode, model), agent in _agents.items():
        try:
            surfaces[f"{mode}@{model}"] = sorted(agent.nodes["tools"].bound.tools_by_name.keys())
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


@app.post("/api/v1/nexus/chat/stream", dependencies=[Depends(require_api_key)])
async def chat_stream(
    request: ChatRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> StreamingResponse:
    mode = _require_mode(request.mode)
    model = _require_model(request.model)
    get_agent(mode, model)
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    thread_id = thread_for(session_id, user_id)
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
    agent = get_agent(mode, model)
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    inputs = {"messages": [{"role": "user", "content": request.message}]}
    config = _config_for(session_id, user_id)
    tool_events: list[dict[str, Any]] = []
    from nexus.request_scope import (
        reset_attachments,
        reset_execution_scope,
        reset_scope,
        set_attachments,
        set_execution_scope,
        set_scope,
    )

    scope_tokens = set_scope(user_id, _context_course_id(request))
    exec_tokens = set_execution_scope(session_id, _sanitize_approval_id(request))
    attach_token = set_attachments(_sanitize_attachment_ids(request))
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
    finally:
        reset_scope(scope_tokens)
        reset_execution_scope(exec_tokens)
        reset_attachments(attach_token)
    state = await agent.aget_state(config)
    final_message = ""
    for msg in reversed(state.values.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            final_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
    await _touch_thread(
        thread_for(session_id, user_id), user_id, session_id, _title_from_message(request.message)
    )
    return {
        "session_id": session_id,
        "message": final_message,
        "tool_events": tool_events,
    }


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
    """单会话历史消息（C2/C3）：从 checkpoint 投影 user/assistant 文本。"""
    agent = get_agent()
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(session_id)
    config = _config_for(session_id, user_id)
    try:
        state = await agent.aget_state(config)
    except Exception as error:  # noqa: BLE001 - 无 checkpoint/读取失败都视为空历史
        logger.warning("session_messages aget_state failed: %s", error)
        state = None
    values = (state.values if state is not None else None) or {}
    return {
        "session_id": session_id,
        "messages": _serialize_history(list(values.get("messages") or [])),
    }


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


class ReproJobError(Exception):
    """作业获取/状态错误：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


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
    report = repro_report.build_report(job=job, preset=preset)
    markdown = repro_report.render_report_markdown(report)
    payload_json = repro_report.render_report_json(report)
    base_title = f"复现报告 · {report['preset_id']}".strip() or "复现报告"

    artifacts: list[dict[str, Any]] = []
    for artifact_type, title, content in (
        ("markdown", base_title, markdown),
        ("markdown", f"{base_title}（原始数据 JSON）", payload_json),
    ):
        written = await write_artifact_via_backend(
            artifact_type=artifact_type, title=title, content=content, user_id=user_id
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
    try:
        return await execute_approved_reproduction(
            approval_id=approval_id,
            user_id=user_id,
            session_id=session_id,
            preset_id=preset_id,
        )
    except approvals.ApprovalError as error:
        status_map = {
            "APPROVAL_NOT_FOUND": 404,
            "APPROVAL_FORBIDDEN": 403,
            "APPROVAL_SESSION_MISMATCH": 403,
            "APPROVAL_NOT_APPROVED": 409,
            "APPROVAL_EXPIRED": 409,
            "APPROVAL_PLAN_CHANGED": 409,
        }
        raise HTTPException(
            status_code=status_map.get(error.code, 409), detail=error.code
        ) from error
