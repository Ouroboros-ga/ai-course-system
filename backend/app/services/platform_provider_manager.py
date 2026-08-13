"""Process-local runtime manager for administrator-configured providers.

The database is authoritative; this manager only holds the active client
references for the current process. Missing/invalid config fails closed.

The administrator toggle (``PlatformIntegrationConfig.enabled``) is applied
through ``refresh`` (enabled) / ``apply_disabled`` (disabled); ``restore_from_db``
re-applies the same state after a process restart so database configuration is
the single source of truth instead of ``.env`` only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging

import httpx

from app.common.llm_client import llm_client
from app.common.tts_client import tts_client


logger = logging.getLogger(__name__)

#: 管理员可一键开关的集成类型。ppt 保持兼容（probe/refresh 已有），
#: 但没有真实/演示二态语义，不参与 apply_disabled。
TOGGLE_KEYS = ("llm", "tts", "asr")
ALL_KEYS = ("llm", "tts", "ppt", "asr")


@dataclass(frozen=True)
class ProviderProbe:
    status: str
    message: str


class PlatformProviderManager:
    async def probe(self, key: str, *, provider: str, base_url: str, model_name: str, api_key: str, extra_config: dict[str, Any] | None = None) -> ProviderProbe:
        if key not in ALL_KEYS:
            return ProviderProbe("unavailable", "UNKNOWN_INTEGRATION")
        if not provider or not api_key:
            return ProviderProbe("not_configured", "PROVIDER_NOT_CONFIGURED")
        if key == "asr":
            # ASR 走 submit/query 两段式 HTTP，探针只验证完整配置，不发起真实识别。
            return ProviderProbe("configured", "CONFIGURATION_READY")
        if key in {"llm", "ppt"} and not base_url:
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
        """应用真实接入配置（enabled=true 时调用）。"""
        if key == "llm":
            llm_client.replace_from_config(provider=provider, base_url=base_url, model_name=model_name, api_key=api_key, extra_config=extra_config)
            llm_client.set_enabled(True)
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
        elif key == "asr":
            from app.services.volcengine_asr import asr_client
            values = extra_config or {}
            asr_client.replace_from_config(
                api_key=api_key,
                resource_id=model_name or str(values.get("resource_id") or ""),
                submit_url=base_url or "",
                query_url=str(values.get("query_url") or ""),
                timeout=int(values.get("timeout") or 0) or None,
            )
            asr_client.set_enabled(True)
        else:
            raise ValueError("UNKNOWN_INTEGRATION")

    def apply_disabled(self, key: str) -> None:
        """应用管理员禁用态（enabled=false）：所有真实调用 fail-closed。

        禁用时不调用任何外部服务；tts 回到本地 demo（fake），llm/asr 拒绝新调用。
        """
        if key == "llm":
            llm_client.set_enabled(False)
        elif key == "tts":
            from app.core.config import settings
            settings.MEDIA_DEMO_MODE = True
            settings.STAGE8_TTS_PROVIDER = "fake"
        elif key == "asr":
            from app.services.volcengine_asr import asr_client
            asr_client.set_enabled(False)
        elif key == "ppt":
            # PPT 生成无真实/演示二态语义，禁用时保持现状（不操作）。
            return
        else:
            raise ValueError("UNKNOWN_INTEGRATION")

    def restore_from_db(self, session_factory: Any) -> None:
        """启动时从数据库恢复集成开关状态（DB 为权威来源）。

        enabled=true 且有密钥 → refresh 真实接入；否则应用禁用态。任何恢复
        失败都落到禁用态（fail-closed），不让未授权外部调用发生。
        """
        from sqlmodel import select
        from app.models.platform_admin_model import PlatformIntegrationConfig
        from app.services.platform_admin_service import decrypt_secret

        try:
            with session_factory() as session:
                items = {
                    item.integration_key: item
                    for item in session.exec(select(PlatformIntegrationConfig)).all()
                }
        except Exception:
            logger.exception("Failed to load platform integration configs at startup; keeping env defaults")
            return

        for key in ALL_KEYS:
            item = items.get(key)
            if item is None:
                continue
            secret = ""
            try:
                secret = decrypt_secret(item.encrypted_api_key)
            except Exception:
                logger.exception("Failed to decrypt integration secret for %s at startup", key)
                secret = ""
            if item.enabled and secret:
                try:
                    self.refresh(
                        key,
                        provider=item.provider,
                        base_url=item.base_url,
                        model_name=item.model_name,
                        api_key=secret,
                        extra_config=item.extra_config,
                    )
                    logger.info("Restored real provider integration %s (enabled)", key)
                except Exception:
                    logger.exception("Restore of integration %s failed; applying disabled state", key)
                    self.apply_disabled(key)
            else:
                self.apply_disabled(key)


provider_manager = PlatformProviderManager()
