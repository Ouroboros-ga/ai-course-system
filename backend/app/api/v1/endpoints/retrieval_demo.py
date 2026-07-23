"""Independent local-only Shadow-1 retrieval demo router.

The router is deliberately separate from ``chat.py`` and ``document.py``.
It executes the frozen research R2 provider only after a course-scope check;
R3 is not imported.  Disabled modes return a clear 503 and never modify or
invoke the V1 path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import admin_only
from app.platform.retrieval_demo.service import DemoService


router = APIRouter()


class DemoQueryRequest(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    v1_reference: str | None = Field(default=None, max_length=12000)


def get_demo_service(request: Request) -> DemoService:
    service = getattr(request.app.state, "retrieval_demo_service", None)
    if service is None:
        service = DemoService(
            configured_mode=settings.DEMO_RETRIEVAL_MODE,
            environment=settings.DEMO_RETRIEVAL_ENVIRONMENT,
        )
        request.app.state.retrieval_demo_service = service
    return service


def require_demo_visible(service: DemoService) -> None:
    state = service.mode_state()
    if not state.enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DEMO_SHADOW_DISABLED",
                "configured_mode": state.configured_mode,
                "effective_mode": state.effective_mode,
                "reason": state.reason,
            },
        )


@router.get("/status", summary="Shadow-1 demo status; no V1 behavior is changed")
async def demo_status(
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    return get_demo_service(request).status()


@router.get("/courses", summary="Course scopes available to the visible frozen demo")
async def demo_courses(
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    service = get_demo_service(request)
    require_demo_visible(service)
    return {"course_ids": list(service.active_provider.course_ids), "data_source": service.runtime_source}


@router.get("/courses/{course_id}/presets", summary="Public-fixture preset questions for a visible demo")
async def demo_presets(
    course_id: str,
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    service = get_demo_service(request)
    require_demo_visible(service)
    return {"course_id": course_id, "data_source": service.runtime_source, "presets": await run_in_threadpool(service.active_provider.presets, course_id)}


@router.get("/courses/{course_id}/graph", summary="Accepted deterministic graph snapshot for a visible demo")
async def demo_graph(
    course_id: str,
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    service = get_demo_service(request)
    require_demo_visible(service)
    return await run_in_threadpool(service.active_provider.graph_snapshot, course_id)


@router.post("/query", summary="Run isolated R2 retrieval and persist an independent demo run")
async def demo_query(
    body: DemoQueryRequest,
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    service = get_demo_service(request)
    require_demo_visible(service)
    return await run_in_threadpool(
        service.query,
        course_id=body.course_id,
        question=body.question,
        v1_reference=body.v1_reference,
    )


@router.post("/rollback", summary="One-click process-local rollback for the demonstration only")
async def demo_rollback(
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    state = get_demo_service(request).rollback_to_v1_only()
    return {
        "configured_mode": state.configured_mode,
        "effective_mode": state.effective_mode,
        "enabled": state.enabled,
        "reason": state.reason,
        "message": "Demo route is now disabled. V1 was never modified.",
    }


@router.post("/rollback-to-fixture", summary="Emergency rollback to the isolated legacy fixture provider")
async def demo_rollback_to_fixture(
    request: Request,
    _admin: Any = Depends(admin_only),
) -> dict[str, Any]:
    service = get_demo_service(request)
    require_demo_visible(service)
    service.rollback_to_fixture()
    return {
        "data_source": service.runtime_source,
        "message": "Sidecar path disabled for this demo process; legacy fixture provider is explicitly active.",
    }
