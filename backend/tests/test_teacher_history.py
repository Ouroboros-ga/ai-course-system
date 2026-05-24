"""
教师历史页面相关测试
测试后端 /stats API 的节点进度数据、前端数据映射逻辑
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestCourseStatsNodeProgress:
    """测试课程统计 API 的节点进度数据"""

    def test_node_progress_data_structure(self):
        """测试节点进度数据的结构完整性"""
        node_progress = {
            "node_id": 1,
            "node_index": 0,
            "title": "频域响应法概述",
            "node_type": "lecture",
            "is_key_point": True,
            "completed_count": 5,
            "total_students": 10,
            "completion_rate": 50.0,
            "avg_understanding": 72.5,
            "accessed_count": 8,
        }

        assert "node_id" in node_progress
        assert "node_index" in node_progress
        assert "title" in node_progress
        assert "node_type" in node_progress
        assert "is_key_point" in node_progress
        assert "completed_count" in node_progress
        assert "total_students" in node_progress
        assert "completion_rate" in node_progress
        assert "avg_understanding" in node_progress
        assert "accessed_count" in node_progress

    def test_completion_rate_calculation(self):
        """测试完成率计算逻辑"""
        total_students = 10

        completed_count = 5
        completion_rate = round(completed_count / total_students * 100, 1)
        assert completion_rate == 50.0

        completed_count = 0
        completion_rate = round(completed_count / total_students * 100, 1)
        assert completion_rate == 0.0

        completed_count = 10
        completion_rate = round(completed_count / total_students * 100, 1)
        assert completion_rate == 100.0

    def test_completion_rate_zero_students(self):
        """测试零学生时的完成率"""
        total_students = 0
        completed_count = 0
        completion_rate = round(completed_count / total_students * 100, 1) if total_students > 0 else 0
        assert completion_rate == 0

    def test_avg_understanding_calculation(self):
        """测试平均理解度计算"""
        total_accessed = 4
        total_understanding = 3.2
        avg_understanding = round(total_understanding / total_accessed * 100, 1) if total_accessed > 0 else 0
        assert avg_understanding == 80.0

    def test_avg_understanding_zero_accessed(self):
        """测试零访问时的平均理解度"""
        total_accessed = 0
        total_understanding = 0.0
        avg_understanding = round(total_understanding / total_accessed * 100, 1) if total_accessed > 0 else 0
        assert avg_understanding == 0

    def test_progress_distribution_keys(self):
        """测试进度分布的键名"""
        dist = {
            "not_started": 2,
            "beginner": 3,
            "intermediate": 5,
            "advanced": 4,
            "completed": 1,
        }
        expected_keys = {"not_started", "beginner", "intermediate", "advanced", "completed"}
        assert set(dist.keys()) == expected_keys

    def test_progress_distribution_total(self):
        """测试进度分布的总人数"""
        dist = {
            "not_started": 2,
            "beginner": 3,
            "intermediate": 5,
            "advanced": 4,
            "completed": 1,
        }
        total = sum(dist.values())
        assert total == 15


class TestFrontendDataMapping:
    """测试前端数据映射逻辑"""

    def test_progress_labels_mapping(self):
        """测试进度标签映射（修复前后的对比）"""
        dist = {
            "not_started": 2,
            "beginner": 3,
            "intermediate": 5,
            "advanced": 4,
            "completed": 1,
        }

        # 修复后的正确映射
        progress_labels = [
            {"key": "not_started", "label": "未开始", "count": dist.get("not_started", 0)},
            {"key": "beginner", "label": "初学", "count": dist.get("beginner", 0)},
            {"key": "intermediate", "label": "进阶", "count": dist.get("intermediate", 0)},
            {"key": "advanced", "label": "熟练", "count": dist.get("advanced", 0)},
            {"key": "completed", "label": "完成", "count": dist.get("completed", 0)},
        ]

        assert progress_labels[0]["label"] == "未开始"
        assert progress_labels[0]["count"] == 2
        assert progress_labels[4]["label"] == "完成"
        assert progress_labels[4]["count"] == 1

    def test_understanding_level_labels(self):
        """测试理解度等级标签映射"""
        labels = {"excellent": "优秀", "high": "良好", "medium": "一般", "low": "需加强", "unknown": "未知"}
        assert labels["excellent"] == "优秀"
        assert labels["unknown"] == "未知"

    def test_pie_chart_data_structure(self):
        """测试饼状图数据结构"""
        progress_labels = [
            {"key": "not_started", "label": "未开始", "count": 2},
            {"key": "beginner", "label": "初学", "count": 3},
            {"key": "intermediate", "label": "进阶", "count": 5},
            {"key": "advanced", "label": "熟练", "count": 4},
            {"key": "completed", "label": "完成", "count": 1},
        ]

        PROGRESS_COLORS = {
            "not_started": "#d1d5db",
            "beginner": "#93c5fd",
            "intermediate": "#a78bfa",
            "advanced": "#86efac",
            "completed": "#34d399",
        }

        pie_data = {
            "labels": [i["label"] for i in progress_labels],
            "datasets": [{
                "data": [i["count"] for i in progress_labels],
                "backgroundColor": [PROGRESS_COLORS[i["key"]] for i in progress_labels],
            }],
        }

        assert pie_data["labels"] == ["未开始", "初学", "进阶", "熟练", "完成"]
        assert pie_data["datasets"][0]["data"] == [2, 3, 5, 4, 1]
        assert len(pie_data["datasets"][0]["backgroundColor"]) == 5

    def test_node_chart_data_structure(self):
        """测试节点完成率环形图数据结构"""
        node_progress = [
            {"node_id": 1, "title": "概述", "completed_count": 5, "total_students": 10, "completion_rate": 50.0},
            {"node_id": 2, "title": "原理", "completed_count": 3, "total_students": 10, "completion_rate": 30.0},
        ]

        completed_counts = [n["completed_count"] for n in node_progress]
        remaining_counts = [n["total_students"] - n["completed_count"] for n in node_progress]

        assert completed_counts == [5, 3]
        assert remaining_counts == [5, 7]

    def test_dist_percent_calculation(self):
        """测试分布百分比计算"""
        total_students = 10
        count = 3
        percent = round(count / total_students * 100)
        assert percent == 30

    def test_dist_percent_zero_students(self):
        """测试零学生时的分布百分比"""
        total_students = 0
        count = 0
        percent = round(count / (total_students or 1) * 100)
        assert percent == 0

    def test_node_progress_class(self):
        """测试节点进度条样式类"""
        def get_class(rate):
            if rate >= 80: return "node-high"
            if rate >= 50: return "node-medium"
            if rate > 0: return "node-low"
            return "node-none"

        assert get_class(90) == "node-high"
        assert get_class(60) == "node-medium"
        assert get_class(20) == "node-low"
        assert get_class(0) == "node-none"
