"""NX-A1 Runtime 侧回归：read_attachment 作用域门 + 内部端点消费。

- attachment_id 只读执行上下文（Backend 验主+绑定后注入），scope 外拒绝；
- Backend 侧 owner/会话绑定拒绝原样透传；不可达 fail-closed。
全 mock（respx 拦内部端点），不调真实 Backend。
"""

import httpx
import respx

from nexus import request_scope
from nexus.tools.attachments import read_attachment

_INTERNAL = "http://127.0.0.1:18000"


async def _scope(user="7", session="s1", attachments=("a1",)):
    tokens = []
    from nexus.request_scope import set_scope

    tokens.append(set_scope(user, None))
    from nexus.request_scope import set_execution_scope

    tokens.append(set_execution_scope(session, None))
    tokens.append(request_scope.set_attachments(list(attachments)))
    return tokens


async def _unscope(tokens):
    from nexus.request_scope import reset_execution_scope, reset_scope

    request_scope.reset_attachments(tokens[2])
    reset_execution_scope(tokens[1])
    reset_scope(tokens[0])


async def test_read_attachment_out_of_scope_rejected(monkeypatch):
    """scope 外 id 直接拒绝，零出站（Backend 都不碰）。"""
    import nexus.tools.attachments as mod

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("scope 外不得出站")

    monkeypatch.setattr(mod.httpx, "AsyncClient", _must_not_call)
    tokens = await _scope(attachments=("a1",))
    try:
        result = await read_attachment.ainvoke({"attachment_id": "evil"})
    finally:
        await _unscope(tokens)
    assert result["status"] == "rejected"
    assert result["code"] == "ATTACHMENT_NOT_IN_SCOPE"


async def test_read_attachment_success_items(monkeypatch):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", _INTERNAL)
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        tokens = await _scope()
        try:
            with respx.mock:
                seen = {}

                def _capture(request: httpx.Request) -> httpx.Response:
                    seen["session"] = request.headers.get("X-Nexus-Session-Id")
                    seen["user"] = request.headers.get("X-Nexus-User-Id")
                    return httpx.Response(200, json={"data": {
                        "attachment_id": "a1", "filename": "doc.pdf",
                        "kind": "pdf", "status": "ready",
                        "truncated": False,
                        "blocks": [{"kind": "text", "locator": "p1", "text": "hello"}],
                    }})

                respx.get(f"{_INTERNAL}/api/v1/nexus-internal/attachments/a1/content").mock(
                    side_effect=_capture)
                result = await read_attachment.ainvoke({"attachment_id": "a1"})
        finally:
            await _unscope(tokens)
        assert result["status"] == "success"
        assert result["items"][0]["locator"] == "p1"
        assert result["is_supplementary"] is True
        assert seen == {"session": "s1", "user": "7"}
    finally:
        get_settings.cache_clear()


async def test_read_attachment_backend_denials_passthrough(monkeypatch):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", _INTERNAL)
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        tokens = await _scope()
        try:
            with respx.mock:
                respx.get(f"{_INTERNAL}/api/v1/nexus-internal/attachments/a1/content").mock(
                    return_value=httpx.Response(403, json={"detail": "ATTACHMENT_SESSION_MISMATCH"}))
                rejected = await read_attachment.ainvoke({"attachment_id": "a1"})
                assert rejected["status"] == "rejected"
                assert rejected["code"] == "ATTACHMENT_SESSION_MISMATCH"
        finally:
            await _unscope(tokens)
    finally:
        get_settings.cache_clear()


async def test_read_attachment_unconfigured_fails_closed(monkeypatch):
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_URL", raising=False)
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_TOKEN", raising=False)
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        tokens = await _scope()
        try:
            result = await read_attachment.ainvoke({"attachment_id": "a1"})
        finally:
            await _unscope(tokens)
        assert result["status"] == "unavailable"
    finally:
        get_settings.cache_clear()


def test_attachments_scope_roundtrip():
    token = request_scope.set_attachments(["a1", " a2 ", "", "a1"])
    assert request_scope.current_attachments() == ("a1", "a2")
    request_scope.reset_attachments(token)
    assert request_scope.current_attachments() == ()
