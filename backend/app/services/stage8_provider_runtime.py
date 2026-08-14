"""Single source of truth for the Stage 8 TTS runtime.

The generic ``TTS_PROVIDER`` setting belongs to the legacy document/video
chain.  Media authoring and playback use this module instead, so a browser
cannot select a paid provider by changing a request field.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.tts_provider import TTSProvider, TtsProviderConfigurationError, get_tts_provider


@dataclass(frozen=True)
class Stage8TtsRuntime:
    configured_provider: str
    effective_provider: str
    provider_key: str
    provider_version: str
    display_name: str
    demo_mode: bool
    billable: bool
    requires_confirmation: bool
    healthy: bool
    status: str
    message: str
    provider: TTSProvider | None = None

    def as_public_dict(self) -> dict[str, object]:
        """Return a safe health payload; no API key, speaker, or secret leaks."""
        return {
            "configured_provider": self.configured_provider,
            "effective_provider": self.effective_provider,
            "provider_key": self.provider_key,
            "provider_version": self.provider_version,
            "display_name": self.display_name,
            "demo_mode": self.demo_mode,
            "billable": self.billable,
            "requires_confirmation": self.requires_confirmation,
            "healthy": self.healthy,
            "status": self.status,
            "message": self.message,
        }


def resolve_stage8_tts_runtime() -> Stage8TtsRuntime:
    """Resolve the configured/effective Stage 8 provider fail-closed.

    ``MEDIA_DEMO_MODE=true`` always wins and forces the non-billable fake
    provider, even if a formal provider is present in the environment.
    Outside demo mode only the explicit ``STAGE8_TTS_PROVIDER=doubao`` value
    is accepted; missing credentials produce ``needs_configuration`` rather
    than silently falling back to fake.
    """
    from app.core.config import settings

    demo_mode = bool(getattr(settings, "MEDIA_DEMO_MODE", False))
    configured = (getattr(settings, "STAGE8_TTS_PROVIDER", "") or "").strip().lower()
    if demo_mode:
        provider = get_tts_provider("fake", strict=True)
        healthy = bool(provider.health_check())
        return Stage8TtsRuntime(
            configured_provider=configured or "fake",
            effective_provider="fake-demo",
            provider_key=provider.provider_key,
            provider_version=provider.provider_version,
            display_name="本地演示模式",
            demo_mode=True,
            billable=False,
            requires_confirmation=False,
            healthy=healthy,
            status="ready" if healthy else "blocked",
            message="本地演示模式，不调用付费 TTS" if healthy else "Fake Demo Provider 不可用",
            provider=provider,
        )

    if configured != "doubao":
        return Stage8TtsRuntime(
            configured_provider=configured or "unset",
            effective_provider="",
            provider_key="",
            provider_version="",
            display_name="未配置",
            demo_mode=False,
            billable=True,
            requires_confirmation=True,
            healthy=False,
            status="needs_configuration",
            message="正式模式必须显式配置 STAGE8_TTS_PROVIDER=doubao；未配置时不会回退 Fake",
            provider=None,
        )

    provider = get_tts_provider("doubao", strict=True)
    healthy = bool(provider.health_check())
    return Stage8TtsRuntime(
        configured_provider="doubao",
        effective_provider="doubao",
        provider_key=provider.provider_key,
        provider_version=provider.provider_version,
        display_name="豆包语音",
        demo_mode=False,
        billable=True,
        requires_confirmation=True,
        healthy=healthy,
        status="ready" if healthy else "needs_configuration",
        message="正式豆包 Provider；提交任务前需要教师确认费用" if healthy else "豆包 Provider 配置不完整，未调用外部服务",
        provider=provider,
    )


def get_stage8_tts_provider(requested_key: str | None = None, *, allow_test_provider: bool = True) -> TTSProvider:
    """Return the server-selected provider and reject browser-side switching."""
    requested = (requested_key or "").strip().lower()
    import os
    if allow_test_provider and os.getenv("AI_COURSE_TESTING") == "1" and requested not in {
        "", "fake", "fake_tts", "doubao", "doubao_tts", "volcengine_doubao_tts",
    }:
        return get_tts_provider(requested, strict=True)
    runtime = resolve_stage8_tts_runtime()
    if runtime.provider is None or runtime.status != "ready":
        raise TtsProviderConfigurationError(runtime.message)

    if not requested:
        return runtime.provider
    aliases = {
        runtime.provider.provider_key.lower(),
        "fake", "fake_tts",
        "doubao", "doubao_tts", "volcengine_doubao_tts",
    }
    if requested in aliases and ((runtime.demo_mode and requested in {"fake", "fake_tts", runtime.provider.provider_key.lower()})
                                 or (not runtime.demo_mode and requested in {"doubao", "doubao_tts", "volcengine_doubao_tts", runtime.provider.provider_key.lower()})):
        return runtime.provider

    # Existing unit tests register deliberately failing/mock providers. Keep
    # that seam test-only; it is never available from a normal browser call.
    raise TtsProviderConfigurationError("Stage 8 TTS Provider 由服务端配置决定，不能由请求选择")
