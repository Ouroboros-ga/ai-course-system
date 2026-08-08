"""Course-bound ResearchAgent API.

The current public slice exposes scholarly metadata search and an honest
capability manifest.  Unimplemented stages remain ``research_preview`` and
cannot return fabricated trend, writing, or reproduction results.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
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


__all__ = ["router"]
