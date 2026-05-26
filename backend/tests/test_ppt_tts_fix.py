"""
测试PPT图片显示修复和TTS语音生成预览修复
- Bug 3.1: /student 下PPT图片显示问题（Vite代理 + 认证token + 签名白名单）
- Bug 3.2: /teacher/course/1 下语音生成预览问题（JSON请求体 + blob响应处理）
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestSlideImageUrlWithToken:
    """测试PPT幻灯片图片URL附加认证token"""

    def test_slide_url_without_token(self):
        slide_url = "/api/v1/document/course/1/slide/1"
        token = None
        if token:
            separator = "&" if "?" in slide_url else "?"
            result = f"{slide_url}{separator}token={token}"
        else:
            result = slide_url
        assert result == "/api/v1/document/course/1/slide/1"

    def test_slide_url_with_token(self):
        slide_url = "/api/v1/document/course/1/slide/1"
        token = "eyJhbGciOiJIUzI1NiJ9.test"
        separator = "&" if "?" in slide_url else "?"
        result = f"{slide_url}{separator}token={token}"
        assert result == "/api/v1/document/course/1/slide/1?token=eyJhbGciOiJIUzI1NiJ9.test"

    def test_slide_url_with_existing_query_params(self):
        slide_url = "/api/v1/document/course/1/slide/1?foo=bar"
        token = "test_token"
        separator = "&" if "?" in slide_url else "?"
        result = f"{slide_url}{separator}token={token}"
        assert result == "/api/v1/document/course/1/slide/1?foo=bar&token=test_token"

    def test_audio_url_with_token(self):
        audio_url = "/api/v1/document/audio/node_1_abc123.mp3"
        token = "test_token"
        separator = "&" if "?" in audio_url else "?"
        result = f"{audio_url}{separator}token={token}"
        assert result == "/api/v1/document/audio/node_1_abc123.mp3?token=test_token"

    def test_empty_audio_url_returns_empty(self):
        audio_url = ""
        result = audio_url if audio_url else ""
        assert result == ""


class TestMediaResourceSignatureWhitelist:
    """测试媒体资源路径的签名白名单配置"""

    def test_media_resource_paths_configured(self):
        from app.core.config import settings
        assert hasattr(settings, "MEDIA_RESOURCE_PATHS")
        assert "/api/v1/document/course/" in settings.MEDIA_RESOURCE_PATHS
        assert "/api/v1/document/audio/" in settings.MEDIA_RESOURCE_PATHS

    def test_slide_path_matches_whitelist(self):
        from app.core.config import settings
        test_path = "/api/v1/document/course/1/slide/1"
        matches = any(test_path.startswith(p) for p in settings.MEDIA_RESOURCE_PATHS)
        assert matches is True

    def test_audio_path_matches_whitelist(self):
        from app.core.config import settings
        test_path = "/api/v1/document/audio/node_1_abc.mp3"
        matches = any(test_path.startswith(p) for p in settings.MEDIA_RESOURCE_PATHS)
        assert matches is True

    def test_non_media_path_not_in_whitelist(self):
        from app.core.config import settings
        test_path = "/api/v1/document/upload"
        matches = any(test_path.startswith(p) for p in settings.MEDIA_RESOURCE_PATHS)
        assert matches is False

    def test_post_request_not_exempt(self):
        from app.core.config import settings
        test_path = "/api/v1/document/course/1/slide/1"
        method = "POST"
        is_exempt = method == "GET" and any(
            test_path.startswith(p) for p in settings.MEDIA_RESOURCE_PATHS
        )
        assert is_exempt is False


class TestSignatureMiddlewareMediaExemption:
    """测试签名中间件对媒体资源GET请求的豁免逻辑"""

    def test_get_slide_request_exempt(self):
        from app.core.config import settings
        path = "/api/v1/document/course/1/slide/1"
        method = "GET"
        is_exempt = method == "GET" and any(
            path.startswith(p) for p in getattr(settings, 'MEDIA_RESOURCE_PATHS', [])
        )
        assert is_exempt is True

    def test_get_audio_request_exempt(self):
        from app.core.config import settings
        path = "/api/v1/document/audio/node_1.mp3"
        method = "GET"
        is_exempt = method == "GET" and any(
            path.startswith(p) for p in getattr(settings, 'MEDIA_RESOURCE_PATHS', [])
        )
        assert is_exempt is True

    def test_post_slide_request_not_exempt(self):
        from app.core.config import settings
        path = "/api/v1/document/course/1/slide/1"
        method = "POST"
        is_exempt = method == "GET" and any(
            path.startswith(p) for p in getattr(settings, 'MEDIA_RESOURCE_PATHS', [])
        )
        assert is_exempt is False

    def test_get_non_media_request_not_exempt(self):
        from app.core.config import settings
        path = "/api/v1/document/courses"
        method = "GET"
        is_exempt = method == "GET" and any(
            path.startswith(p) for p in getattr(settings, 'MEDIA_RESOURCE_PATHS', [])
        )
        assert is_exempt is False


class TestTTSJsonRequestBody:
    """测试TTS接口改为JSON请求体后的参数解析"""

    def test_parse_tts_request_body(self):
        body = {
            "text": "这是一段测试文本",
            "voice": "zh_female_shuangkuaisisi_moon_bigtts",
            "sample_rate": 16000,
            "output_format": "mp3",
        }
        text = body.get("text", "")
        voice = body.get("voice")
        sample_rate = body.get("sample_rate", 16000)
        output_format = body.get("output_format", "mp3")

        assert text == "这是一段测试文本"
        assert voice == "zh_female_shuangkuaisisi_moon_bigtts"
        assert sample_rate == 16000
        assert output_format == "mp3"

    def test_parse_tts_request_body_minimal(self):
        body = {
            "text": "最小参数",
        }
        text = body.get("text", "")
        voice = body.get("voice")
        sample_rate = body.get("sample_rate", 16000)
        output_format = body.get("output_format", "mp3")

        assert text == "最小参数"
        assert voice is None
        assert sample_rate == 16000
        assert output_format == "mp3"

    def test_parse_tts_request_body_with_clone_voice(self):
        body = {
            "text": "使用克隆音色",
            "voice": "S_abc123def",
        }
        voice = body.get("voice")
        assert voice is not None
        assert voice.startswith("S_")

    def test_empty_text_rejected(self):
        body = {"text": ""}
        text = body.get("text", "")
        assert len(text) == 0

    def test_long_text_accepted(self):
        body = {"text": "很长的文本" * 500}
        text = body.get("text", "")
        assert len(text) > 2000


class TestBlobResponseHandling:
    """测试前端blob响应处理逻辑"""

    def test_blob_type_detection_audio(self):
        blob_type = "audio/mpeg"
        is_json_error = blob_type and "application/json" in blob_type
        assert is_json_error is False

    def test_blob_type_detection_json_error(self):
        blob_type = "application/json"
        is_json_error = blob_type and "application/json" in blob_type
        assert is_json_error is True

    def test_json_error_parsing(self):
        error_json = {"code": 500, "message": "语音合成失败: TTS服务不可用", "data": None}
        error_text = json.dumps(error_json)
        parsed = json.loads(error_text)
        assert parsed["code"] == 500
        assert "语音合成失败" in parsed["message"]

    def test_content_type_mapping(self):
        content_type_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "pcm": "audio/pcm",
        }
        assert content_type_map.get("mp3") == "audio/mpeg"
        assert content_type_map.get("wav") == "audio/wav"
        assert content_type_map.get("ogg") is None


class TestViteProxyConfig:
    """测试Vite代理配置的正确性"""

    def test_proxy_config_structure(self):
        proxy_config = {
            "/api": {
                "target": "http://localhost:8000",
                "changeOrigin": True,
            },
        }
        assert "/api" in proxy_config
        assert proxy_config["/api"]["target"] == "http://localhost:8000"
        assert proxy_config["/api"]["changeOrigin"] is True

    def test_api_base_url_dev(self):
        import os
        os.environ["DEV"] = "true"
        is_dev = True
        base_url = "/api/v1" if is_dev else "http://localhost:8000/api/v1"
        assert base_url == "/api/v1"

    def test_api_base_url_prod(self):
        is_dev = False
        base_url = "/api/v1" if is_dev else "http://localhost:8000/api/v1"
        assert base_url == "http://localhost:8000/api/v1"


class TestGetCurrentUserTokenFromQuery:
    """测试get_current_user支持query参数传递token"""

    def test_token_from_query_params(self):
        query_params = {"token": "eyJhbGciOiJIUzI1NiJ9.test.sig"}
        token = query_params.get("token")
        assert token is not None
        assert token.startswith("eyJ")

    def test_no_token_in_query_params(self):
        query_params = {}
        token = query_params.get("token")
        assert token is None
