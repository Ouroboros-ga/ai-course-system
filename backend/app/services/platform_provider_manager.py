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

#: 豆包 TTS 的 provider 别名（火山引擎豆包 TTS 即豆包语音）
_DOUBAO_TTS_ALIASES = {"doubao", "doubao_tts", "volcengine_doubao_tts", "volcengine"}


@dataclass(frozen=True)
class ProviderProbe:
    status: str
    message: str


def _is_doubao_tts(provider: str) -> bool:
    return (provider or "").strip().lower() in _DOUBAO_TTS_ALIASES


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
        if key == "tts" and _is_doubao_tts(provider):
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
            if _is_doubao_tts(provider):
                # 豆包 TTS（火山引擎豆包语音）用于 Stage 8 媒体生成，
                # 统一设置 STAGE8_TTS_PROVIDER=doubao 并关闭 demo 模式。
                settings.MEDIA_DEMO_MODE = False
                settings.STAGE8_TTS_PROVIDER = "doubao"
                settings.VOLCENGINE_DOUBAO_TTS_WS_URL = base_url
                settings.VOLCENGINE_DOUBAO_TTS_API_KEY = api_key
                settings.VOLCENGINE_DOUBAO_TTS_RESOURCE_ID = model_name
                settings.VOLCENGINE_DOUBAO_TTS_SPEAKER = str(values.get("speaker") or values.get("voice") or "")
            else:
                tts_client.replace_from_config(provider=provider, api_key=api_key, extra_config=values)
            # 批量媒体建设的字符数/节点数限额（可选，由管理员在 extra_config 中覆盖默认值）
            if values.get("max_billable_chars"):
                try:
                    settings.MEDIA_BATCH_MAX_BILLABLE_CHARS = max(1000, int(values["max_billable_chars"]))
                except (TypeError, ValueError):
                    pass
            if values.get("max_nodes"):
                try:
                    settings.MEDIA_BATCH_MAX_NODES = max(1, int(values["max_nodes"]))
                except (TypeError, ValueError):
                    pass
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
            settings.MEDIA_BATCH_MAX_BILLABLE_CHARS = 50_000
            settings.MEDIA_BATCH_MAX_NODES = 20
        elif key == "asr":
            from app.services.volcengine_asr import asr_client
            asr_client.set_enabled(False)
        elif key == "ppt":
            # PPT 生成无真实/演示二态语义，禁用时保持现状（不操作）。
            return
        else:
            raise ValueError("UNKNOWN_INTEGRATION")

    def get_runtime_health(self, key: str) -> tuple[str, str]:
        """读取当前进程内实际运行时的健康状态，用于 list_integrations 时
        保证管理界面显示与真实调用情况一致。

        返回 (status, message)。
        """
        if key == "llm":
            if not getattr(llm_client, "_enabled", True):
                return "disabled", "真实接入已关闭；未调用外部服务"
            try:
                from app.core.config import settings
                if not settings.LLM_API_KEY or not settings.LLM_API_BASE or not settings.LLM_MODEL_NAME:
                    return "not_configured", "PROVIDER_NOT_CONFIGURED"
                return "healthy", "ENV_RESTORED"
            except Exception:
                return "not_configured", "PROVIDER_NOT_CONFIGURED"
        if key == "tts":
            try:
                from app.services.stage8_provider_runtime import resolve_stage8_tts_runtime
                runtime = resolve_stage8_tts_runtime()
                if runtime.demo_mode:
                    return "disabled", "本地演示模式（fake）"
                if runtime.healthy:
                    return "healthy", f"Stage8:{runtime.effective_provider}"
                return "unavailable", runtime.message
            except Exception as exc:
                return "unavailable", type(exc).__name__
        if key == "asr":
            try:
                from app.services.volcengine_asr import asr_client
                if not getattr(asr_client, "_enabled", False):
                    return "disabled", "真实接入已关闭；未调用外部服务"
                if not asr_client.api_key:
                    return "not_configured", "PROVIDER_NOT_CONFIGURED"
                return "healthy", "ASR_CLIENT_CONFIGURED"
            except Exception:
                return "not_configured", "PROVIDER_NOT_CONFIGURED"
        if key == "ppt":
            try:
                from app.services.ppt_generation_service import ppt_generation_service
                xf = getattr(ppt_generation_service, "xfyun_client", None)
                if xf and getattr(xf, "api_key", None):
                    return "healthy", "PPT_CLIENT_CONFIGURED"
                return "not_configured", "PROVIDER_NOT_CONFIGURED"
            except Exception:
                return "not_configured", "PROVIDER_NOT_CONFIGURED"
        return "unknown", "UNKNOWN_INTEGRATION"

    def read_env_config(self, key: str) -> dict[str, Any] | None:
        """从环境变量/settings 中读取某集成的有效配置。

        返回可用于写入 DB 的 dict（provider/base_url/model_name/api_key/extra_config/enabled），
        配置不完整时返回 None。
        """
        from app.core.config import settings

        if key == "llm":
            provider = (settings.LLM_PROVIDER or "").strip().lower()
            api_key = settings.LLM_API_KEY or ""
            base_url = settings.LLM_API_BASE or ""
            model_name = settings.LLM_MODEL_NAME or ""
            if provider and api_key and base_url and model_name:
                return {
                    "provider": provider,
                    "base_url": base_url,
                    "model_name": model_name,
                    "api_key": api_key,
                    "extra_config": {},
                    "enabled": True,
                }
            return None

        if key == "tts":
            # 优先识别 Stage 8 的豆包 TTS 配置（正式媒体生成路径）
            stage8_provider = (getattr(settings, "STAGE8_TTS_PROVIDER", "") or "").strip().lower()
            ws_url = getattr(settings, "VOLCENGINE_DOUBAO_TTS_WS_URL", "") or ""
            api_key = getattr(settings, "VOLCENGINE_DOUBAO_TTS_API_KEY", "") or ""
            resource_id = getattr(settings, "VOLCENGINE_DOUBAO_TTS_RESOURCE_ID", "") or ""
            speaker = getattr(settings, "VOLCENGINE_DOUBAO_TTS_SPEAKER", "") or ""
            demo_mode = bool(getattr(settings, "MEDIA_DEMO_MODE", False))
            if stage8_provider == "doubao" and not demo_mode and api_key and ws_url and resource_id and speaker:
                return {
                    "provider": "doubao",
                    "base_url": ws_url,
                    "model_name": resource_id,
                    "api_key": api_key,
                    "extra_config": {"speaker": speaker},
                    "enabled": True,
                }
            # 回退：遗留 TTS_PROVIDER 路径（aliyun/tencent/volcengine/mock）
            legacy_provider = (settings.TTS_PROVIDER or "").strip().lower()
            tts_api_key = settings.TTS_API_KEY or ""
            if legacy_provider and legacy_provider != "mock" and tts_api_key:
                return {
                    "provider": legacy_provider,
                    "base_url": "",
                    "model_name": "",
                    "api_key": tts_api_key,
                    "extra_config": {
                        "app_id": settings.TTS_APP_ID or "",
                        "voice": settings.TTS_VOICE or "",
                    },
                    "enabled": True,
                }
            return None

        if key == "asr":
            api_key = settings.VOLCENGINE_ASR_API_KEY or ""
            if api_key:
                return {
                    "provider": "volcengine",
                    "base_url": settings.VOLCENGINE_ASR_SUBMIT_URL or "",
                    "model_name": settings.VOLCENGINE_ASR_RESOURCE_ID or "",
                    "api_key": api_key,
                    "extra_config": {
                        "query_url": settings.VOLCENGINE_ASR_QUERY_URL or "",
                    },
                    "enabled": True,
                }
            return None

        if key == "ppt":
            # PPT 走科大讯飞，保留兼容
            api_key = getattr(settings, "XFYUN_TTS_API_KEY", "") or ""
            base_url = getattr(settings, "XFYUN_TTS_WS_URL", "") or ""
            app_id = getattr(settings, "XFYUN_TTS_APP_ID", "") or ""
            if api_key and app_id:
                return {
                    "provider": "xfyun",
                    "base_url": base_url,
                    "model_name": "",
                    "api_key": api_key,
                    "extra_config": {"app_id": app_id},
                    "enabled": True,
                }
            return None

        return None

    def restore_from_db(self, session_factory: Any) -> None:
        """启动时从数据库恢复集成开关状态（DB 为权威来源）。

        enabled=true 且有密钥 → refresh 真实接入；否则应用禁用态。任何恢复
        失败都落到禁用态（fail-closed），不让未授权外部调用发生。

        另外，如果数据库中缺失某集成的记录，但环境变量/settings 中已有有效
        配置（即进程启动时已可工作），则把该配置同步写入数据库，使管理
        界面显示与实际运行状态一致。
        """
        from sqlmodel import select
        from app.models.platform_admin_model import PlatformIntegrationConfig
        from app.services.platform_admin_service import decrypt_secret, encrypt_secret

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
            if item is not None:
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
                continue

            # DB 中无记录：检查环境变量是否有有效配置，有则同步写入 DB 并应用
            env_cfg = self.read_env_config(key)
            if env_cfg is None:
                continue
            try:
                self.refresh(
                    key,
                    provider=env_cfg["provider"],
                    base_url=env_cfg["base_url"],
                    model_name=env_cfg["model_name"],
                    api_key=env_cfg["api_key"],
                    extra_config=env_cfg["extra_config"],
                )
            except Exception:
                logger.exception("Env config for %s failed to apply at startup; skipping sync", key)
                continue
            try:
                with session_factory() as session:
                    new_item = PlatformIntegrationConfig(
                        integration_key=key,
                        provider=env_cfg["provider"],
                        base_url=env_cfg["base_url"],
                        model_name=env_cfg["model_name"],
                        encrypted_api_key=encrypt_secret(env_cfg["api_key"]),
                        api_key_last4=env_cfg["api_key"][-4:] if env_cfg["api_key"] else "",
                        extra_config=env_cfg["extra_config"] or {},
                        enabled=bool(env_cfg["enabled"]),
                        health_status="healthy",
                        health_message="ENV_SYNCED_AT_STARTUP",
                    )
                    session.add(new_item)
                    session.commit()
                logger.info(
                    "Synced env-based %s config into DB so admin UI matches runtime",
                    key,
                )
            except Exception:
                logger.exception("Failed to sync env config for %s into DB; runtime still uses env values", key)


provider_manager = PlatformProviderManager()
