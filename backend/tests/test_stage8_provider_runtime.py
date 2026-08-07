from app.core.config import settings
from app.services.stage8_provider_runtime import resolve_stage8_tts_runtime


def test_demo_mode_forces_fake_demo(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_DEMO_MODE", True)
    monkeypatch.setattr(settings, "STAGE8_TTS_PROVIDER", "doubao")
    runtime = resolve_stage8_tts_runtime()
    assert runtime.effective_provider == "fake-demo"
    assert runtime.provider_key == "fake_tts"
    assert runtime.demo_mode is True
    assert runtime.billable is False
    assert runtime.requires_confirmation is False
    assert runtime.status == "ready"


def test_formal_mode_requires_explicit_doubao(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_DEMO_MODE", False)
    monkeypatch.setattr(settings, "STAGE8_TTS_PROVIDER", "")
    runtime = resolve_stage8_tts_runtime()
    assert runtime.status == "needs_configuration"
    assert runtime.healthy is False
    assert runtime.provider is None


def test_formal_doubao_without_credentials_is_not_ready(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_DEMO_MODE", False)
    monkeypatch.setattr(settings, "STAGE8_TTS_PROVIDER", "doubao")
    monkeypatch.setattr(settings, "VOLCENGINE_DOUBAO_TTS_API_KEY", "")
    monkeypatch.setattr(settings, "VOLCENGINE_DOUBAO_TTS_RESOURCE_ID", "")
    monkeypatch.setattr(settings, "VOLCENGINE_DOUBAO_TTS_SPEAKER", "")
    runtime = resolve_stage8_tts_runtime()
    assert runtime.effective_provider == "doubao"
    assert runtime.status == "needs_configuration"
    assert runtime.healthy is False
    assert runtime.billable is True
    assert runtime.requires_confirmation is True
