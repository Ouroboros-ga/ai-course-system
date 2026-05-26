"""
视频生成服务测试
测试F5视频生成管线的核心功能
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))


class TestDigitalHumanClient:
    """数字人客户端测试"""

    def test_init(self):
        """测试客户端初始化"""
        from app.common.digital_human_client import DigitalHumanClient
        client = DigitalHumanClient()
        assert "localhost:7860" in client.api_url
        assert client.min_resolution == 2
        assert client.steps == 4
        assert client.timeout == 600

    def test_generate_video_file_not_found(self):
        """测试输入文件不存在时抛出异常"""
        from app.common.digital_human_client import DigitalHumanClient, DigitalHumanError
        import asyncio
        client = DigitalHumanClient()

        with pytest.raises(DigitalHumanError, match="音频文件不存在"):
            asyncio.get_event_loop().run_until_complete(
                client.generate_video(
                    audio_path="/nonexistent/audio.wav",
                    video_path="/nonexistent/video.mp4",
                )
            )

    def test_check_health_unavailable(self):
        """测试服务不可用"""
        from app.common.digital_human_client import DigitalHumanClient
        import asyncio
        client = DigitalHumanClient()
        client.api_url = "http://localhost:99999"

        result = asyncio.get_event_loop().run_until_complete(client.check_health())
        assert result is False


class TestVideoGenerationModel:
    """视频生成数据模型测试"""

    def test_generation_status_enum(self):
        """测试生成状态枚举"""
        from app.models.video_generation_model import GenerationStatus
        assert GenerationStatus.PENDING.value == "pending"
        assert GenerationStatus.TTS_SYNTHESIZING.value == "tts_synthesizing"
        assert GenerationStatus.TTS_COMPLETED.value == "tts_completed"
        assert GenerationStatus.DH_GENERATING.value == "dh_generating"
        assert GenerationStatus.COMPLETED.value == "completed"
        assert GenerationStatus.FAILED.value == "failed"

    def test_task_creation(self):
        """测试任务模型创建"""
        from app.models.video_generation_model import VideoGenerationTask, GenerationStatus
        task = VideoGenerationTask(
            course_id=1,
            script_id=1,
            node_id=1,
            status=GenerationStatus.PENDING,
        )
        assert task.course_id == 1
        assert task.status == GenerationStatus.PENDING
        assert task.retry_count == 0
        assert task.audio_duration == 0.0


class TestVideoGenerationService:
    """视频生成服务测试"""

    def test_resolve_face_video_no_video(self):
        """测试没有人脸视频时抛出异常"""
        from app.services.video_generation_service import VideoGenerationService
        from app.models.asset_model import AssetType
        import asyncio

        service = VideoGenerationService()
        session = MagicMock()
        mock_node = MagicMock()
        mock_node.script_id = 1

        mock_script = MagicMock()
        mock_script.course_id = 1

        session.get.return_value = mock_script
        session.exec.return_value.first.return_value = None

        with pytest.raises(ValueError, match="没有人脸视频素材"):
            asyncio.get_event_loop().run_until_complete(
                service._resolve_face_video(None, mock_node, session)
            )

    def test_resolve_face_video_default(self):
        """测试解析默认人脸视频"""
        from app.services.video_generation_service import VideoGenerationService
        from app.models.asset_model import AssetType
        import asyncio

        service = VideoGenerationService()
        session = MagicMock()
        mock_node = MagicMock()
        mock_node.script_id = 1

        mock_script = MagicMock()
        mock_script.course_id = 1

        # 创建临时视频文件
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            temp_video = f.name
            f.write(b"fake video data")

        try:
            mock_asset = MagicMock()
            mock_asset.asset_type = AssetType.FACE_VIDEO
            mock_asset.file_path = temp_video

            session.get.return_value = mock_script
            session.exec.return_value.first.return_value = mock_asset

            result = asyncio.get_event_loop().run_until_complete(
                service._resolve_face_video(None, mock_node, session)
            )
            assert result == temp_video
        finally:
            os.unlink(temp_video)


class TestVideoGenerationAPIRoutes:
    """API路由注册测试"""

    def test_routes_registered(self):
        """测试视频生成路由已注册"""
        from app.main import app
        routes = [r.path for r in app.routes if hasattr(r, 'path')]
        vg_routes = [r for r in routes if 'video-generation' in r]

        assert "/api/v1/video-generation/course/{course_id}/generate" in vg_routes
        assert "/api/v1/video-generation/node/{node_id}/generate" in vg_routes
        assert "/api/v1/video-generation/task/{task_id}" in vg_routes
        assert "/api/v1/video-generation/course/{course_id}/tasks" in vg_routes
        assert "/api/v1/video-generation/health" in vg_routes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
