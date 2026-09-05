"""Nexus Runtime 服务入口：FastAPI + SSE。"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from nexus import __version__
from nexus.agent import build_agent, normalize_mode
from nexus.config import get_settings
from nexus.persistence import sanitize_session_id, sanitize_user_id, thread_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nexus")

# M1-B2：按模式索引的 agent 实例（general/research 共享同一 checkpointer）。
_agents: dict[str, Any] = {}
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
            step = "saver_setup"
            cm = AsyncPostgresSaver.from_conn_string(dsn_with_schema(dsn, schema))
            saver = await cm.__aenter__()
            await saver.setup()
            _pg_ctx = cm
            _pg_saver = saver
            for mode in ("research", "general"):
                _agents[mode] = build_agent(mode=mode, checkpointer=saver)
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


def get_agent(mode: str = "research") -> Any:
    mode = normalize_mode(mode)
    agent = _agents.get(mode)
    if agent is None:
        try:
            agent = build_agent(
                mode=mode,
                checkpointer=_pg_saver if _pg_saver is not None else _fallback_saver,
            )
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        _agents[mode] = agent
    return agent


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    api_key = get_settings().api_key
    if api_key and authorization != f"Bearer {api_key}":
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(default="default", max_length=128)
    # M1-B1（D2）：mode 与 context 不再被 pydantic 静默丢弃。
    # mode 白名单归一（agent.normalize_mode）；context 形状 M2 才消费（course_id）。
    mode: str | None = Field(default=None, max_length=32)
    context: dict[str, Any] | None = Field(default=None)


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
    if field == "plan" and isinstance(raw, dict):
        raw = [raw]
    if field == "job" and isinstance(raw, dict):
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
    message: str, session_id: str, user_id: str | None = None, mode: str = "research"
):
    agent = get_agent(mode)
    inputs = {"messages": [{"role": "user", "content": message}]}
    config = _config_for(session_id, user_id)
    token_count = 0
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
    yield _sse("done", {"session_id": session_id, "token_count": token_count})


def _tool_surface() -> dict[str, list[str]] | None:
    """已构建 agent 的执行器工具注册表（M0-B1 巡检口径，M1 起按模式上报）。

    General 应为 read_file + web_search；Research 为 read_file + 四产品工具。
    出现 write_file/execute/task 等即表示工具面收敛失效（回归信号）。
    未构建任何 agent 时返回 null。
    """
    if not _agents:
        return None
    surfaces: dict[str, list[str]] = {}
    for mode, agent in _agents.items():
        try:
            surfaces[mode] = sorted(agent.nodes["tools"].bound.tools_by_name.keys())
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
    }


@app.post("/api/v1/nexus/chat/stream", dependencies=[Depends(require_api_key)])
async def chat_stream(
    request: ChatRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> StreamingResponse:
    mode = normalize_mode(request.mode)
    get_agent(mode)
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    thread_id = thread_for(session_id, user_id)
    await _touch_thread(thread_id, user_id, session_id, _title_from_message(request.message))
    return StreamingResponse(
        _agent_stream(request.message, session_id, user_id, mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/nexus/chat", dependencies=[Depends(require_api_key)])
async def chat(
    request: ChatRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    mode = normalize_mode(request.mode)
    agent = get_agent(mode)
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    inputs = {"messages": [{"role": "user", "content": request.message}]}
    config = _config_for(session_id, user_id)
    tool_events: list[dict[str, Any]] = []
    # stream_mode 必须是列表形式：单字符串模式下 astream 产出单值，
    # 列表模式才产出 (mode, payload) 元组（与 _agent_stream 一致）。
    async for mode, payload in agent.astream(inputs, config, stream_mode=["updates"]):
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
