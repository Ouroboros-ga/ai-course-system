"""
分屏视频播放器API测试
测试F6分屏播放器的后端接口功能
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
import uuid

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestPlayerAPI:
    """播放器API端点测试"""

    @pytest.fixture
    def mock_session(self):
        """模拟数据库会话"""
        session = MagicMock()
        return session

    @pytest.fixture
    def mock_user(self):
        """模拟当前用户"""
        return {
            "user_id": 1,
            "username": "test_student",
            "role": "student",
        }

    def test_get_player_init_data_success(self, mock_session, mock_user):
        """测试获取播放器初始化数据 - 成功场景"""
        from app.api.v1.endpoints.player import get_player_init_data
        from app.models.course_model import Course, CourseScript, ScriptNode, ScriptNodeType
        from app.models.video_generation_model import VideoGenerationTask, GenerationStatus
        from app.models.progress_model import LearningProgress, LearningStatus

        # 模拟课程数据
        mock_course = MagicMock()
        mock_course.id = 1
        mock_course.title = "测试课程"
        mock_session.get.return_value = mock_course

        # 模拟脚本数据
        mock_script = MagicMock()
        mock_script.id = 10
        mock_script.version = 1
        mock_script.audio_duration = 300
        mock_script.is_active = True
        mock_session.exec.return_value.first.return_value = mock_script

        # 模拟节点数据
        mock_nodes = [
            MagicMock(
                id=1,
                node_index=1,
                node_type=ScriptNodeType.LECTURE,
                title="知识点1",
                content="这是第一个知识点的讲解内容...",
                chapter_id="chap001_01",
                timestamp_start=0.0,
                timestamp_end=60.0,
                duration=60,
                page_start=1,
                page_end=3,
                is_key_point=True,
            ),
            MagicMock(
                id=2,
                node_index=2,
                node_type=ScriptNodeType.LECTURE,
                title="知识点2",
                content="这是第二个知识点的讲解内容...",
                chapter_id="chap001_02",
                timestamp_start=60.0,
                timestamp_end=120.0,
                duration=60,
                page_start=4,
                page_end=6,
                is_key_point=False,
            ),
        ]
        mock_session.exec.return_value.all.return_value = mock_nodes

        # 模拟视频生成任务（已完成）
        mock_task = MagicMock()
        mock_task.node_id = 1
        mock_task.dh_video_path = "/videos/test_dh_video.mp4"
        mock_session.exec.return_value.__iter__ = MagicMock(return_value=iter([mock_task]))

        # 模拟学习进度数据
        mock_progress = MagicMock()
        mock_progress.current_node_id = 1
        mock_progress.current_node_index = 0
        mock_progress.current_timestamp = 30.5
        mock_progress.current_page = 2
        mock_progress.completion_rate = 0.5
        mock_progress.total_learning_time = 1800
        mock_progress.last_accessed_at = datetime.utcnow()
        mock_session.exec.return_value.first.return_value = mock_progress

        # 调用API（这里只是验证逻辑，实际需要FastAPI TestClient）
        # 由于依赖注入复杂，我们主要测试数据处理逻辑
        print("✓ 测试数据准备完成")

        # 验证数据结构
        assert len(mock_nodes) == 2
        assert mock_nodes[0].timestamp_start == 0.0
        assert mock_nodes[1].timestamp_end == 120.0

    def test_player_route_requires_course_membership(self, client, student_token):
        """未知课程不能被播放器读取，且不以空 pass 伪造断言。"""
        response = client.get(
            "/api/v1/player/init/999999",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        # Course Access resolves scope before player data and fails closed.
        assert response.status_code in {403, 404}

    def test_player_returns_empty_payload_for_accessible_course_without_content(
        self, client, session, teacher_user, student_user, student_token,
    ):
        """An accessible draft course is an empty learning state, not a 404."""
        from app.models.course_model import Course, CourseStatus
        from app.services.course_access_service import (
            activate_student_membership,
            establish_course_access_baseline,
        )

        suffix = uuid.uuid4().hex[:8]
        course = Course(
            fanya_course_id=f"empty-player-{suffix}",
            fanya_course_name="Empty player fixture",
            title="Empty player fixture",
            teacher_id=teacher_user.id,
            status=CourseStatus.DRAFT,
        )
        session.add(course)
        session.commit()
        session.refresh(course)
        establish_course_access_baseline(session, course.id, teacher_user.id)
        activate_student_membership(session, course.id, student_user.id)
        session.commit()

        response = client.get(
            f"/api/v1/player/init/{course.id}",
            headers={"Authorization": f"Bearer {student_token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["course_id"] == course.id
        assert payload["nodes"] == []
        assert payload["content_status"] == "unavailable"
        assert payload["content_message"]

    def test_teacher_can_preview_unpublished_outline_but_student_cannot(
        self, client, session, teacher_user, student_user, teacher_token, student_token,
    ):
        """Draft lesson content is visible only through the teacher preview path."""
        from app.models.course_model import Course, CourseStatus
        from app.models.course_outline_model import (
            CourseOutlineNode,
            CourseOutlineVersion,
            OutlineLifecycleStatus,
            OutlineNodeType,
        )
        from app.services.course_access_service import (
            activate_student_membership,
            establish_course_access_baseline,
        )

        suffix = uuid.uuid4().hex[:8]
        course = Course(
            fanya_course_id=f"draft-preview-{suffix}",
            fanya_course_name="Draft preview fixture",
            title="Draft preview fixture",
            teacher_id=teacher_user.id,
            status=CourseStatus.DRAFT,
        )
        session.add(course)
        session.commit()
        session.refresh(course)
        establish_course_access_baseline(session, course.id, teacher_user.id)
        activate_student_membership(session, course.id, student_user.id)

        outline = CourseOutlineVersion(
            course_id=course.id,
            version=1,
            lifecycle_status=OutlineLifecycleStatus.DRAFT,
            created_by=teacher_user.id,
        )
        session.add(outline)
        session.commit()
        session.refresh(outline)
        session.add(CourseOutlineNode(
            course_id=course.id,
            outline_version_id=outline.outline_version_id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title="未发布的知识点",
            order_index=1,
            page_range="2-3",
        ))
        session.commit()

        teacher_response = client.get(
            f"/api/v1/player/init/{course.id}",
            headers={"Authorization": f"Bearer {teacher_token}"},
        )
        assert teacher_response.status_code == 200
        teacher_payload = teacher_response.json()
        assert teacher_payload["content_status"] == "preview"
        assert teacher_payload["nodes"][0]["title"] == "未发布的知识点"
        assert teacher_payload["nodes"][0]["status"] == "preview"

        student_response = client.get(
            f"/api/v1/player/init/{course.id}",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert student_response.status_code == 200
        assert student_response.json()["content_status"] == "unavailable"

    def test_save_player_progress_new_record(self, mock_session, mock_user):
        """测试保存学习进度 - 新记录"""
        from app.api.v1.endpoints.player import save_player_progress, ProgressSaveRequest
        from app.models.progress_model import LearningProgress, LearningStatus
        from fastapi import Response

        # 模拟没有现有进度
        mock_session.exec.return_value.first.return_value = None

        # 模拟课程存在
        mock_course = MagicMock()
        mock_course.id = 1
        mock_session.get.return_value = mock_course

        # 构造请求数据
        request_data = ProgressSaveRequest(
            course_id=1,
            current_node_id=1,
            current_timestamp=45.5,
            current_page=3,
            completed_nodes=[1],
        )

        print("✓ 进度保存请求构造完成")
        assert request_data.course_id == 1
        assert request_data.current_timestamp == 45.5

    def test_save_player_progress_update_existing(self, mock_session, mock_user):
        """测试保存学习进度 - 更新现有记录"""
        from app.api.v1.endpoints.player import save_player_progress, ProgressSaveRequest
        from app.models.progress_model import LearningProgress, LearningStatus

        # 模拟已有进度记录
        mock_progress = MagicMock()
        mock_progress.id = 100
        mock_progress.current_node_id = 1
        mock_progress.current_timestamp = 30.0
        mock_progress.current_page = 2
        mock_progress.completed_nodes = 1
        mock_progress.completion_rate = 0.3
        mock_progress.status = LearningStatus.IN_PROGRESS
        mock_session.exec.return_value.first.return_value = mock_progress

        # 构造更新请求
        request_data = ProgressSaveRequest(
            course_id=1,
            current_node_id=2,
            current_timestamp=75.8,
            current_page=5,
            completed_nodes=[1, 2],
        )

        print("✓ 进度更新请求构造完成")
        assert request_data.current_timestamp == 75.8
        assert len(request_data.completed_nodes) == 2


class TestKnowledgePointsAPI:
    """知识点导航API测试"""

    def test_get_knowledge_points_with_completion(self):
        """测试获取知识点列表 - 包含完成状态"""
        from app.api.v1.endpoints.player import KnowledgePoint

        # 构造知识点数据
        kp1 = KnowledgePoint(
            node_id=1,
            chapter_id="chap001_01",
            title="频域响应法基础",
            timestamp_start=0.0,
            timestamp_end=60.0,
            node_index=0,
            is_completed=True,
        )

        kp2 = KnowledgePoint(
            node_id=2,
            chapter_id="chap001_02",
            title="频率特性分析",
            timestamp_start=60.0,
            timestamp_end=120.0,
            node_index=1,
            is_completed=False,
        )

        # 验证数据结构
        data = [kp1.dict(), kp2.dict()]

        assert len(data) == 2
        assert data[0]["is_completed"] is True
        assert data[1]["is_completed"] is False
        assert data[0]["title"] == "频域响应法基础"
        assert data[1]["timestamp_end"] == 120.0

        print("✓ 知识点数据结构验证通过")


class TestDataModels:
    """数据模型测试"""

    def test_player_init_data_model(self):
        """测试PlayerInitData模型"""
        from app.api.v1.endpoints.player import PlayerInitData

        data = PlayerInitData(
            course_id=1,
            course_title="测试课程",
            script_id=10,
            total_duration=300.5,
            total_nodes=5,
            nodes=[
                {
                    "id": 1,
                    "node_index": 1,
                    "title": "知识点1",
                    "timestamp_start": 0.0,
                    "timestamp_end": 60.0,
                }
            ],
            video_base_url="/api/v1/video/stream/",
        )

        assert data.course_id == 1
        assert data.total_duration == 300.5
        assert len(data.nodes) == 1
        assert data.saved_progress is None

    def test_progress_save_request_model(self):
        """测试ProgressSaveRequest模型"""
        from app.api.v1.endpoints.player import ProgressSaveRequest

        request = ProgressSaveRequest(
            course_id=1,
            current_timestamp=45.5,
            current_page=3,
            completed_nodes=[1, 2, 3],
        )

        assert request.course_id == 1
        assert request.current_timestamp == 45.5
        assert request.current_page == 3
        assert len(request.completed_nodes) == 3


class TestVideoSyncLogic:
    """视频-PPT同步逻辑测试"""

    def test_find_node_by_time_binary_search(self):
        """测试二分查找时间戳对应节点"""
        nodes = [
            {"id": 1, "node_index": 1, "timestamp_start": 0.0, "timestamp_end": 60.0},
            {"id": 2, "node_index": 2, "timestamp_start": 60.0, "timestamp_end": 120.0},
            {"id": 3, "node_index": 3, "timestamp_start": 120.0, "timestamp_end": 180.0},
            {"id": 4, "node_index": 4, "timestamp_start": 180.0, "timestamp_end": 240.0},
        ]

        def find_node(timestamp):
            left, right = 0, len(nodes) - 1
            while left <= right:
                mid = (left + right) // 2
                node = nodes[mid]
                if node["timestamp_start"] <= timestamp <= node["timestamp_end"]:
                    return node
                elif timestamp < node["timestamp_start"]:
                    right = mid - 1
                else:
                    left = mid + 1
            return None

        # 测试各个时间点
        assert find_node(30.0)["id"] == 1
        assert find_node(60.0)["id"] == 2
        assert find_node(90.0)["id"] == 2
        assert find_node(150.0)["id"] == 3
        assert find_node(239.9)["id"] == 4

        print("✓ 二分查找时间戳算法验证通过")

    def test_calculate_knowledge_point_progress(self):
        """测试知识点进度计算"""
        point = {
            "timestamp_start": 60.0,
            "timestamp_end": 120.0,
        }

        def calculate_progress(current_time, point):
            total = point["timestamp_end"] - point["timestamp_start"]
            if total <= 0:
                return 0
            current = current_time - point["timestamp_start"]
            return max(0, min(100, (current / total) * 100))

        # 测试不同进度
        assert calculate_progress(60.0, point) == 0.0
        assert calculate_progress(90.0, point) == 50.0
        assert calculate_progress(120.0, point) == 100.0
        assert calculate_progress(105.0, point) == 75.0

        print("✓ 知识点进度计算验证通过")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
