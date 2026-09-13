"""NX-CT1 代码伴学工具回归（全 mock，不连真实 Backend/PG/LLM）。

锁定四件事：
1. 读哪次提交只信请求作用域（代理层投影注入），无绑定时 fail-closed；
2. 工具无参数——模型无法指定 run_id/course_id；
3. 内部端点未配置/不可达/403/404 时如实返回错误码，绝不假造提交内容；
4. 成功路径透传结构化快照，且顶层为 is_supplementary=True。
"""

from contextlib import contextmanager

import httpx
import pytest

import nexus.tools.submission as sub
from nexus import request_scope
from nexus.tools.submission import read_my_submission

TOKEN = "test-internal-token"
URL = "http://127.0.0.1:8000"


@contextmanager
def _settings_ready(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", URL)
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", TOKEN)
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@contextmanager
def _mock_backend(handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sub.httpx, "AsyncClient", factory)
        yield


def _submission_body() -> dict:
    return {
        "code": 200,
        "message": "本人提交快照读取完成",
        "data": {
            "authority": "oj_submission",
            "is_supplementary": True,
            "course_id": 15,
            "submission": {
                "run_id": "run_abc123",
                "language": "python",
                "outcome": "wrong_answer",
                "source_code": "print('hi')",
                "source_truncated": False,
                "compile_ok": True,
                "passed_count": 1,
                "total_count": 3,
                "test_summary": [
                    {"case_name": "sample1", "passed": True, "reason": ""},
                ],
                "artifacts": {},
            },
        },
    }


@contextmanager
def _bound_submission():
    request_scope.set_scope("42", 15)
    token = request_scope.set_submission(15, "run_abc123")
    try:
        yield
    finally:
        request_scope.reset_submission(token)
        request_scope.set_submission(None, None)


async def test_unbound_submission_fails_closed():
    request_scope.set_scope("42", 15)
    request_scope.set_submission(None, None)
    result = await read_my_submission.ainvoke({})
    assert result["status"] == "no_submission_context"
    assert result["code"] == "SUBMISSION_NOT_BOUND"


async def test_unconfigured_backend_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_URL", raising=False)
    monkeypatch.delenv("NEXUS_BACKEND_INTERNAL_TOKEN", raising=False)
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        with _bound_submission():
            result = await read_my_submission.ainvoke({})
    finally:
        get_settings.cache_clear()
    assert result["code"] == "SUBMISSION_RETRIEVAL_UNCONFIGURED"


async def test_success_returns_bounded_snapshot(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["user"] = request.headers.get("X-Nexus-User-Id")
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_submission_body())

    with _settings_ready(monkeypatch), _mock_backend(handler):
        with _bound_submission():
            result = await read_my_submission.ainvoke({})
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["user"] == "42"
    assert seen["path"] == "/api/v1/nexus-internal/submission"
    assert seen["params"]["course_id"] == "15"
    assert seen["params"]["run_id"] == "run_abc123"
    assert result["status"] == "success"
    assert result["is_supplementary"] is True
    assert result["submission"]["run_id"] == "run_abc123"
    assert result["submission"]["outcome"] == "wrong_answer"


async def test_denied_maps_403(monkeypatch: pytest.MonkeyPatch):
    with _settings_ready(monkeypatch), _mock_backend(
        lambda request: httpx.Response(403, json={"detail": "denied"})
    ):
        with _bound_submission():
            result = await read_my_submission.ainvoke({})
    assert result["status"] == "rejected"
    assert result["code"] == "SUBMISSION_ACCESS_DENIED"


async def test_missing_maps_404(monkeypatch: pytest.MonkeyPatch):
    with _settings_ready(monkeypatch), _mock_backend(
        lambda request: httpx.Response(404, json={"detail": "nope"})
    ):
        with _bound_submission():
            result = await read_my_submission.ainvoke({})
    assert result["status"] == "rejected"
    assert result["code"] == "SUBMISSION_NOT_FOUND"


async def test_unreachable_fails_closed(monkeypatch: pytest.MonkeyPatch):
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with _settings_ready(monkeypatch), _mock_backend(_boom):
        with _bound_submission():
            result = await read_my_submission.ainvoke({})
    assert result["code"] == "SUBMISSION_RETRIEVAL_UNAVAILABLE"
