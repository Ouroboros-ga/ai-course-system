"""阶段8 DigitalHuman Provider 抽象与实现

实现 `DigitalHumanProvider` 抽象：仅描述"如何让一个引擎消费已发布音频"，
不负责 TTS，不直接改时间轴，也不接触课程权限。

设计要点：
- `prepare_avatar(request)` -> `AvatarPreparationResult`：资产预处理（独立 Worker 调用）
- `get_playback_manifest(request)` -> `DigitalHumanPlaybackManifest`：播放清单
- `health_check()` -> `ProviderHealth`：健康状态
- 首版实现：FakeDigitalHumanProvider（自动化测试）、DuixAvatarProvider 适配现有
- 替换引擎时只新增 Provider，课程核心数据不变
"""
from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.exceptions import reject_dependency_unavailable
from app.services.object_storage import get_object_storage


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


@dataclass
class AvatarPreparationRequest:
    """数字人资产预处理请求"""
    avatar_id: str
    owner_user_id: int
    portrait_video_object_key: str
    voice_sample_object_key: Optional[str] = None
    provider_key: str = "fake"
    provider_version: str = ""
    consent_text: str = ""
    idempotency_key: str = ""

    def input_hash(self) -> str:
        payload = "|".join([
            self.avatar_id,
            self.portrait_video_object_key,
            self.voice_sample_object_key or "",
            self.provider_key,
            self.provider_version,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class AvatarPreparationResult:
    """数字人资产预处理结果"""
    asset_package_id: str
    object_prefix: str
    manifest_object_key: str
    asset_sha256: str
    estimated_download_bytes: int
    supported_render_modes: list[str] = field(default_factory=lambda: ["browser_realtime"])
    quality_profiles: list[str] = field(default_factory=lambda: ["auto", "low_resource", "compatibility"])
    provider_key: str = ""
    provider_version: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class DigitalHumanPlaybackRequest:
    """数字人播放清单请求"""
    avatar_id: str
    asset_package_id: str
    audio_object_key: str
    course_id: int
    media_release_id: str
    recommended_quality: str = "auto"


@dataclass
class DigitalHumanPlaybackManifest:
    """数字人播放清单

    前端 `DigitalHumanRendererAdapter` 通过本清单初始化引擎。
    """
    provider: str
    provider_version: str
    avatar_version: str
    asset_manifest_url: str
    audio_url: str
    render_mode: str = "browser_realtime"
    recommended_quality: str = "auto"
    fallback_supported: bool = True
    asset_sha256: str = ""


@dataclass
class ProviderHealth:
    """Provider 健康状态"""
    healthy: bool
    provider_key: str = ""
    provider_version: str = ""
    message: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# 抽象接口
# ---------------------------------------------------------------------------


class DigitalHumanProvider(ABC):
    """数字人 Provider 抽象

    - 不负责 TTS，不直接改时间轴，也不接触课程权限
    - 只描述"如何让一个引擎消费已发布音频"
    - 替换引擎时只新增 Provider 和前端适配器
    """

    provider_key: str = "abstract"
    provider_version: str = "0.0.0"

    @abstractmethod
    def prepare_avatar(self, request: AvatarPreparationRequest) -> AvatarPreparationResult:
        """资产预处理（独立 Worker 调用，不在主 Web 请求里）"""

    @abstractmethod
    def get_playback_manifest(self, request: DigitalHumanPlaybackRequest) -> DigitalHumanPlaybackManifest:
        """生成播放清单；前端按清单初始化引擎"""

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """健康检查"""


# ---------------------------------------------------------------------------
# Fake Provider（用于自动化测试与端到端演示）
# ---------------------------------------------------------------------------


class FakeDigitalHumanProvider(DigitalHumanProvider):
    """假数字人 Provider

    - 不调用真实引擎，自动化测试与离线演示使用
    - 资产预处理"产物"是包含元数据的占位 manifest
    - 播放清单指向占位资产 URL，前端 FakeRenderer 据此驱动
    - 任何场景下都不应被当作"数字人已生成"的真实证据
    """

    provider_key = "fake"
    provider_version = "fake-dh-v1.0"

    def prepare_avatar(self, request: AvatarPreparationRequest) -> AvatarPreparationResult:
        asset_package_id = "aap_" + uuid.uuid4().hex
        object_prefix = f"avatars/u_{request.owner_user_id}/{asset_package_id}/"

        # 生成占位 manifest
        manifest = {
            "asset_package_id": asset_package_id,
            "avatar_id": request.avatar_id,
            "provider": self.provider_key,
            "provider_version": self.provider_version,
            "object_prefix": object_prefix,
            "render_modes": ["browser_realtime"],
            "quality_profiles": ["auto", "low_resource", "compatibility"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": "fake digital human manifest; not a real engine output",
        }
        import json
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

        manifest_object_key = f"{object_prefix}manifest.json"
        storage = get_object_storage()
        asset_sha = storage.put(manifest_object_key, manifest_bytes, mime_type="application/json")

        # 同时登记一个占位"模型"对象，模拟真实引擎产物
        model_object_key = f"{object_prefix}model.fake"
        model_bytes = b"FAKE_DH_MODEL_V1\n" + asset_package_id.encode()
        storage.put(model_object_key, model_bytes, mime_type="application/octet-stream")

        return AvatarPreparationResult(
            asset_package_id=asset_package_id,
            object_prefix=object_prefix,
            manifest_object_key=manifest_object_key,
            asset_sha256=asset_sha,
            estimated_download_bytes=len(manifest_bytes) + len(model_bytes),
            supported_render_modes=["browser_realtime"],
            quality_profiles=["auto", "low_resource", "compatibility"],
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            warnings=["fake_dh: 生成的是占位资产，非真实数字人引擎输出"],
        )

    def get_playback_manifest(self, request: DigitalHumanPlaybackRequest) -> DigitalHumanPlaybackManifest:
        storage = get_object_storage()
        asset_manifest_url = storage.sign_read_url(
            f"avatars/u_*/{request.asset_package_id}/manifest.json",
            scope={"course_id": request.course_id, "purpose": "dh_playback"},
        )
        audio_url = storage.sign_read_url(
            request.audio_object_key,
            scope={"course_id": request.course_id, "purpose": "dh_playback"},
        )
        return DigitalHumanPlaybackManifest(
            provider=self.provider_key,
            provider_version=self.provider_version,
            avatar_version=request.asset_package_id,
            asset_manifest_url=asset_manifest_url,
            audio_url=audio_url,
            render_mode="browser_realtime",
            recommended_quality=request.recommended_quality,
            fallback_supported=True,
            asset_sha256="",
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=True,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            message="fake provider is always healthy",
        )


# ---------------------------------------------------------------------------
# DH_live 占位（M4 接入真实引擎）
# ---------------------------------------------------------------------------


class DhLiveMiniProvider(DigitalHumanProvider):
    """DH_live_mini Provider（M4 实现）

    首版仅为占位：调用时直接返回 DEPENDENCY_UNAVAILABLE，
    避免在 M1 阶段误用真实数字人引擎。
    """

    provider_key = "dh_live_mini"
    provider_version = "dh-live-mini-v0.1"

    def prepare_avatar(self, request: AvatarPreparationRequest) -> AvatarPreparationResult:
        reject_dependency_unavailable(
            "DH_live_mini 尚未接入（M4 任务），请使用 FakeDigitalHumanProvider 完成端到端测试"
        )

    def get_playback_manifest(self, request: DigitalHumanPlaybackRequest) -> DigitalHumanPlaybackManifest:
        reject_dependency_unavailable(
            "DH_live_mini 尚未接入（M4 任务），请使用 FakeDigitalHumanProvider 完成端到端测试"
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=False,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            message="DH_live_mini not implemented yet (M4)",
        )


# ---------------------------------------------------------------------------
# Provider 注册表
# ---------------------------------------------------------------------------


_DH_PROVIDER_REGISTRY: dict[str, DigitalHumanProvider] = {
    "fake": FakeDigitalHumanProvider(),
    "dh_live_mini": DhLiveMiniProvider(),
}


def get_digital_human_provider(provider_key: Optional[str] = None) -> DigitalHumanProvider:
    """获取数字人 Provider

    首版默认返回 FakeDigitalHumanProvider，确保自动化测试与离线演示不依赖外部服务。
    M4 接入 DH_live 后，可通过 settings.STAGE8_DH_PROVIDER 切换。
    """
    if provider_key is None:
        from app.core.config import settings
        provider_key = getattr(settings, "STAGE8_DH_PROVIDER", "fake") or "fake"
    provider = _DH_PROVIDER_REGISTRY.get(provider_key.lower())
    if provider is None:
        return _DH_PROVIDER_REGISTRY["fake"]
    return provider


def register_digital_human_provider(provider_key: str, provider: DigitalHumanProvider) -> None:
    """注册自定义数字人 Provider（测试辅助）"""
    _DH_PROVIDER_REGISTRY[provider_key.lower()] = provider


def reset_dh_registry_for_tests() -> None:
    """测试辅助：重置注册表为默认状态"""
    _DH_PROVIDER_REGISTRY.clear()
    _DH_PROVIDER_REGISTRY.update({
        "fake": FakeDigitalHumanProvider(),
        "dh_live_mini": DhLiveMiniProvider(),
    })
