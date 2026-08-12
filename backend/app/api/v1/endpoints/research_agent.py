"""Course-bound ResearchAgent API.

The current public slice exposes scholarly metadata search and an honest
capability manifest.  Unimplemented stages remain ``research_preview`` and
cannot return fabricated trend, writing, or reproduction results.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.platform.agents.runtime.base import AgentRunContext
from app.platform.agents.runtime.profile import AgentType
from app.services.course_access_service import require_course_permission

router = APIRouter()


class PaperSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    max_results: int = Field(default=8, ge=1, le=20)
    cursor: str | None = Field(default=None, max_length=20)


ResearchAction = Literal[
    "auto",
    "literature_search",
    "todo_create",
    "todo_update",
    "todo_list",
    "notepad_write",
    "notepad_read",
    "memory_store",
    "memory_search",
    "scope_create",
    "scope_switch",
    "scope_interrupt",
    "scope_resume",
    "scope_complete",
]


class ResearchHarnessRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2_000)
    action: ResearchAction = "auto"
    workspace_id: str | None = Field(default=None, pattern=r"^rws_[a-f0-9]{32}$")
    scope_id: str | None = Field(default=None, pattern=r"^rscope_[a-f0-9]{32}$")
    payload: dict[str, Any] = Field(default_factory=dict)
    context_budget_tokens: int = Field(default=4_000, ge=256, le=16_000)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_harness_payload(value)
        return value


@router.get("/courses/{course_id}/capabilities")
async def get_research_capabilities(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    context = require_course_permission(session, current_user, course_id, "course.view")
    can_search = context.allows("course.question.ask")
    can_reproduce = context.allows("experiment.run") and bool(context.capabilities.get("coding_sandbox"))
    return unified_response(
        code=200,
        message="获取研究智能体能力成功",
        data={
            "course_id": course_id,
            "maturity": "research_preview",
            "stages": [
                {
                    "key": "research_harness",
                    "label": "科研编排",
                    "status": "available" if can_search else "permission_required",
                },
                {"key": "literature_search", "label": "文献检索", "status": "available" if can_search else "permission_required"},
                {"key": "trend_analysis", "label": "趋势分析", "status": "research_preview"},
                {"key": "evidence_synthesis", "label": "证据综合", "status": "research_preview"},
                {"key": "writing_assist", "label": "学术写作", "status": "research_preview"},
                {
                    "key": "code_reproduction",
                    "label": "代码复现",
                    "status": "research_preview" if can_reproduce else "capability_required",
                },
            ],
            "providers": [
                {"key": "arxiv", "label": "arXiv", "status": "available", "requires_api_key": False},
                {
                    "key": "semantic_scholar",
                    "label": "Semantic Scholar",
                    "status": "planned",
                    "requires_api_key": True,
                },
            ],
            "source_policy": {
                "is_supplementary": True,
                "cannot_modify_mastery": True,
                "cannot_modify_recommendation": True,
                "cannot_modify_graph": True,
            },
        },
    )


@router.post("/courses/{course_id}/search")
async def search_papers(
    course_id: int,
    payload: PaperSearchRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.question.ask")
    platform = getattr(request.app.state, "agent_platform", None)
    if platform is None or not platform.is_registered(AgentType.RESEARCH):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="研究智能体暂不可用",
        )

    user_id = str(current_user["user_id"])
    result = await platform.respond(AgentRunContext(
        agent_type="research",
        scope=(str(course_id), user_id),
        course_id=str(course_id),
        student_id=user_id,
        user_message=payload.query,
        extras={
            "actor_user_id": user_id,
            "action": "literature_search",
            "max_results": payload.max_results,
            "cursor": payload.cursor,
        },
    ))
    search_result: dict[str, Any] = dict(result.get("search_result") or {})
    data = {
        "trace_id": result.get("trace_id"),
        "status": result.get("status", "unavailable"),
        "message": result.get("final_answer"),
        "query": result.get("query", payload.query),
        "provider": search_result.get("provider", "arxiv"),
        "retrieved_at": search_result.get("retrieved_at"),
        "items": result.get("papers", []),
        "total": len(result.get("papers", [])),
        "next_cursor": search_result.get("next_cursor"),
        "cache_hit": bool(search_result.get("cache_hit")),
        "warnings": result.get("warnings", []),
        "degraded_services": result.get("degraded_services", []),
        "source_policy": {
            "is_supplementary": True,
            "cannot_modify_mastery": True,
            "cannot_modify_recommendation": True,
            "cannot_modify_graph": True,
        },
    }
    return unified_response(code=200, message="研究检索完成", data=data)


@router.get("/courses/{course_id}/workspace")
async def get_research_workspace(
    course_id: int,
    request: Request,
    workspace_id: str | None = None,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return only the current actor's course-bound research workspace."""
    require_course_permission(session, current_user, course_id, "course.view")
    provider = getattr(request.app.state, "research_workspace_provider", None)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="科研工作区暂不可用")
    actor_user_id = str(current_user["user_id"])
    try:
        if workspace_id:
            snapshot = await provider.get_workspace_snapshot(
                workspace_id=workspace_id,
                course_id=course_id,
                actor_user_id=actor_user_id,
            )
        else:
            workspace = await provider.get_or_create_workspace(
                course_id=course_id,
                actor_user_id=actor_user_id,
                title="科研工作台",
            )
            snapshot = await provider.get_workspace_snapshot(
                workspace_id=workspace["workspace_id"],
                course_id=course_id,
                actor_user_id=actor_user_id,
            )
    except Exception as error:  # avoid revealing workspace ownership
        if str(error) == "RESEARCH_WORKSPACE_SCOPE_DENIED":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="科研工作区不存在") from error
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="科研工作区读取失败") from error
    return unified_response(code=200, message="获取科研工作区成功", data=dict(snapshot))


@router.post("/courses/{course_id}/workspace/runs")
async def run_research_harness(
    course_id: int,
    payload: ResearchHarnessRequest,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Execute one allowlisted Harness action through the LangGraph workflow."""
    require_course_permission(session, current_user, course_id, "course.question.ask")
    platform = getattr(request.app.state, "agent_platform", None)
    if platform is None or not platform.is_registered(AgentType.RESEARCH):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="研究智能体暂不可用")

    user_id = str(current_user["user_id"])
    result = await platform.respond(AgentRunContext(
        agent_type="research",
        scope=(str(course_id), user_id),
        course_id=str(course_id),
        student_id=user_id,
        user_message=payload.message,
        extras={
            "actor_user_id": user_id,
            "action": payload.action,
            "payload": payload.payload,
            "workspace_id": payload.workspace_id,
            "scope_id": payload.scope_id,
            "context_budget_tokens": payload.context_budget_tokens,
        },
    ))
    data = {
        "run_id": result.get("run_id"),
        "trace_id": result.get("trace_id"),
        "status": result.get("status", "unavailable"),
        "message": result.get("final_answer"),
        "graph_route": result.get("graph_route"),
        "selected_tools": result.get("selected_tools", []),
        "denied_tools": result.get("denied_tools", []),
        "tool_selection_reason": result.get("tool_selection_reason"),
        "tool_result": result.get("tool_result"),
        "tool_error_code": result.get("tool_error_code"),
        "prompt": {
            "version": result.get("prompt_version"),
            "hash": result.get("prompt_hash"),
        },
        "context": _safe_context_meta(result.get("context_meta")),
        "workspace": result.get("workspace_snapshot"),
        "papers": result.get("papers", []),
        "search": _safe_search_result(result.get("search_result")),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
        "degraded_services": result.get("degraded_services", []),
        "source_policy": {
            "is_supplementary": True,
            "cannot_modify_mastery": True,
            "cannot_modify_recommendation": True,
            "cannot_modify_graph": True,
        },
    }
    return unified_response(code=200, message="科研 Harness 执行完成", data=data)


def _validate_harness_payload(value: Any, *, depth: int = 0) -> None:
    if depth > 4:
        raise ValueError("payload nesting is too deep")
    if isinstance(value, Mapping):
        if len(value) > 32:
            raise ValueError("payload has too many fields")
        for key, item in value.items():
            normalized_key = str(key)
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", normalized_key):
                raise ValueError("payload key is invalid")
            if any(marker in normalized_key.casefold() for marker in ("api_key", "secret", "password", "token")):
                raise ValueError("sensitive fields are not accepted")
            _validate_harness_payload(item, depth=depth + 1)
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 48_000:
            raise ValueError("payload is too large")
        return
    if isinstance(value, list):
        if len(value) > 64:
            raise ValueError("payload list is too large")
        for item in value:
            _validate_harness_payload(item, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str) and len(value) <= 40_000:
        return
    raise ValueError("payload value is invalid")


def _safe_context_meta(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "selected_item_ids", "dropped_item_ids", "estimated_tokens",
        "budget_tokens", "compressed", "compression_method",
    }
    return {key: value[key] for key in allowed if key in value}


def _safe_search_result(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = {"status", "provider", "retrieved_at", "total", "next_cursor", "cache_hit"}
    return {key: value[key] for key in allowed if key in value}


__all__ = ["router"]
