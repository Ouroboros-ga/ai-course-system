"""P1-8 验收测试：digital_human_provider.py 实现 DhLiveMiniProvider

验证约束：
- DhLiveMiniProvider 必须是真实 Provider 实现（不再是占位 stub 直接 reject）
- 引擎未配置时返回 DEPENDENCY_UNAVAILABLE（不伪装成功）
- 引擎可达且返回正确结果时，prepare_avatar 返回 AvatarPreparationResult
- health_check 在严格模式下：引擎可达但无实际测试报告时 healthy=False
- health_check 在非严格模式下：引擎可达即 healthy=True
- HTTP Worker 模式：通过 httpx 调用 Worker，失败降级
- 子进程模式：通过 subprocess 调用引擎二进制，失败降级

约束来源：
- Hard Constraints: "Digital human service must implement DhLiveMiniProvider (not fake provider)"
- Hard Constraints: "Digital human effects and frame rates must be based on actual test reports"
- Hard Constraints: "Avatar assets must be preprocessed by an independent Windows worker"
- Lessons Learned: "Fake digital human providers (e.g., fake) prevent proper service integration"
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services.digital_human_provider import (
    AvatarPreparationRequest,
    DhLiveMiniProvider,
    DigitalHumanPlaybackRequest,
)


def _make_prepare_request() -> AvatarPreparationRequest:
    return AvatarPreparationRequest(
        avatar_id="av_001",
        owner_user_id=42,
        portrait_video_object_key="avatars/u_42/source/portrait.mp4",
        voice_sample_object_key="avatars/u_42/source/voice.wav",
        provider_key="dh_live_mini",
        provider_version="dh-live-mini-v1.0",
        consent_text="I authorize",
        idempotency_key="idem_001",
    )


def _make_playback_request() -> DigitalHumanPlaybackRequest:
    return DigitalHumanPlaybackRequest(
        avatar_id="av_001",
        asset_package_id="aap_engine_001",
        audio_object_key="media/c_1/release_001/audio.mp3",
        course_id=1,
        media_release_id="mr_001",
        recommended_quality="auto",
    )


class TestEngineAvailability:
    """测试1: 引擎可达性检查"""

    def test_unconfigured_engine_returns_unavailable(self) -> None:
        """DHLIVE_ENGINE_BINARY 与 DHLIVE_WORKER_PORT 均未配置时返回不可用"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_port=0,
            strict_report=False,
        )
        available, reason = provider._engine_available()
        assert available is False
        assert "not configured" in reason

    def test_missing_binary_returns_unavailable(self, tmp_path) -> None:
        """引擎二进制路径不存在时返回不可用"""
        missing_binary = str(tmp_path / "nonexistent_dhlive")
        provider = DhLiveMiniProvider(
            engine_binary=missing_binary,
            worker_port=0,
            strict_report=False,
        )
        available, reason = provider._engine_available()
        assert available is False
        assert "not found" in reason

    def test_worker_health_200_returns_available(self) -> None:
        """Worker 健康检查返回 200 时可用"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=False,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            available, reason = provider._engine_available()
        assert available is True
        assert "worker healthy" in reason

    def test_worker_http_error_returns_unavailable(self) -> None:
        """Worker HTTP 错误时返回不可用"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9999,
            strict_report=False,
        )
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.side_effect = httpx.ConnectError("connection refused")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            available, reason = provider._engine_available()
        assert available is False
        assert "worker probe failed" in reason


class TestPrepareAvatarUnconfigured:
    """测试2: 引擎未配置时 prepare_avatar 返回 DEPENDENCY_UNAVAILABLE"""

    def test_prepare_avatar_raises_dependency_unavailable_when_unconfigured(self) -> None:
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_port=0,
            strict_report=False,
        )
        with pytest.raises(HTTPException) as exc_info:
            provider.prepare_avatar(_make_prepare_request())
        # reject_dependency_unavailable 抛 503 DEPENDENCY_UNAVAILABLE
        assert exc_info.value.status_code == 503
        detail = exc_info.value.detail
        assert detail["error_code"] == "DEPENDENCY_UNAVAILABLE"
        assert "DH_live_mini 引擎不可用" in detail["message"]


class TestPrepareAvatarWorkerSuccess:
    """测试3: HTTP Worker 模式成功路径"""

    def test_prepare_avatar_returns_result_with_actual_report(self) -> None:
        """Worker 返回正确结果时返回 AvatarPreparationResult 并记录实际测试报告"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=True,
        )

        # 模拟 _engine_available 通过（worker 健康）
        mock_health_response = MagicMock()
        mock_health_response.status_code = 200

        # 模拟 Worker POST /prepare_avatar 返回
        engine_result = {
            "asset_package_id": "aap_engine_001",
            "object_prefix": "avatars/u_42/aap_engine_001/",
            "manifest_object_key": "avatars/u_42/aap_engine_001/manifest.json",
            "asset_sha256": "sha_engine_" + "a" * 56,
            "estimated_download_bytes": 1024000,
            "actual_fps": 30,
            "actual_resolution": "512x512",
            "preprocess_duration_ms": 5500,
        }
        mock_post_response = MagicMock()
        mock_post_response.json.return_value = engine_result
        mock_post_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            # 第一次调用 .get() 是健康检查，第二次 .post() 是实际调用
            mock_client.get.return_value = mock_health_response
            mock_client.post.return_value = mock_post_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = provider.prepare_avatar(_make_prepare_request())

        assert result.asset_package_id == "aap_engine_001"
        assert result.asset_sha256 == engine_result["asset_sha256"]
        assert "browser_realtime" in result.supported_render_modes
        assert "offline_video" in result.supported_render_modes
        assert result.provider_key == "dh_live_mini"
        assert result.provider_version == "dh-live-mini-v1.0"
        # 30fps 不应触发低帧率告警
        assert not any("low frame rate" in w for w in result.warnings)

        # _last_report 已写入（health_check 严格模式据此判定）
        assert provider._last_report is not None
        assert provider._last_report["actual_fps"] == 30
        assert provider._last_report["actual_resolution"] == "512x512"

    def test_prepare_avatar_low_fps_emits_warning(self) -> None:
        """引擎返回低 fps 时 warning 包含 low frame rate"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=True,
        )

        mock_health_response = MagicMock()
        mock_health_response.status_code = 200
        engine_result = {
            "asset_package_id": "aap_low_fps",
            "object_prefix": "avatars/u_42/aap_low_fps/",
            "manifest_object_key": "avatars/u_42/aap_low_fps/manifest.json",
            "asset_sha256": "sha_low",
            "estimated_download_bytes": 1024,
            "actual_fps": 10,
            "actual_resolution": "256x256",
            "preprocess_duration_ms": 1000,
        }
        mock_post_response = MagicMock()
        mock_post_response.json.return_value = engine_result
        mock_post_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_health_response
            mock_client.post.return_value = mock_post_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = provider.prepare_avatar(_make_prepare_request())

        assert any("low frame rate" in w for w in result.warnings)


class TestPrepareAvatarWorkerFailure:
    """测试4: Worker 调用失败降级"""

    def test_prepare_avatar_raises_on_worker_http_error(self) -> None:
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=False,
        )

        mock_health_response = MagicMock()
        mock_health_response.status_code = 200

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_health_response
            mock_client.post.side_effect = httpx.ConnectError("worker down")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                provider.prepare_avatar(_make_prepare_request())

        assert exc_info.value.status_code == 503
        detail = exc_info.value.detail
        assert detail["error_code"] == "DEPENDENCY_UNAVAILABLE"
        # 不伪装成功：错误消息包含原始异常类型
        assert "ConnectError" in detail["message"] or "引擎调用失败" in detail["message"]

    def test_prepare_avatar_raises_on_malformed_result(self) -> None:
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=False,
        )

        mock_health_response = MagicMock()
        mock_health_response.status_code = 200
        # 缺少 asset_package_id 必填字段
        mock_post_response = MagicMock()
        mock_post_response.json.return_value = {"object_prefix": "x"}
        mock_post_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_health_response
            mock_client.post.return_value = mock_post_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                provider.prepare_avatar(_make_prepare_request())

        assert exc_info.value.status_code == 503
        detail = exc_info.value.detail
        assert detail["error_code"] == "DEPENDENCY_UNAVAILABLE"
        assert "格式错误" in detail["message"] or "KeyError" in detail["message"]


class TestGetPlaybackManifest:
    """测试5: get_playback_manifest"""

    def test_get_playback_manifest_unconfigured_raises(self) -> None:
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_port=0,
            strict_report=False,
        )
        with pytest.raises(HTTPException) as exc_info:
            provider.get_playback_manifest(_make_playback_request())
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["error_code"] == "DEPENDENCY_UNAVAILABLE"

    def test_get_playback_manifest_uses_engine_urls_when_provided(self) -> None:
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=False,
        )
        mock_health_response = MagicMock()
        mock_health_response.status_code = 200
        engine_result = {
            "asset_manifest_url": "https://cdn.example.com/manifest.json?sig=engine",
            "audio_url": "https://cdn.example.com/audio.mp3?sig=engine",
            "asset_sha256": "sha_playback",
        }
        mock_post_response = MagicMock()
        mock_post_response.json.return_value = engine_result
        mock_post_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_health_response
            mock_client.post.return_value = mock_post_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            manifest = provider.get_playback_manifest(_make_playback_request())

        assert manifest.provider == "dh_live_mini"
        assert manifest.asset_manifest_url == engine_result["asset_manifest_url"]
        assert manifest.audio_url == engine_result["audio_url"]
        assert manifest.asset_sha256 == "sha_playback"


class TestHealthCheckStrictMode:
    """测试6: 严格模式健康检查"""

    def test_strict_mode_unhealthy_without_report(self) -> None:
        """严格模式：引擎可达但无实际测试报告时 healthy=False"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=True,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            health = provider.health_check()
        assert health.healthy is False
        assert "no actual test report" in health.message
        assert health.provider_key == "dh_live_mini"

    def test_non_strict_mode_healthy_without_report(self) -> None:
        """非严格模式：引擎可达即 healthy=True"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=False,
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            health = provider.health_check()
        assert health.healthy is True

    def test_unconfigured_engine_unhealthy(self) -> None:
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_port=0,
            strict_report=False,
        )
        health = provider.health_check()
        assert health.healthy is False
        assert "engine unavailable" in health.message

    def test_strict_mode_healthy_after_prepare(self) -> None:
        """严格模式：prepare_avatar 成功后 health_check 为 healthy=True"""
        provider = DhLiveMiniProvider(
            engine_binary="",
            worker_host="127.0.0.1",
            worker_port=9876,
            strict_report=True,
        )

        # 完成一次成功 prepare_avatar
        mock_health_response = MagicMock()
        mock_health_response.status_code = 200
        engine_result = {
            "asset_package_id": "aap_2",
            "object_prefix": "x/",
            "manifest_object_key": "x/m.json",
            "asset_sha256": "sha",
            "estimated_download_bytes": 10,
            "actual_fps": 25,
            "actual_resolution": "512x512",
            "preprocess_duration_ms": 1000,
        }
        mock_post_response = MagicMock()
        mock_post_response.json.return_value = engine_result
        mock_post_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_health_response
            mock_client.post.return_value = mock_post_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            provider.prepare_avatar(_make_prepare_request())
            # _last_report 已写入，health_check 应为 healthy
            health = provider.health_check()

        assert health.healthy is True
        assert "fps=25" in health.message


class TestSubprocessEngineMode:
    """测试7: 子进程模式（DHLIVE_ENGINE_BINARY）"""

    def test_subprocess_engine_success(self, tmp_path) -> None:
        """构造一个可执行的 stub 脚本模拟引擎"""
        if os.name == "nt":
            # Windows: 写一个 batch 脚本返回固定 JSON
            stub_path = tmp_path / "stub_engine.bat"
            stub_path.write_text(
                '@echo off\necho {"asset_package_id":"aap_sub","object_prefix":"x/",'
                '"manifest_object_key":"x/m.json","asset_sha256":"sha_sub",'
                '"estimated_download_bytes":100,"actual_fps":24,'
                '"actual_resolution":"512x512","preprocess_duration_ms":2000}\n',
                encoding="utf-8",
            )
        else:
            stub_path = tmp_path / "stub_engine.sh"
            stub_path.write_text(
                '#!/bin/sh\ncat <<EOF\n'
                '{"asset_package_id":"aap_sub","object_prefix":"x/",'
                '"manifest_object_key":"x/m.json","asset_sha256":"sha_sub",'
                '"estimated_download_bytes":100,"actual_fps":24,'
                '"actual_resolution":"512x512","preprocess_duration_ms":2000}\n'
                'EOF\n',
                encoding="utf-8",
            )
            os.chmod(stub_path, 0o755)

        # --version 也需要返回 0 退出码
        if os.name == "nt":
            # 在 batch 脚本里，无论参数都返回 JSON
            pass
        else:
            # shell 脚本同上
            pass

        provider = DhLiveMiniProvider(
            engine_binary=str(stub_path),
            worker_port=0,
            strict_report=False,
        )

        # 注意：subprocess.run 会真实执行 stub 脚本
        result = provider.prepare_avatar(_make_prepare_request())
        assert result.asset_package_id == "aap_sub"
        assert result.asset_sha256 == "sha_sub"
        assert provider._last_report is not None
        assert provider._last_report["actual_fps"] == 24
