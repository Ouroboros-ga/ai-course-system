"""Nexus Runtime 服务入口：FastAPI + SSE。"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from pydantic import BaseModel, Field

from nexus import __version__
from nexus.agent import build_agent
from nexus.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nexus")

app = FastAPI(title="Nexus AI Runtime", version=__version__)

_agent: Any = None


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


def _config_for(session_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"nexus-session-{session_id}"}}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _summarize_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content[:600]
    try:
        return json.dumps(content, ensure_ascii=False)[:600]
    except (TypeError, ValueError):
        return str(content)[:600]


async def _agent_stream(message: str, session_id: str):
    agent = get_agent()
    inputs = {"messages": [{"role": "user", "content": message}]}
    config = _config_for(session_id)
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


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "llm_configured": bool(settings.deepseek_api_key),
        "searxng_configured": bool(settings.searxng_url),
        "ddgs_enabled": settings.ddgs_enabled,
        "repro_worker_configured": bool(settings.repro_worker_url),
    }


@app.post("/api/v1/nexus/chat/stream", dependencies=[Depends(require_api_key)])
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    get_agent()
    return StreamingResponse(
        _agent_stream(request.message, request.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/nexus/chat", dependencies=[Depends(require_api_key)])
async def chat(request: ChatRequest) -> dict[str, Any]:
    agent = get_agent()
    inputs = {"messages": [{"role": "user", "content": request.message}]}
    config = _config_for(request.session_id)
    tool_events: list[dict[str, Any]] = []
    async for mode, payload in agent.astream(inputs, config, stream_mode="updates"):
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
    return {
        "session_id": request.session_id,
        "message": final_message,
        "tool_events": tool_events,
    }
