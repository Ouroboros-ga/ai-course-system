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
from pydantic import BaseModel, Field

from nexus import __version__
from nexus.agent import build_agent
from nexus.config import get_settings
from nexus.persistence import sanitize_session_id, sanitize_user_id, thread_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nexus")

_agent: Any = None
_pg_saver: Any = None
_pg_ctx: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001, ARG001
    """P1-C lifespan：DSN 配置时启用 AsyncPostgresSaver，否则保持 InMemory 降级。

    本地 DSN 为空 → 不连 PG、不建表，零外部依赖。服务器 DSN 配置 → 建独立
    schema + nexus_threads 表 + saver.setup()，重启后同 thread 可续聊。
    任何 PG 故障都 fail-open 回 InMemory 语义（对话可用但重启即清），绝不 500。
    """
    global _agent, _pg_saver, _pg_ctx
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
            _agent = build_agent(checkpointer=saver)
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


app = FastAPI(title="Nexus AI Runtime", version=__version__, lifespan=lifespan)


def get_agent() -> Any:
    global _agent
    if _agent is None:
        try:
            _agent = build_agent()
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    return _agent


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    api_key = get_settings().api_key
    if api_key and authorization != f"Bearer {api_key}":
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(default="default", max_length=128)


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


async def _agent_stream(message: str, session_id: str, user_id: str | None = None):
    agent = get_agent()
    inputs = {"messages": [{"role": "user", "content": message}]}
    config = _config_for(session_id, user_id)
    token_count = 0
    async for mode, payload in agent.astream(inputs, config, stream_mode=["messages", "updates"]):
        if mode == "messages":
            chunk, _meta = payload
            if isinstance(chunk, AIMessageChunk):
                content = chunk.content
                if isinstance(content, str) and content:
                    token_count += len(content)
                    yield _sse("token", {"content": content})
        elif mode == "updates":
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
                        yield _sse(
                            "tool_result",
                            {
                                "name": msg.name or "",
                                "status": msg.status or "success",
                                "content": _summarize_tool_content(msg.content),
                            },
                        )
    yield _sse("done", {"session_id": session_id, "token_count": token_count})


def _tool_surface() -> list[str] | None:
    """已构建 agent 的执行器工具注册表（M0-B1 巡检口径）。

    预期恰为 read_file + 四个产品工具；出现 write_file/execute/task 等即
    表示工具面收敛失效（回归信号）。未构建 agent 时返回 null。
    """
    if _agent is None:
        return None
    try:
        return sorted(_agent.nodes["tools"].bound.tools_by_name.keys())
    except AttributeError:
        return None


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    dsn = settings.postgres_dsn.strip()
    if _agent is None and settings.deepseek_api_key:
        # 部署后无需先发起对话即可核对工具面；构建失败不阻断健康检查。
        try:
            get_agent()
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
    get_agent()
    user_id = sanitize_user_id(x_nexus_user_id)
    session_id = sanitize_session_id(request.session_id)
    thread_id = thread_for(session_id, user_id)
    await _touch_thread(thread_id, user_id, session_id, _title_from_message(request.message))
    return StreamingResponse(
        _agent_stream(request.message, session_id, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/nexus/chat", dependencies=[Depends(require_api_key)])
async def chat(
    request: ChatRequest,
    x_nexus_user_id: str | None = Header(default=None, alias="X-Nexus-User-Id"),
) -> dict[str, Any]:
    agent = get_agent()
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
