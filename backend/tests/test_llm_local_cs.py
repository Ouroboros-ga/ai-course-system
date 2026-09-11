"""本地 CS 微调模型选项（LLM_PROVIDER=local_cs）回归。

- 分发：local_cs 进 SparkCSLocalClient；未知 provider 仍回退豆包（旧语义不动）；
- 接线： base/model/key 进 URL＋payload＋鉴权头；全离线（_make_request 替身）；
- 关闭：管理员 set_enabled(False) 即 LLMError，不静默降级。
"""
import pytest

from app.common.llm_client import (
    DoubaoClient,
    LLMClient,
    LLMError,
    Message,
    SparkCSLocalClient,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    LLMClient.reset()
    yield
    LLMClient.reset()


def _local_env(monkeypatch, provider="local_cs",
               base="http://127.0.0.1:8001/v1",
               model="spark-x25-4b-cs", key=""):
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", provider)
    monkeypatch.setattr("app.core.config.settings.LOCAL_CS_BASE_URL", base)
    monkeypatch.setattr("app.core.config.settings.LOCAL_CS_MODEL", model)
    monkeypatch.setattr("app.core.config.settings.LOCAL_CS_API_KEY", key)


def test_dispatch_local_cs(monkeypatch):
    _local_env(monkeypatch)
    client = LLMClient()
    assert isinstance(client._client, SparkCSLocalClient)
    assert issubclass(SparkCSLocalClient, object)
    # 与 OpenAI 兼容协议同形（chat/chat_stream 由基类提供）。
    from app.common.llm_client import OpenAIClient
    assert issubclass(SparkCSLocalClient, OpenAIClient)


def test_dispatch_unknown_still_falls_back_doubao(monkeypatch):
    _local_env(monkeypatch, provider="nope")
    client = LLMClient()
    assert isinstance(client._client, DoubaoClient)


def test_local_cs_wiring(monkeypatch):
    _local_env(monkeypatch, base="http://gpu-box:8000/v1",
               model="spark-x25-4b-cs", key="k-local")
    client = SparkCSLocalClient()
    assert client.base_url == "http://gpu-box:8000/v1"
    assert client.model == "spark-x25-4b-cs"

    seen = {}

    async def _fake_make_request(url, headers, payload, timeout):
        seen["url"] = url
        seen["headers"] = headers
        seen["payload"] = payload
        return {"choices": [{"message": {"content": "ok"},
                             "finish_reason": "stop"}],
                "model": "spark-x25-4b-cs"}

    monkeypatch.setattr(client, "_make_request", _fake_make_request)
    import asyncio

    response = asyncio.run(client.chat([Message(role="user", content="hi")]))
    assert seen["url"] == "http://gpu-box:8000/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k-local"
    assert seen["payload"]["model"] == "spark-x25-4b-cs"
    assert seen["payload"]["messages"] == [{"role": "user", "content": "hi"}]
    assert response.content == "ok"
    assert response.model == "spark-x25-4b-cs"


def test_local_cs_defaults_without_env(monkeypatch):
    _local_env(monkeypatch, base="", model="", key="")
    client = SparkCSLocalClient()
    assert client.base_url == "http://127.0.0.1:8001/v1"
    assert client.model == "spark-x25-4b-cs"


def test_local_cs_disabled_fails_closed(monkeypatch):
    _local_env(monkeypatch)
    client = LLMClient()
    client.set_enabled(False)
    import asyncio

    with pytest.raises(LLMError):
        asyncio.run(client.chat([Message(role="user", content="hi")]))
