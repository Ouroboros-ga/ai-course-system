"""Nexus AI Runtime 反代契约（CodeNexus 转型 S1 双轨期）。

本套测试锁定两件事：
1. 反代是**纯透传**且 **fail-closed**：Runtime 未配置/不可达/超时/自身报错时，
   一律返回明确错误码，绝不返回一个看起来正常的空回答（AGENTS.md 禁止静默成功）。
2. 旧 ``/research-agent`` 与 ``/web-research`` 只被**标注**为废弃，行为不变——
   S1 双轨期必须能随时回退到旧链路演示。

Runtime 本身跑在独立 Python 环境（``nexus/``），这里不启动它：用
``httpx.MockTransport`` 拦在出站边界上，与 ``test_research_agent.py`` 的 arXiv
provider 测试同一手法。
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.api.v1.endpoints import nexus_proxy

RUNTIME_URL = "http://127.0.0.1:8300"
SERVICE_TOKEN = "test-nexus-service-token"

RUNTIME_HEALTH = {
    "status": "ok",
    "version": "0.1.0",
    "llm_configured": True,
    "searxng_configured": True,
    "ddgs_enabled": True,
    "repro_worker_configured": False,
}

SSE_CHUNKS = [
    b'event: tool_call\ndata: {"name": "web_search", "args": {"query": "transformer"}}\n\n',
    b'event: tool_result\ndata: {"name": "web_search", "status": "success"}\n\n',
    b'event: token\ndata: {"content": "Transformer"}\n\n',
    b'event: done\ndata: {"session_id": "s1", "token_count": 11}\n\n',
]


@contextmanager
def mock_runtime(handler):
    """把反代的出站 httpx 客户端接到 MockTransport 上。

    生产代码里不留测试钩子：这里直接替换 ``nexus_proxy`` 模块引用到的
    ``httpx.AsyncClient``，让它带上 mock transport。
    """
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    with patch.object(nexus_proxy.httpx, "AsyncClient", factory):
        yield


@pytest.fixture
def runtime_configured(monkeypatch):
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_URL", RUNTIME_URL)
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_API_KEY", SERVICE_TOKEN)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 透传
# ---------------------------------------------------------------------------


def test_health_proxies_runtime_payload_and_identity_without_leaking_user_jwt(
    client, student_token, student_user, runtime_configured
):
    seen: dict[str, httpx.Request] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=RUNTIME_HEALTH)

    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/health", headers=_auth(student_token))

    assert response.status_code == 200
    assert response.json() == RUNTIME_HEALTH

    upstream = seen["request"]
    assert upstream.url.path == "/health"
    # 后端到 Runtime 用内部服务令牌，用户 JWT 不外泄。
    assert upstream.headers["Authorization"] == f"Bearer {SERVICE_TOKEN}"
    assert student_token not in upstream.headers["Authorization"]
    # 用户身份以专用头透传，供 Runtime 侧审计与后续权限位使用。
    assert upstream.headers["X-Nexus-User-Id"] == str(student_user.id)
    assert upstream.headers["X-Nexus-User-Role"] == student_user.role.value


def test_chat_proxies_request_body_to_runtime_chat_route(
    client, student_token, runtime_configured
):
    seen: dict[str, httpx.Request] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={"session_id": "s1", "message": "已完成检索", "tool_events": []},
        )

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "搜索 Transformer 最新进展", "session_id": "s1"},
            headers=_auth(student_token),
        )

    assert response.status_code == 200
    assert response.json()["message"] == "已完成检索"
    assert seen["request"].url.path == "/api/v1/nexus/chat"


def test_chat_stream_relays_upstream_sse_events(client, student_token, runtime_configured):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/nexus/chat/stream"
        assert request.headers["Accept"] == "text/event-stream"

        # 传异步生成器而非 bytes：``httpx.Response(content=bytes)`` 会把流标记为
        # 已消费，无法再 ``aiter_raw()``；真实上游给的是未消费的流，用生成器才
        # 真正验证逐块中继。
        async def upstream_chunks():
            for chunk in SSE_CHUNKS:
                yield chunk

        return httpx.Response(
            200,
            content=upstream_chunks(),
            headers={"content-type": "text/event-stream"},
        )

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat/stream",
            json={"message": "搜索 Transformer 最新进展", "session_id": "s1"},
            headers=_auth(student_token),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # 反代必须关闭上游缓冲，否则 SSE 会被攒成一整块再下发。
    assert response.headers["X-Accel-Buffering"] == "no"
    body = response.content
    assert b"event: tool_call" in body
    assert b"event: tool_result" in body
    assert b"event: token" in body
    assert body.endswith(b'event: done\ndata: {"session_id": "s1", "token_count": 11}\n\n')


# ---------------------------------------------------------------------------
# fail-closed：不伪造回答
# ---------------------------------------------------------------------------


def test_health_fails_closed_when_runtime_url_not_configured(
    client, student_token, monkeypatch
):
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_URL", "")

    response = client.get("/api/v1/nexus/health", headers=_auth(student_token))

    assert response.status_code == 503
    assert response.json()["data"]["error_code"] == nexus_proxy.ERROR_NOT_CONFIGURED


def test_chat_fails_closed_when_runtime_unreachable(
    client, student_token, runtime_configured
):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "帮我规划 nanoGPT 复现"},
            headers=_auth(student_token),
        )

    assert response.status_code == 503
    payload = response.json()
    assert payload["data"]["error_code"] == nexus_proxy.ERROR_UNAVAILABLE
    # 关键：不得出现任何看起来像正常回答的字段。
    assert "message" not in payload["data"]


def test_chat_reports_timeout_instead_of_fabricating_answer(
    client, student_token, runtime_configured
):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timeout", request=request)

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "执行 nanoGPT 复现"},
            headers=_auth(student_token),
        )

    assert response.status_code == 504
    assert response.json()["data"]["error_code"] == nexus_proxy.ERROR_TIMEOUT


def test_chat_passes_through_runtime_own_error_code(
    client, student_token, runtime_configured
):
    """Runtime 自己 fail-closed（如 LLM 未配置）时，错误码必须原样到达前端。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "LLM_NOT_CONFIGURED"})

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好"},
            headers=_auth(student_token),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "LLM_NOT_CONFIGURED"


def test_chat_stream_surfaces_upstream_failure_as_json_not_empty_stream(
    client, student_token, runtime_configured
):
    """建流阶段上游就失败时，返回可判读的 JSON 错误，而不是一个空 SSE 流。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "LLM_NOT_CONFIGURED"})

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat/stream",
            json={"message": "你好"},
            headers=_auth(student_token),
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "LLM_NOT_CONFIGURED"


def test_chat_reports_non_json_upstream_response(
    client, student_token, runtime_configured
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好"},
            headers=_auth(student_token),
        )

    assert response.status_code == 502
    assert response.json()["data"]["error_code"] == nexus_proxy.ERROR_UNAVAILABLE


# ---------------------------------------------------------------------------
# 鉴权与入参
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/nexus/health"),
        ("post", "/api/v1/nexus/chat"),
        ("post", "/api/v1/nexus/chat/stream"),
    ],
)
def test_nexus_endpoints_require_authentication(client, runtime_configured, method, path):
    call = getattr(client, method)
    response = call(path, json={"message": "你好"}) if method == "post" else call(path)

    assert response.status_code == 401


def test_chat_rejects_empty_message_before_reaching_runtime(
    client, student_token, runtime_configured
):
    called = {"upstream": False}

    async def handler(request: httpx.Request) -> httpx.Response:
        called["upstream"] = True
        return httpx.Response(200, json={})

    with mock_runtime(handler):
        response = client.post(
            "/api/v1/nexus/chat", json={"message": ""}, headers=_auth(student_token)
        )

    assert response.status_code == 422
    assert called["upstream"] is False


# ---------------------------------------------------------------------------
# S1 双轨期：旧接口只被标注，行为不变
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/research-agent/courses/1/capabilities",
        "/api/v1/web-research/policy",
    ],
)
def test_legacy_research_responses_carry_deprecation_headers(client, student_token, path):
    response = client.get(path, headers=_auth(student_token))

    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/v1/nexus/chat>; rel="successor-version"'
    assert response.headers["X-Deprecation-Phase"] == "S1-dual-track"
    # S1 只标注不改行为：不得是 410（那是 S2 的动作）。
    assert response.status_code != 410


def test_deprecation_marking_does_not_leak_to_nexus_routes(
    client, student_token, runtime_configured
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RUNTIME_HEALTH)

    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/health", headers=_auth(student_token))

    assert "Deprecation" not in response.headers


def test_sunset_header_is_absent_until_a_date_is_configured(client, student_token):
    """转型按里程碑推进；未配置日期时不得编造 Sunset。"""
    response = client.get(
        "/api/v1/research-agent/courses/1/capabilities", headers=_auth(student_token)
    )

    assert response.headers["Deprecation"] == "true"
    assert "Sunset" not in response.headers
