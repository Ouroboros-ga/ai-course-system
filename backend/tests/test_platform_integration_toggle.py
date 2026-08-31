"""管理员一键开关（真实接入 true/false）语义测试。

覆盖：list_integrations 含 asr；enabled=false 保存为禁用态且不 probe 外部服务；
llm/asr 禁用后调用 fail-closed；tts 禁用回到 demo；启动恢复 restore_from_db。
所有用例均不发起真实付费调用。
"""
from __future__ import annotations

import asyncio

import pytest

from app.common.llm_client import LLMError, llm_client
from app.services.volcengine_asr import (
    VolcengineAsrClient,
    VolcengineAsrError,
    asr_client,
)


@pytest.fixture(autouse=True)
def _reset_provider_state(session):
    """隔离共享测试库中的集成配置与进程级单例状态。"""
    from sqlmodel import select
    from app.models.platform_admin_model import PlatformIntegrationConfig
    for row in session.exec(select(PlatformIntegrationConfig)).all():
        session.delete(row)
    session.commit()
    asr_client.set_enabled(True)
    yield
    asr_client.set_enabled(True)


def _fake_session_factory(session):
    def factory():
        return session
    return factory


def test_list_integrations_includes_asr(session):
    from app.services.platform_admin_service import list_integrations

    keys = [item["integration_key"] for item in list_integrations(session)]
    assert keys == ["llm", "tts", "ppt", "asr"]


def test_disable_asr_skips_probe_and_fails_closed(session):
    from app.services.platform_admin_service import update_integration

    updated = asyncio.run(update_integration(
        session, 1, "asr",
        {"provider": "volcengine", "enabled": False, "expected_version": 0},
    ))
    assert updated["enabled"] is False
    assert updated["health_status"] == "disabled"
    assert not asr_client._enabled

    with pytest.raises(VolcengineAsrError) as exc:
        asr_client.submit("https://example.invalid/audio.wav", task_id="t1")
    assert exc.value.error_code == "ASR_DISABLED"


def test_enable_asr_with_complete_config_activates_client(session):
    from app.services.platform_admin_service import update_integration

    updated = asyncio.run(update_integration(
        session, 1, "asr",
        {
            "provider": "volcengine",
            "base_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            "model_name": "volc.seedasr.auc",
            "api_key": "test-asr-key",
            "enabled": True,
            "expected_version": 0,
        },
    ))
    assert updated["enabled"] is True
    assert updated["health_status"] == "healthy"
    assert asr_client._enabled is True
    assert asr_client.api_key == "test-asr-key"


def test_enable_asr_without_secret_rejected(session):
    from fastapi import HTTPException
    from app.services.platform_admin_service import update_integration

    with pytest.raises(HTTPException) as exc:
        asyncio.run(update_integration(
            session, 1, "asr",
            {"provider": "volcengine", "enabled": True, "expected_version": 0},
        ))
    assert exc.value.status_code == 503


def test_disable_llm_makes_chat_fail_closed():
    # 测试环境 conftest 会把 llm_client 替换为 FakeLLMClient；这里直接用真实
    # 单例验证禁用语义，避免依赖 fake 注入。
    from app.common.llm_client import LLMClient as RealLLMClient

    real_client = RealLLMClient()
    real_client.set_enabled(False)

    async def _chat():
        return await real_client.chat([])

    with pytest.raises(LLMError) as exc:
        asyncio.run(_chat())
    assert exc.value.reason_code == "LLM_DISABLED"
    real_client.set_enabled(True)


def test_disable_tts_returns_to_demo(session):
    from app.core.config import settings
    from app.services.platform_admin_service import update_integration

    asyncio.run(update_integration(
        session, 1, "tts", {"provider": "doubao", "enabled": False, "expected_version": 0},
    ))
    assert settings.MEDIA_DEMO_MODE is True
    assert settings.STAGE8_TTS_PROVIDER == "fake"


def test_read_env_config_llm_prefers_deepseek_specific_vars():
    """LLM_PROVIDER=deepseek 时，env 检测应读取 DEEPSEEK_* 专属变量。

    DeepSeekClient 只认 DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL/DEEPSEEK_MODEL；
    若 read_env_config 仅读 LLM_*，则 DEEPSEEK_API_KEY 已配置但 LLM_API_KEY
    为空时，启动同步/DB 补全会把可用配置误判为未配置（线上 401 排查结论）。
    """
    from app.core.config import settings
    from app.services.platform_provider_manager import provider_manager

    saved = {name: getattr(settings, name) for name in (
        "LLM_PROVIDER", "LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL_NAME",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
    )}
    try:
        settings.LLM_PROVIDER = "deepseek"
        settings.LLM_API_KEY = ""
        settings.LLM_API_BASE = ""
        settings.LLM_MODEL_NAME = ""
        settings.DEEPSEEK_API_KEY = "sk-env-test-deepseek"
        settings.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
        settings.DEEPSEEK_MODEL = "deepseek-chat"

        cfg = provider_manager.read_env_config("llm")
        assert cfg is not None
        assert cfg["provider"] == "deepseek"
        assert cfg["api_key"] == "sk-env-test-deepseek"
        assert cfg["base_url"] == "https://api.deepseek.com"
        assert cfg["model_name"] == "deepseek-chat"
        assert cfg["enabled"] is True
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def test_restore_from_db_applies_enabled_and_disabled(session):
    from app.services.platform_admin_service import update_integration
    from app.services.platform_provider_manager import provider_manager

    # 先保存 asr 真实配置（enabled=true），再保存 asr 禁用配置。
    # 测试环境 conftest 会注入 FakeLLMClient，因此不在此处断言 llm 分支。
    asyncio.run(update_integration(
        session, 1, "asr",
        {"provider": "volcengine", "base_url": "https://example.invalid/submit",
         "model_name": "volc.seedasr.auc", "api_key": "restore-key", "enabled": True},
    ))

    # 复位进程态，模拟重启
    asr_client.set_enabled(False)

    provider_manager.restore_from_db(_fake_session_factory(session))

    # asr：DB enabled=true + 密钥 → 恢复真实接入
    assert asr_client._enabled is True
    assert asr_client.api_key == "restore-key"

    # 再禁用后重启，应恢复为禁用态
    asyncio.run(update_integration(session, 1, "asr", {"provider": "volcengine", "enabled": False}))
    asr_client.set_enabled(True)
    provider_manager.restore_from_db(_fake_session_factory(session))
    assert asr_client._enabled is False
