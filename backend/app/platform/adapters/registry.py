import os

from app.core.config import settings
from app.platform.adapters.digital_human import DigitalHumanAdapter
from app.platform.adapters.llm import LLMAdapter
from app.platform.adapters.ppt import PPTAdapter
from app.platform.adapters.tts import TTSAdapter
from app.platform.adapters.voice_clone import VoiceCloneAdapter


def get_digital_human_provider_name(provider: str | None = None) -> str:
    return (
        provider
        or os.getenv("DIGITAL_HUMAN_PROVIDER")
        or getattr(settings, "DIGITAL_HUMAN_PROVIDER", "digital_human")
        or "digital_human"
    ).lower()


def _is_legacy_digital_human_client(client) -> bool:
    return (
        client is not None
        and client.__class__.__module__ == "app.common.digital_human_client"
        and client.__class__.__name__ == "DigitalHumanClient"
    )


def get_llm_adapter(client=None) -> LLMAdapter:
    if client is None:
        from app.common.llm_client import llm_client
        client = llm_client
    return LLMAdapter(client)


def get_tts_adapter(client=None) -> TTSAdapter:
    if client is None:
        from app.common.tts_client import tts_client
        client = tts_client
    return TTSAdapter(client)


def get_voice_clone_adapter(client=None) -> VoiceCloneAdapter:
    if client is None:
        from app.common.tts_client import voice_clone_client
        client = voice_clone_client
    return VoiceCloneAdapter(client)


def get_ppt_adapter(client=None) -> PPTAdapter:
    if client is None:
        from app.services.ppt_generation_service import ppt_generation_service
        client = ppt_generation_service.xfyun_client
    return PPTAdapter(client)


def get_digital_human_adapter(client=None, provider: str | None = None) -> DigitalHumanAdapter:
    provider_name = get_digital_human_provider_name(provider)
    if provider_name in {"duix", "duix_avatar"}:
        if client is None or _is_legacy_digital_human_client(client):
            from app.platform.adapters.duix_avatar import DuixAvatarProvider
            client = DuixAvatarProvider()
        return DigitalHumanAdapter(client, provider="duix")
    if client is None:
        from app.common.digital_human_client import digital_human_client
        client = digital_human_client
    return DigitalHumanAdapter(client)
