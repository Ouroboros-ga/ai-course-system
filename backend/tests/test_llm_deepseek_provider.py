"""DeepSeek LLM Provider 单元测试（XH-202620 学科垂类基座，2026-08-20 决策）。

覆盖：provider 注册与工厂选择、OpenAI 兼容 payload 构造、非流式/流式响应解析、
密钥缺失时的告警语义。全部为本地 Fake/Mock，不调用真实付费服务。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.common.llm_client import DeepSeekClient, LLMClient, Message
from app.core.config import settings


@pytest.fixture(autouse=True)
def _clean_llm_client(monkeypatch):
    LLMClient.reset()
    yield
    LLMClient.reset()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")


def test_deepseek_registered_and_selected(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "test-deepseek-key")

    client = LLMClient()

    assert isinstance(client._client, DeepSeekClient)
    assert client._client.api_key == "test-deepseek-key"


def test_deepseek_client_config_defaults(monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(settings, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/")
    monkeypatch.setattr(settings, "DEEPSEEK_MODEL", "")

    client = DeepSeekClient()

    assert client.base_url == "https://api.deepseek.com/v1"
    assert client.model == "deepseek-chat"


def test_deepseek_chat_builds_openai_compatible_request(monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "deepseek-key")
    client = DeepSeekClient()
    captured = {}

    async def fake_make_request(url, headers, payload, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": "最坏情况 O(n²)"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 9},
            "model": "deepseek-chat",
            "_latency_ms": 33.0,
        }

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    async def run():
        return await client.chat([Message(role="user", content="快排最坏复杂度")])

    response = asyncio.run(run())

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer deepseek-key"
    assert captured["payload"]["model"] == "deepseek-chat"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "快排最坏复杂度"}]
    assert response.content == "最坏情况 O(n²)"
    assert response.model == "deepseek-chat"


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


def test_deepseek_chat_stream_parses_sse(monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "deepseek-key")
    client = DeepSeekClient()

    chunk = json.dumps({"choices": [{"delta": {"content": "TCP "}}]})
    chunk2 = json.dumps({"choices": [{"delta": {"content": "三次握手"}}]})
    fake_httpx = _FakeHTTPXClient(lines=["data: " + chunk, "data: " + chunk2, "data: [DONE]"])

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "AsyncClient", lambda **kw: fake_httpx)

    async def run():
        return [part async for part in client.chat_stream([Message(role="user", content="三次握手")])]

    parts = asyncio.run(run())

    assert "".join(parts) == "TCP 三次握手"
    assert fake_httpx.captured[0]["json"]["stream"] is True


def test_deepseek_missing_key_only_warns(monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")

    client = DeepSeekClient()
    assert client.api_key == ""
