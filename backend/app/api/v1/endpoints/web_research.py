"""G7 WebResearchTool 受控研究 API

教师可以关闭课程级 WebResearch。
每条外部参考带来源、时间和用途。
不可用、无引用或越权来源时拒绝使用。
"""
from __future__ import annotations

from app.core.time_utils import utcnow_naive
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.web_research_model import (
    WebResearchConfig,
    WebResearchResult,
    ExternalReference,
    DEFAULT_ALLOWED_DOMAINS,
)
from app.services.course_access_service import require_course_permission
from app.services.web_research_service import (
    get_or_create_config,
    execute_research,
    serialize_result,
    serialize_config,
    sanitize_query,
    normalize_allowed_domains,
)

router = APIRouter(tags=["G7 WebResearchTool"])


class ConfigUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    allowed_domains: Optional[list[str]] = Field(default=None, max_length=100)
    search_budget_per_query: Optional[int] = Field(default=None, ge=1, le=100)
    max_results_per_search: Optional[int] = Field(default=None, ge=1, le=20)
    cache_ttl_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)


@router.get("/course/{course_id}/config")
async def get_config(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程 WebResearch 配置"""
    require_course_permission(session, current_user, course_id, "course.view")
    config = get_or_create_config(session, course_id)
    return unified_response(code=200, message="获取配置成功", data=serialize_config(config))


@router.put("/course/{course_id}/config")
async def update_config(
    course_id: int,
    payload: ConfigUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新课程 WebResearch 配置

    需要 agent.policy.configure 权限。
    教师可以关闭课程级 WebResearch。
    """
    require_course_permission(session, current_user, course_id, "agent.policy.configure")
    config = get_or_create_config(session, course_id)

    if payload.enabled is not None:
        config.enabled = payload.enabled
    if payload.allowed_domains is not None:
        try:
            config.allowed_domains = normalize_allowed_domains(payload.allowed_domains)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.search_budget_per_query is not None:
        config.search_budget_per_query = payload.search_budget_per_query
    if payload.max_results_per_search is not None:
        config.max_results_per_search = payload.max_results_per_search
    if payload.cache_ttl_minutes is not None:
        config.cache_ttl_minutes = payload.cache_ttl_minutes

    config.updated_at = utcnow_naive()
    session.add(config)
    session.commit()
    session.refresh(config)

    return unified_response(code=200, message="配置已更新", data=serialize_config(config))


@router.post("/course/{course_id}/search")
async def search(
    course_id: int,
    payload: SearchRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """执行受控外部研究

    每条外部参考带来源、时间和用途。
    不可用、无引用或越权来源时拒绝使用。
    外部资料只标记为"补充参考"，与课程 Evidence 分开。
    """
    require_course_permission(session, current_user, course_id, "course.question.ask")

    result = execute_research(
        session, course_id, payload.query,
        user_id=int(current_user["user_id"]),
    )

    return unified_response(
        code=200,
        message="研究完成" if result.status.value == "success" else f"研究状态: {result.status.value}",
        data=serialize_result(result),
    )


@router.get("/course/{course_id}/references")
async def list_references(
    course_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的外部参考"""
    require_course_permission(session, current_user, course_id, "course.view")

    refs = session.exec(
        select(ExternalReference).where(
            ExternalReference.course_id == course_id,
        ).order_by(ExternalReference.created_at.desc()).limit(limit)
    ).all()

    return unified_response(
        code=200,
        message="获取外部参考成功",
        data={
            "items": [_serialize_ref(r) for r in refs],
            "total": len(refs),
        },
    )


def _serialize_ref(ref: ExternalReference) -> dict[str, Any]:
    return {
        "id": ref.id,
        "course_id": ref.course_id,
        "source_domain": ref.source_domain,
        "source_url": ref.source_url,
        "title": ref.title,
        "snippet": ref.snippet,
        "retrieved_at": ref.retrieved_at.isoformat() if ref.retrieved_at else None,
        "purpose": ref.purpose,
        "is_supplementary": ref.is_supplementary,
        "cannot_modify_mastery": ref.cannot_modify_mastery,
        "cannot_modify_recommendation": ref.cannot_modify_recommendation,
        "cannot_modify_graph": ref.cannot_modify_graph,
        "created_at": ref.created_at.isoformat() if ref.created_at else None,
    }
