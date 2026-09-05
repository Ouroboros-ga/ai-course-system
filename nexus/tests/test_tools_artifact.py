"""M3：write_artifact 工具契约（全 mock，不触真实 Backend/存储）。

fail-closed 是核心：未配置/不可达/非 200 时必须返回 ARTIFACT_UNAVAILABLE
并带"不得声称文件已生成"语义；成功时透传 artifact_id 与下载路径。
"""

import httpx
import pytest

import nexus.tools.artifact as artifact_module
from nexus import request_scope
from nexus.config import get_settings
from nexus.tools.artifact import write_artifact

TOKEN = "test-internal-token"
URL = "http://127.0.0.1:8000"


def _ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", URL)
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", TOKEN)
    get_settings.cache_clear()


def _not_ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_URL", raising=False)
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_TOKEN", raising=False)
    get_settings.cache_clear()


async def test_write_artifact_unconfigured_fails_closed(monkeypatch: pytest.MonkeyPatch):
    _not_ready(monkeypatch)
    result = await write_artifact.ainvoke(
        {"artifact_type": "markdown", "title": "报告", "content": "# 报告"}
    )
    assert result["status"] == "unavailable"
    assert result["code"] == "ARTIFACT_UNAVAILABLE"
    assert "不得声称文件已生成" in result["detail"]


async def test_write_artifact_success(monkeypatch: pytest.MonkeyPatch):
    _ready(monkeypatch)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["user"] = request.headers.get("X-Nexus-User-Id")
        seen["body"] = request.read()
        return httpx.Response(200, json={
            "code": 200,
            "data": {
                "artifact_id": "abc123def456",
                "artifact_type": "markdown",
                "title": "复现报告",
                "size_bytes": 20,
            },
        })

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(artifact_module.write_artifact_via_backend.__globals__["httpx"], "AsyncClient", factory)
    request_scope.set_scope("42", None)
    try:
        result = await write_artifact.ainvoke(
            {"artifact_type": "markdown", "title": "复现报告", "content": "# 复现报告"}
        )
    finally:
        get_settings.cache_clear()
    assert result["status"] == "success"
    artifact = result["artifact"]
    assert artifact["artifact_id"] == "abc123def456"
    assert artifact["download_path"] == "/api/v1/nexus/artifacts/abc123def456/download"
    assert seen["path"] == "/api/v1/nexus-internal/artifacts"
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["user"] == "42"
    assert b"markdown" in seen["body"]


async def test_write_artifact_rejected_maps_unavailable(monkeypatch: pytest.MonkeyPatch):
    _ready(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "ARTIFACT_TYPE_UNSUPPORTED"})

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(artifact_module.write_artifact_via_backend.__globals__["httpx"], "AsyncClient", factory)
    try:
        result = await write_artifact.ainvoke(
            {"artifact_type": "docx", "title": "t", "content": "x"}
        )
    finally:
        get_settings.cache_clear()
    assert result["status"] == "unavailable"
    assert "ARTIFACT_TYPE_UNSUPPORTED" in result["detail"]


async def test_write_artifact_unreachable_fails_closed(monkeypatch: pytest.MonkeyPatch):
    _ready(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(artifact_module.write_artifact_via_backend.__globals__["httpx"], "AsyncClient", factory)
    try:
        result = await write_artifact.ainvoke(
            {"artifact_type": "markdown", "title": "t", "content": "x"}
        )
    finally:
        get_settings.cache_clear()
    assert result["code"] == "ARTIFACT_UNAVAILABLE"


def test_tool_registered_in_surface():
    from nexus.tools import NEXUS_TOOLS

    assert "write_artifact" in {t.name for t in NEXUS_TOOLS}
