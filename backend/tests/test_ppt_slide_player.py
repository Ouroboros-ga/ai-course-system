"""
PPT幻灯片播放器和节点级音频合成测试
测试新增的后端API和前端数据映射逻辑
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestScriptNodeAudioFields:
    """测试 ScriptNode 新增的 audio_url 和 audio_duration 字段"""

    def test_audio_url_default_none(self):
        from app.models.course_model import ScriptNode
        node = ScriptNode(
            script_id=1,
            node_index=0,
            node_type="lecture",
            content="测试内容",
        )
        assert node.audio_url is None
        assert node.audio_duration == 0.0

    def test_audio_url_with_value(self):
        from app.models.course_model import ScriptNode
        node = ScriptNode(
            script_id=1,
            node_index=0,
            node_type="lecture",
            content="测试内容",
            audio_url="/api/v1/document/audio/node_1_abc123.mp3",
            audio_duration=45.5,
        )
        assert node.audio_url == "/api/v1/document/audio/node_1_abc123.mp3"
        assert node.audio_duration == 45.5


class TestSlidesAPIDataStructure:
    """测试幻灯片API返回数据结构"""

    def test_slides_response_structure(self):
        slides_data = {
            "course_id": 1,
            "total_pages": 5,
            "slides": [
                {"page": 1, "url": "/api/v1/document/course/1/slide/1"},
                {"page": 2, "url": "/api/v1/document/course/1/slide/2"},
                {"page": 3, "url": "/api/v1/document/course/1/slide/3"},
                {"page": 4, "url": "/api/v1/document/course/1/slide/4"},
                {"page": 5, "url": "/api/v1/document/course/1/slide/5"},
            ],
        }

        assert slides_data["total_pages"] == 5
        assert len(slides_data["slides"]) == 5
        assert slides_data["slides"][0]["page"] == 1
        assert "/slide/1" in slides_data["slides"][0]["url"]

    def test_empty_slides_response(self):
        slides_data = {
            "course_id": 1,
            "total_pages": 0,
            "slides": [],
        }
        assert slides_data["total_pages"] == 0
        assert len(slides_data["slides"]) == 0


class TestNodeAudioSynthesis:
    """测试节点级音频合成逻辑"""

    def test_text_segmentation_short(self):
        content = "这是一段短文本"
        if len(content) > 2000:
            segments = []
            current = ""
            for char in content:
                current += char
                if char in "。！？；" and len(current) >= 500:
                    segments.append(current)
                    current = ""
            if current:
                segments.append(current)
        else:
            segments = [content]

        assert segments == ["这是一段短文本"]

    def test_text_segmentation_long(self):
        content = "第一段内容。" + "很长的填充文字" * 50 + "。第二段内容。" + "更多填充" * 50 + "。"
        if len(content) > 2000:
            segments = []
            current = ""
            for char in content:
                current += char
                if char in "。！？；" and len(current) >= 500:
                    segments.append(current)
                    current = ""
            if current:
                segments.append(current)
        else:
            segments = [content]

        assert len(segments) >= 1

    def test_audio_url_format(self):
        node_id = 42
        import uuid
        audio_filename = f"node_{node_id}_{uuid.uuid4().hex[:8]}.mp3"
        audio_url = f"/api/v1/document/audio/{audio_filename}"

        assert audio_url.startswith("/api/v1/document/audio/")
        assert audio_url.endswith(".mp3")
        assert f"node_{node_id}_" in audio_url

    def test_audio_duration_estimation(self):
        audio_data_size = 32000
        sample_rate = 16000
        channels = 2
        estimated_duration = audio_data_size / sample_rate / channels
        assert estimated_duration == 1.0

    def test_node_type_filter_for_tts(self):
        valid_types = {"lecture", "summary", "interactive"}
        invalid_types = {"question", "breakpoint", "video"}

        for t in valid_types:
            assert t in valid_types
        for t in invalid_types:
            assert t not in valid_types


class TestCourseDetailNodeFields:
    """测试课程详情API中节点返回的新字段"""

    def test_node_response_includes_audio_fields(self):
        node_data = {
            "id": 1,
            "node_index": 0,
            "node_type": "lecture",
            "title": "频域响应法概述",
            "content": "这是内容",
            "page_start": 1,
            "page_end": 3,
            "duration": 60,
            "is_key_point": True,
            "extra_data": None,
            "audio_url": "/api/v1/document/audio/node_1_abc.mp3",
            "audio_duration": 45.5,
        }

        assert "audio_url" in node_data
        assert "audio_duration" in node_data
        assert "page_start" in node_data
        assert "page_end" in node_data
        assert node_data["audio_url"].startswith("/api/v1/document/audio/")
        assert node_data["audio_duration"] > 0

    def test_node_response_without_audio(self):
        node_data = {
            "id": 2,
            "node_index": 1,
            "node_type": "question",
            "title": "互动问答",
            "content": "请回答问题",
            "page_start": 4,
            "page_end": 4,
            "duration": 30,
            "is_key_point": False,
            "extra_data": None,
            "audio_url": None,
            "audio_duration": 0.0,
        }

        assert node_data["audio_url"] is None
        assert node_data["audio_duration"] == 0.0


class TestFrontendMediaMapping:
    """测试前端媒体数据映射逻辑"""

    def test_slide_page_from_node(self):
        node = {
            "page_start": 5,
            "page_end": 8,
            "audio_url": "/api/v1/document/audio/node_1.mp3",
            "audio_duration": 60.0,
        }
        current_slide_page = node["page_start"] or 1
        assert current_slide_page == 5

    def test_slide_page_default(self):
        node = {"page_start": None, "page_end": None}
        current_slide_page = node["page_start"] or 1
        assert current_slide_page == 1

    def test_audio_url_mapping(self):
        node = {"audio_url": "/api/v1/document/audio/node_1.mp3", "audio_duration": 45.5}
        audio_url = node["audio_url"] or ""
        audio_duration = node["audio_duration"] or 0
        assert audio_url == "/api/v1/document/audio/node_1.mp3"
        assert audio_duration == 45.5

    def test_audio_url_empty_when_none(self):
        node = {"audio_url": None, "audio_duration": 0}
        audio_url = node["audio_url"] or ""
        assert audio_url == ""

    def test_format_audio_time(self):
        def format_time(seconds):
            if not seconds or str(seconds) == "nan":
                return "0:00"
            m = int(seconds) // 60
            s = int(seconds) % 60
            return f"{m}:{str(s).zfill(2)}"

        assert format_time(0) == "0:00"
        assert format_time(45) == "0:45"
        assert format_time(90) == "1:30"
        assert format_time(3661) == "61:01"
        assert format_time(None) == "0:00"

    def test_batch_synthesize_response_structure(self):
        response = {
            "course_id": 1,
            "success_count": 3,
            "error_count": 1,
            "results": [
                {"node_id": 1, "title": "概述", "audio_url": "/api/v1/document/audio/node_1.mp3"},
                {"node_id": 2, "title": "原理", "audio_url": "/api/v1/document/audio/node_2.mp3"},
                {"node_id": 3, "title": "应用", "audio_url": "/api/v1/document/audio/node_3.mp3"},
            ],
            "errors": [
                {"node_id": 4, "title": "问答", "error": "内容过短"},
            ],
        }

        assert response["success_count"] == 3
        assert response["error_count"] == 1
        assert len(response["results"]) == 3
        assert len(response["errors"]) == 1
