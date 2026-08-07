"""Process-local runtime manager for administrator-configured providers.

The database is authoritative; this manager only holds the active client
references for the current process. Missing/invalid config fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import httpx

from app.common.llm_client import llm_client
from app.common.tts_client import tts_client


@dataclass(frozen=True)
class ProviderProbe:
    status: str
    message: str


class PlatformProviderManager:
    async def probe(self, key: str, *, provider: str, base_url: str, model_name: str, api_key: str, extra_config: dict[str, Any] | None = None) -> ProviderProbe:
        if key not in {"llm", "tts", "ppt"}:
            return ProviderProbe("unavailable", "UNKNOWN_INTEGRATION")
        if not provider or not api_key or (key in {"llm", "ppt"} and not base_url):
            return ProviderProbe("not_configured", "PROVIDER_NOT_CONFIGURED")
        if key == "tts" and provider.lower() in {"doubao", "doubao_tts", "volcengine_doubao_tts"}:
            values = extra_config or {}
            if not base_url or not model_name or not (values.get("speaker") or values.get("voice")):
                return ProviderProbe("not_configured", "PROVIDER_NOT_CONFIGURED")
            # The Stage 8 provider's real remote test is billable. This checks
            # the complete server-side configuration only; a generation task
            # remains subject to teacher confirmation and provider health.
            return ProviderProbe("configured", "CONFIGURATION_READY")
        # A GET/HEAD reachability check avoids sending prompts, audio or paid
        # generation requests. Authentication failures still prove reachability.
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                response = await client.get(base_url.rstrip("/"))
            if response.status_code < 500:
                return ProviderProbe("reachable", f"HTTP_{response.status_code}")
            return ProviderProbe("unavailable", f"HTTP_{response.status_code}")
        except (httpx.HTTPError, OSError) as exc:
            return ProviderProbe("unavailable", type(exc).__name__)

    def refresh(self, key: str, *, provider: str, base_url: str, model_name: str, api_key: str, extra_config: dict[str, Any] | None = None) -> None:
        if key == "llm":
            llm_client.replace_from_config(provider=provider, base_url=base_url, model_name=model_name, api_key=api_key, extra_config=extra_config)
        elif key == "tts":
            from app.core.config import settings
            values = extra_config or {}
            if provider.lower() in {"doubao", "doubao_tts", "volcengine_doubao_tts"}:
                settings.MEDIA_DEMO_MODE = False
                settings.STAGE8_TTS_PROVIDER = "doubao"
                settings.VOLCENGINE_DOUBAO_TTS_WS_URL = base_url
                settings.VOLCENGINE_DOUBAO_TTS_API_KEY = api_key
                settings.VOLCENGINE_DOUBAO_TTS_RESOURCE_ID = model_name
                settings.VOLCENGINE_DOUBAO_TTS_SPEAKER = str(values.get("speaker") or values.get("voice") or "")
            else:
                tts_client.replace_from_config(provider=provider, api_key=api_key, extra_config=values)
        elif key == "ppt":
            from app.services.ppt_generation_service import ppt_generation_service
            ppt_generation_service.xfyun_client.configure(base_url=base_url, api_key=api_key, extra_config=extra_config or {})
        else:
            raise ValueError("UNKNOWN_INTEGRATION")


provider_manager = PlatformProviderManager()
