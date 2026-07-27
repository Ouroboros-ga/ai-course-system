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
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import reject_dependency_unavailable
from app.services.object_storage import get_object_storage

logger = logging.getLogger(__name__)


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
# DH_live_mini 真实 Provider（M4 实现）
# ---------------------------------------------------------------------------


class DhLiveMiniProvider(DigitalHumanProvider):
    """DH_live_mini Provider（M4 真实实现）

    约束来源：
    - Hard Constraints: "Digital human service must implement DhLiveMiniProvider (not fake provider)"
    - Hard Constraints: "Avatar assets must be preprocessed by an independent Windows worker"
    - Hard Constraints: "Digital human effects and frame rates must be based on actual test reports"
    - Lessons Learned: "DH_live's offline video synthesis is more complete on Windows than Linux"

    设计：
    - 通过 ``DHLIVE_ENGINE_BINARY``（子进程）或 ``DHLIVE_WORKER_PORT``（HTTP Worker）调用真实引擎
    - 两者均未配置时，prepare_avatar/get_playback_manifest 返回 DEPENDENCY_UNAVAILABLE
    - health_check 探测引擎可执行文件是否存在或 Worker 是否响应；无实际测试报告时强制 healthy=False
    - 自动化测试不调用真实引擎，必须通过 monkey-patch 或 ``DHLIVE_ENGINE_BINARY`` 注入测试桩
    - 严格模式（``DHLIVE_STRICT_REPORT=True``）：无实际测试报告时不允许返回 healthy=True
    """

    provider_key = "dh_live_mini"
    provider_version = "dh-live-mini-v1.0"

    def __init__(self, *, engine_binary: str | None = None,
                 worker_host: str | None = None,
                 worker_port: int | None = None,
                 worker_timeout_s: int | None = None,
                 strict_report: bool | None = None) -> None:
        # 显式参数优先；缺失时从 settings 读取，避免测试需要 patch 全局配置
        self._engine_binary = engine_binary if engine_binary is not None else getattr(
            settings, "DHLIVE_ENGINE_BINARY", ""
        )
        self._worker_host = worker_host if worker_host is not None else getattr(
            settings, "DHLIVE_WORKER_HOST", "127.0.0.1"
        )
        self._worker_port = worker_port if worker_port is not None else int(
            getattr(settings, "DHLIVE_WORKER_PORT", 0)
        )
        self._worker_timeout_s = worker_timeout_s if worker_timeout_s is not None else int(
            getattr(settings, "DHLIVE_WORKER_TIMEOUT_S", 120)
        )
        self._strict_report = bool(strict_report if strict_report is not None else getattr(
            settings, "DHLIVE_STRICT_REPORT", True
        ))
        # 缓存最近一次实际测试报告（fps、resolution、duration_ms 等）
        # 由 prepare_avatar 写入；health_check 据此判断"是否有实际测试报告"
        self._last_report: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 引擎可达性检查
    # ------------------------------------------------------------------

    def _engine_available(self) -> tuple[bool, str]:
        """探测 DH_live 引擎是否可用。

        优先级：
        1. ``DHLIVE_ENGINE_BINARY``：检查可执行文件存在并可执行 ``--version``
        2. ``DHLIVE_WORKER_PORT``：HTTP GET ``/health`` 探测 Worker

        返回 (available, reason)。reason 用于审计与日志。
        """
        # 1. 子进程模式
        if self._engine_binary:
            if not os.path.isfile(self._engine_binary):
                return False, f"engine binary not found: {self._engine_binary}"
            if not shutil.which(self._engine_binary) and not os.access(self._engine_binary, os.X_OK):
                return False, f"engine binary not executable: {self._engine_binary}"
            # 实际执行 --version 验证引擎可调用；失败即不可用
            try:
                proc = subprocess.run(
                    [self._engine_binary, "--version"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if proc.returncode != 0:
                    return False, f"engine --version exit={proc.returncode}"
                return True, "engine binary available"
            except (subprocess.TimeoutExpired, OSError) as exc:
                return False, f"engine probe failed: {type(exc).__name__}: {exc}"

        # 2. HTTP Worker 模式
        if self._worker_port and self._worker_port > 0:
            url = f"http://{self._worker_host}:{self._worker_port}/health"
            try:
                with httpx.Client(timeout=5) as client:
                    resp = client.get(url)
                if resp.status_code == 200:
                    return True, f"worker healthy at {url}"
                return False, f"worker health status={resp.status_code}"
            except (httpx.HTTPError, OSError) as exc:
                return False, f"worker probe failed: {type(exc).__name__}: {exc}"

        # 两者均未配置：引擎不可用（非异常状态，是未配置）
        return False, "DH_live_mini engine not configured (DHLIVE_ENGINE_BINARY/DHLIVE_WORKER_PORT empty)"

    # ------------------------------------------------------------------
    # 子进程模式：调用真实引擎
    # ------------------------------------------------------------------

    def _invoke_engine_subprocess(
        self,
        *,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """通过子进程调用 DH_live 引擎。

        约定调用协议：
        - 引擎接收 ``--action <name> --input <json_path>`` 参数
        - 输出 JSON 到 stdout；非零退出码表示失败
        - payload 中的 ``portrait_video_object_key`` 由本 Provider 先解析为本地路径
          （或由引擎直接通过 object_key 拉取，取决于部署形态）

        Returns:
            引擎返回的 JSON dict

        Raises:
            RuntimeError: 引擎调用失败或返回非 JSON
        """
        if not self._engine_binary:
            raise RuntimeError("DHLIVE_ENGINE_BINARY not configured")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as input_file:
            json.dump(payload, input_file, ensure_ascii=False)
            input_path = input_file.name

        try:
            cmd = [self._engine_binary, "--action", action, "--input", input_path]
            logger.info("Invoking DH_live engine: action=%s cmd=%s", action, cmd)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self._worker_timeout_s,
                check=False,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace")[:2000]
                raise RuntimeError(
                    f"DH_live engine exit={proc.returncode} stderr={stderr}"
                )
            try:
                result = json.loads(proc.stdout.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"DH_live engine returned non-JSON: {exc}") from exc
            return result
        finally:
            try:
                os.unlink(input_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # HTTP Worker 模式
    # ------------------------------------------------------------------

    def _invoke_worker_http(
        self,
        *,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """通过 HTTP 调用独立 Windows Worker。

        Worker 路由约定：``POST /<action>``，body 为 JSON，响应为 JSON。
        """
        if not (self._worker_port and self._worker_port > 0):
            raise RuntimeError("DHLIVE_WORKER_PORT not configured")

        url = f"http://{self._worker_host}:{self._worker_port}/{action}"
        with httpx.Client(timeout=self._worker_timeout_s) as client:
            resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def _invoke_engine(
        self,
        *,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """统一入口：优先 HTTP Worker，其次子进程；两者均未配置抛 RuntimeError。"""
        if self._worker_port and self._worker_port > 0:
            return self._invoke_worker_http(action=action, payload=payload)
        if self._engine_binary:
            return self._invoke_engine_subprocess(action=action, payload=payload)
        raise RuntimeError(
            "DH_live_mini engine not configured: set DHLIVE_ENGINE_BINARY or DHLIVE_WORKER_PORT"
        )

    # ------------------------------------------------------------------
    # DigitalHumanProvider 实现
    # ------------------------------------------------------------------

    def prepare_avatar(self, request: AvatarPreparationRequest) -> AvatarPreparationResult:
        """调用真实 DH_live 引擎预处理数字人资产。

        失败语义：
        - 引擎未配置/不可用 → reject_dependency_unavailable（503）
        - 引擎调用失败 → reject_dependency_unavailable（503），不伪装成功
        - 成功 → 写入实际测试报告（fps/resolution/duration），更新 _last_report
        """
        available, reason = self._engine_available()
        if not available:
            logger.warning("DhLiveMiniProvider.prepare_avatar skipped: %s", reason)
            reject_dependency_unavailable(
                f"DH_live_mini 引擎不可用：{reason}；请配置 DHLIVE_ENGINE_BINARY 或 DHLIVE_WORKER_PORT"
            )

        # 构造引擎调用 payload；object_key 不暴露本地路径，由引擎/Worker 自行拉取
        payload = {
            "avatar_id": request.avatar_id,
            "owner_user_id": request.owner_user_id,
            "portrait_video_object_key": request.portrait_video_object_key,
            "voice_sample_object_key": request.voice_sample_object_key or "",
            "provider_key": self.provider_key,
            "provider_version": self.provider_version,
            "consent_text": request.consent_text,
            "idempotency_key": request.idempotency_key or request.input_hash(),
            "default_fps": int(getattr(settings, "DHLIVE_DEFAULT_FPS", 25)),
            "default_resolution": getattr(settings, "DHLIVE_DEFAULT_RESOLUTION", "512x512"),
        }

        try:
            result = self._invoke_engine(action="prepare_avatar", payload=payload)
        except (RuntimeError, httpx.HTTPError, OSError) as exc:
            logger.exception("DH_live_mini prepare_avatar failed")
            reject_dependency_unavailable(
                f"DH_live_mini 引擎调用失败：{type(exc).__name__}: {exc}"
            )
            return  # reject_dependency_unavailable 已 raise，此处仅为类型提示

        # 解析引擎返回结果；必填字段缺失视为失败
        try:
            asset_package_id = result["asset_package_id"]
            object_prefix = result["object_prefix"]
            manifest_object_key = result["manifest_object_key"]
            asset_sha = result["asset_sha256"]
            estimated_bytes = int(result.get("estimated_download_bytes", 0))
            fps = int(result.get("actual_fps", payload["default_fps"]))
            resolution = result.get("actual_resolution", payload["default_resolution"])
            duration_ms = int(result.get("preprocess_duration_ms", 0))
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("DH_live_mini engine returned malformed result: %s", result)
            reject_dependency_unavailable(
                f"DH_live_mini 引擎返回结果格式错误：{type(exc).__name__}: {exc}"
            )
            return

        # 写入实际测试报告；health_check 据此判断"已基于实际测试"
        self._last_report = {
            "asset_package_id": asset_package_id,
            "actual_fps": fps,
            "actual_resolution": resolution,
            "preprocess_duration_ms": duration_ms,
            "engine_reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        warnings: list[str] = []
        if fps < 15:
            warnings.append(f"low frame rate: {fps}fps < 15fps baseline")
        if duration_ms == 0:
            warnings.append("preprocess_duration_ms not reported by engine")

        return AvatarPreparationResult(
            asset_package_id=asset_package_id,
            object_prefix=object_prefix,
            manifest_object_key=manifest_object_key,
            asset_sha256=asset_sha,
            estimated_download_bytes=estimated_bytes,
            supported_render_modes=["browser_realtime", "offline_video"],
            quality_profiles=["auto", "low_resource", "compatibility"],
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            warnings=warnings,
        )

    def get_playback_manifest(self, request: DigitalHumanPlaybackRequest) -> DigitalHumanPlaybackManifest:
        """生成基于真实引擎资产的播放清单。

        失败语义：
        - 引擎不可用 → reject_dependency_unavailable（503）
        - 引擎调用失败 → reject_dependency_unavailable（503）
        - 成功 → 返回基于真实资产签名 URL 的播放清单
        """
        available, reason = self._engine_available()
        if not available:
            logger.warning("DhLiveMiniProvider.get_playback_manifest skipped: %s", reason)
            reject_dependency_unavailable(
                f"DH_live_mini 引擎不可用：{reason}；请配置 DHLIVE_ENGINE_BINARY 或 DHLIVE_WORKER_PORT"
            )

        payload = {
            "avatar_id": request.avatar_id,
            "asset_package_id": request.asset_package_id,
            "audio_object_key": request.audio_object_key,
            "course_id": request.course_id,
            "media_release_id": request.media_release_id,
            "recommended_quality": request.recommended_quality,
        }

        try:
            result = self._invoke_engine(action="playback_manifest", payload=payload)
        except (RuntimeError, httpx.HTTPError, OSError) as exc:
            logger.exception("DH_live_mini get_playback_manifest failed")
            reject_dependency_unavailable(
                f"DH_live_mini 引擎调用失败：{type(exc).__name__}: {exc}"
            )
            return

        # 引擎返回 asset_manifest_url + audio_url 时直接使用；否则回退到本地对象存储签名
        asset_manifest_url = result.get("asset_manifest_url") or self._sign_read_url_for_prefix(
            request.asset_package_id, request.course_id, suffix="manifest.json"
        )
        audio_url = result.get("audio_url") or get_object_storage().sign_read_url(
            request.audio_object_key,
            scope={"course_id": request.course_id, "purpose": "dh_playback"},
        )
        asset_sha = result.get("asset_sha256", "")

        return DigitalHumanPlaybackManifest(
            provider=self.provider_key,
            provider_version=self.provider_version,
            avatar_version=request.asset_package_id,
            asset_manifest_url=asset_manifest_url,
            audio_url=audio_url,
            render_mode="browser_realtime",
            recommended_quality=request.recommended_quality,
            fallback_supported=True,
            asset_sha256=asset_sha,
        )

    def _sign_read_url_for_prefix(
        self, asset_package_id: str, course_id: int, *, suffix: str
    ) -> str:
        """为指定 asset_package_id 下的子对象签发读取 URL。

        注意：FakeDigitalHumanProvider 使用 ``avatars/u_*/...`` 通配前缀，
        但真实 Provider 必须基于具体 object_key 签名；调用方需先查询资产清单
        获取实际 object_key。这里回退到 manifest 路径以避免通配签名。
        """
        # 真实场景下应通过 engine 查询 asset_package 的 manifest object_key；
        # 此处为防御性回退，避免通配签名破坏权限边界
        fallback_key = f"avatars/_packages/{asset_package_id}/{suffix}"
        return get_object_storage().sign_read_url(
            fallback_key,
            scope={"course_id": course_id, "purpose": "dh_playback"},
        )

    def health_check(self) -> ProviderHealth:
        """探测 DH_live 引擎健康状态。

        严格模式（``DHLIVE_STRICT_REPORT=True``）：
        - 即使引擎可达，若无实际测试报告（_last_report 为空），仍返回 healthy=False
        - 约束："Digital human effects and frame rates must be based on actual test reports"
        """
        available, reason = self._engine_available()
        if not available:
            return ProviderHealth(
                healthy=False,
                provider_key=self.provider_key,
                provider_version=self.provider_version,
                message=f"engine unavailable: {reason}",
            )

        # 引擎可达但无实际测试报告：严格模式下视为不健康
        if self._strict_report and self._last_report is None:
            return ProviderHealth(
                healthy=False,
                provider_key=self.provider_key,
                provider_version=self.provider_version,
                message="engine available but no actual test report; run prepare_avatar first",
            )

        report_msg = ""
        if self._last_report:
            report_msg = (
                f" (last_report: fps={self._last_report.get('actual_fps')}, "
                f"resolution={self._last_report.get('actual_resolution')})"
            )

        return ProviderHealth(
            healthy=True,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            message=f"engine available: {reason}{report_msg}",
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
