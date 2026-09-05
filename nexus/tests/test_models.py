"""模型网关 P0 回归：服务端 allowlist 是唯一真相源。

- 缺字段→默认模型；清单命中→原样；未知/空串/空白/非 str→400；
- 模型 id 大小写敏感（计费安全）；
- 同 (mode, model) 复用实例，不同模型隔离，切模型不断 thread 上下文。
全 mock：不调真实 LLM。
"""

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

import nexus.agent
from nexus.agent import InvalidNexusModel, normalize_model_name
from nexus.config import llm_available_models, llm_default_model, llm_models_manifest


def test_normalize_model_name_strict():
    available = ["deepseek-chat", "deepseek-reasoner"]
    assert normalize_model_name(None, available, "deepseek-chat") == "deepseek-chat"
    assert normalize_model_name("deepseek-reasoner", available, "deepseek-chat") == "deepseek-reasoner"
    for bad in ("", "   ", "gpt-4", "DeepSeek-Chat", "deepseek-chatx"):
        with pytest.raises(InvalidNexusModel):
            normalize_model_name(bad, available, "deepseek-chat")
    with pytest.raises(InvalidNexusModel):
        normalize_model_name(123, available, "deepseek-chat")  # type: ignore[arg-type]


def test_models_manifest_default_first_dedup(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_MODEL", "flash-x")
    monkeypatch.setenv("NEXUS_LLM_MODELS", "flash-x, reasoner-y ,")
    from nexus.config import get_settings

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert llm_default_model(settings) == "flash-x"
        assert llm_available_models(settings) == ["flash-x", "reasoner-y"]
        manifest = llm_models_manifest(settings)
        assert manifest["default"] == "flash-x"
        assert [m["id"] for m in manifest["available"]] == ["flash-x", "reasoner-y"]
        assert manifest["available"][0]["default"] is True
    finally:
        get_settings.cache_clear()


async def test_agents_isolated_per_model(monkeypatch: pytest.MonkeyPatch):
    """同 mode 不同 model → 不同实例；同 (mode, model) → 缓存复用。"""
    import nexus.main as main_module
    from langchain_openai import ChatOpenAI

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    main_module._agents = {}
    built = []

    def _spy(model=None):
        # 只记录被请求的模型名；返回的 ChatOpenAI 永不被调用（仅构造图）。
        built.append(model)
        return ChatOpenAI(
            model="deepseek-chat",
            api_key="spy-key-not-real",
            base_url="http://127.0.0.1:9",
        )

    monkeypatch.setattr(nexus.agent, "build_llm", _spy)
    try:
        a1 = main_module.get_agent("general", "deepseek-chat")
        a1_again = main_module.get_agent("general", "deepseek-chat")
        assert a1 is a1_again
        assert built == ["deepseek-chat"]  # 缓存命中不再构建
        # 未在清单的模型：get_agent 纵深防御同样拒绝（端点层已先 400）。
        with pytest.raises(InvalidNexusModel):
            main_module.get_agent("general", "gpt-4")
        # 清单内第二模型可建，且与默认模型实例隔离。
        monkeypatch.setenv("NEXUS_LLM_MODELS", "deepseek-chat,second-model")
        from nexus.config import get_settings

        get_settings.cache_clear()
        try:
            a2 = main_module.get_agent("general", "second-model")
            assert built[-1] == "second-model"
            assert a2 is not a1
            # 跨 mode 同模型同样隔离。
            a3 = main_module.get_agent("research", "second-model")
            assert a3 is not a2
        finally:
            get_settings.cache_clear()
    finally:
        main_module._agents = {}


async def test_chat_rejects_unknown_model_before_agent(monkeypatch: pytest.MonkeyPatch):
    """未知模型在启动 agent 前以 400 INVALID_NEXUS_MODEL 拒绝。"""
    import nexus.main as main_module
    from nexus.main import app

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    class _MustNotRun:
        async def astream(self, inputs, config, stream_mode=None):  # noqa: ANN001, ANN003
            raise AssertionError("模型不应被启动")
            yield  # pragma: no cover

        async def aget_state(self, config):  # noqa: ANN001
            raise AssertionError("模型不应被启动")

    original = main_module._agents
    main_module._agents = {
        ("research", "deepseek-chat"): _MustNotRun(),
        ("general", "deepseek-chat"): _MustNotRun(),
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/nexus/chat",
                json={"message": "hi", "session_id": "m", "model": "gpt-4"},
            )
            assert r.status_code == 400
            assert "INVALID_NEXUS_MODEL" in r.json()["detail"]
            rs = await client.post(
                "/api/v1/nexus/chat/stream",
                json={"message": "hi", "session_id": "m", "model": ""},
            )
            assert rs.status_code == 400
            health = await client.get("/health")
            assert health.status_code == 200
            manifest = health.json()["models"]
            assert manifest["default"] == "deepseek-chat"
            assert manifest["available"][0]["id"] == "deepseek-chat"
    finally:
        main_module._agents = original
