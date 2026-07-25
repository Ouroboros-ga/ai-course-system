"""Tests for the error monitoring middleware (批次0上线底座)."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.error_monitoring import (
    monitor,
    CATEGORY_CROSS_COURSE_DENIAL,
    CATEGORY_SHADOW_DISABLED_503,
    CATEGORY_SERVER_ERROR_5XX,
    CATEGORY_AUTHORIZATION_403,
    CATEGORY_CLIENT_ERROR_4XX,
    ErrorMonitoringMiddleware,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ErrorMonitoringMiddleware)

    @app.get("/ok")
    async def ok():
        return {"code": 200, "message": "ok", "data": None}

    @app.get("/cross-course")
    async def cross_course():
        raise HTTPException(403, "课程权限不足")

    @app.get("/other-403")
    async def other_403():
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "禁止访问"})

    @app.get("/shadow")
    async def shadow():
        raise HTTPException(503, detail={"code": "SHADOW_FEATURE_DISABLED", "message": "shadow off"})

    @app.get("/server-error")
    async def server_error():
        raise HTTPException(500, detail="内部错误")

    @app.get("/client-error")
    async def client_error():
        raise HTTPException(404, "not found")

    return app


def test_ok_response_not_counted():
    monitor.reset()
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/ok")
    assert r.status_code == 200
    assert monitor.snapshot() == {}


def test_cross_course_denial_counted():
    monitor.reset()
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/cross-course")
    assert r.status_code == 403
    snap = monitor.snapshot()
    assert snap.get(CATEGORY_CROSS_COURSE_DENIAL) == 1


def test_other_403_counted():
    monitor.reset()
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/other-403")
    assert r.status_code == 403
    snap = monitor.snapshot()
    assert snap.get(CATEGORY_AUTHORIZATION_403) == 1


def test_shadow_disabled_503_counted():
    monitor.reset()
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/shadow")
    assert r.status_code == 503
    snap = monitor.snapshot()
    assert snap.get(CATEGORY_SHADOW_DISABLED_503) == 1


def test_server_error_5xx_counted():
    monitor.reset()
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/server-error")
    assert r.status_code == 500
    snap = monitor.snapshot()
    assert snap.get(CATEGORY_SERVER_ERROR_5XX) == 1


def test_client_error_4xx_counted():
    monitor.reset()
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/client-error")
    assert r.status_code == 404
    snap = monitor.snapshot()
    assert snap.get(CATEGORY_CLIENT_ERROR_4XX) == 1


def test_monitor_snapshot_endpoint_exposed():
    """The /api/v1/health/error-monitor route should be registered in main app."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/v1/health/error-monitor")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    assert isinstance(body["data"], dict)
