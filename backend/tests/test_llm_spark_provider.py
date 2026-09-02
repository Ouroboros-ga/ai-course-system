"""讯飞星火 LLM Provider 单元测试（挑战杯 XH-202620 学科垂类基座）。

覆盖：provider 注册与工厂选择、OpenAI 兼容 payload 构造、非流式/流式响应解析、
密钥缺失时的告警语义。全部为本地 Fake/Mock，不调用真实付费服务。

注：使用 ``asyncio.run`` 而非 ``pytest.mark.asyncio`` 以避免对 pytest-asyncio
插件的硬依赖（与 P1-4/P1-5 测试保持一致）。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.common.llm_client import LLMClient, Message, SparkClient
from app.core.config import settings


@pytest.fixture(autouse=True)
def _clean_llm_client(monkeypatch):
    LLMClient.reset()
    yield
    LLMClient.reset()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "doubao")


def test_spark_registered_and_selected_when_provider_is_spark(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "spark")
    monkeypatch.setattr(settings, "XFYUN_SPARK_API_KEY", "test-spark-key")

    client = LLMClient()

    assert isinstance(client._client, SparkClient)
    assert client._client.api_key == "test-spark-key"


def test_unknown_provider_falls_back_to_doubao(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "not-a-provider")

    client = LLMClient()

    assert not isinstance(client._client, SparkClient)


def test_spark_client_config_defaults(monkeypatch):
    monkeypatch.setattr(settings, "XFYUN_SPARK_API_KEY", "k")
    monkeypatch.setattr(settings, "XFYUN_SPARK_BASE_URL", "https://spark-api-open.xf-yun.com/v1/")
    monkeypatch.setattr(settings, "XFYUN_SPARK_MODEL", "")

    client = SparkClient()

    assert client.base_url == "https://spark-api-open.xf-yun.com/v1"
    assert client.model == "4.0Ultra"


def test_spark_chat_builds_openai_compatible_request(monkeypatch):
    monkeypatch.setattr(settings, "XFYUN_SPARK_API_KEY", "spark-key")
    client = SparkClient()
    captured = {}

    async def fake_make_request(url, headers, payload, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": "时间复杂度为 O(n)"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            "model": "4.0Ultra",
            "_latency_ms": 42.0,
        }

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    async def run():
        return await client.chat([Message(role="user", content="分析快排复杂度")])

    response = asyncio.run(run())

    assert captured["url"] == "https://spark-api-open.xf-yun.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer spark-key"
    assert captured["payload"]["model"] == "4.0Ultra"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "分析快排复杂度"}]
    assert response.content == "时间复杂度为 O(n)"
    assert response.finish_reason == "stop"
    assert response.model == "4.0Ultra"


class _FakeSSE:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeResponseCM:
    def __init__(self, lines):
        self._resp = _FakeSSE(lines)

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args):
        return False


class _FakeHTTPXClient:
    def __init__(self, lines):
        self._lines = lines
        self.captured = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        self.captured.append({"method": method, "url": url, **kwargs})
        return _FakeResponseCM(self._lines)


def test_spark_chat_stream_parses_sse_and_marks_stream(monkeypatch):
    monkeypatch.setattr(settings, "XFYUN_SPARK_API_KEY", "spark-key")
    client = SparkClient()

    chunk = json.dumps({"choices": [{"delta": {"content": "TCP "}}]})
    chunk2 = json.dumps({"choices": [{"delta": {"content": "三次握手"}}]})
    fake_httpx = _FakeHTTPXClient(lines=["data: " + chunk, "data: " + chunk2, "data: [DONE]"])

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "AsyncClient", lambda **kw: fake_httpx)

    async def run():
        return [part async for part in client.chat_stream([Message(role="user", content="三次握手")])]

    parts = asyncio.run(run())

    assert "".join(parts) == "TCP 三次握手"
    assert fake_httpx.captured[0]["url"] == "https://spark-api-open.xf-yun.com/v1/chat/completions"
    assert fake_httpx.captured[0]["json"]["stream"] is True


def test_spark_missing_key_only_warns(monkeypatch):
    monkeypatch.setattr(settings, "XFYUN_SPARK_API_KEY", "")

    # 不抛异常：只告警；真正调用时由网关/上游失败并按调用方语义降级。
    client = SparkClient()
    assert client.api_key == ""
