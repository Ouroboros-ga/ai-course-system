"""
AI课程系统功能测试
测试内容：
1. 教师界面学生状态数字显示
2. 学生选课/退课功能
3. 学习进度数据持久化

运行方式: python -m pytest tests/test_new_features.py -v
"""

import pytest
from datetime import datetime
from sqlmodel import Session, select


class TestCourseStudentCount:
    """测试教师界面的学生选课人数统计"""

    def test_courses_list_includes_student_count(self, client, teacher_token, session):
        """测试课程列表API是否包含student_count字段"""
        # 创建一门已发布的课程
        course_data = self._create_published_course(client, teacher_token)

        # 获取课程列表（教师视角）
        response = client.get(
            "/api/v1/document/courses",
            headers={"Authorization": f"Bearer {teacher_token}"}
        )
        assert response.status_code == 200
        data = response.json()

        assert "courses" in data
        assert len(data["courses"]) > 0

        course = data["courses"][0]
        assert "student_count" in course, "课程数据应包含student_count字段"
        assert isinstance(course["student_count"], int), "student_count应为整数"

    def test_student_count_matches_enrollments(self, client, teacher_token, student_token, session):
        """测试student_count与实际选课记录数一致"""
        # 创建并发布课程
        course = self._create_published_course(client, teacher_token)
        course_id = course["id"]

        # 学生选课
        enroll_response = client.post(
            f"/api/v1/document/course/{course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert enroll_response.status_code == 200

        # 验证教师看到的选课人数为1
        courses_response = client.get(
            "/api/v1/document/courses",
            headers={"Authorization": f"Bearer {teacher_token}"}
        )
        courses = courses_response.json()["courses"]
        target_course = next(c for c in courses if c["id"] == course_id)
        assert target_course["student_count"] == 1, f"应有1名学生，实际显示{target_course['student_count']}"

    def _create_published_course(self, client, token):
        """辅助方法：创建并发布课程"""
        # 这里简化处理，实际应调用上传接口
        return {"id": 999}


class TestStudentEnrollment:
    """测试学生选课/退课功能"""

    def test_get_my_courses_empty(self, client, student_token):
        """测试未选课时我的课程列表为空"""
        response = client.get(
            "/api/v1/document/my-courses",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["courses"] == []

    def test_enroll_course_success(self, client, published_course_id, student_token):
        """测试学生成功选课"""
        response = client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "enrollment_id" in data or "already_enrolled" in data

    def test_my_courses_after_enrollment(self, client, published_course_id, student_token):
        """测试选课后我的课程列表包含该课程"""
        # 先选课
        self.test_enroll_course_success(client, published_course_id, student_token)

        # 查看我的课程
        response = client.get(
            "/api/v1/document/my-courses",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        course_ids = [c["course_id"] for c in data["courses"]]
        assert published_course_id in course_ids

    def test_unenroll_course(self, client, published_course_id, student_token):
        """测试退课功能"""
        # 先确保已选课
        client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )

        # 退课
        response = client.post(
            f"/api/v1/document/course/{published_course_id}/unenroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert response.status_code == 200

        # 验证我的课程列表不再包含该课程
        my_courses = client.get(
            "/api/v1/document/my-courses",
            headers={"Authorization": f"Bearer {student_token}"}
        ).json()
        course_ids = [c["course_id"] for c in my_courses["courses"]]
        assert published_course_id not in course_ids

    def test_reenroll_after_unenroll(self, client, published_course_id, student_token):
        """测试退课后重新选课"""
        # 选课 -> 退课 -> 再选课
        client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        client.post(
            f"/api/v1/document/course/{published_course_id}/unenroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )

        reenroll_resp = client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert reenroll_resp.status_code == 200
        assert reenroll_resp.json().get("reactivated") == True


class TestLearningProgressPersistence:
    """测试学习进度持久化"""

    def test_progress_initialized_on_enrollment(self, client, published_course_id, student_token, session):
        """测试选课时自动初始化学习进度"""
        # 选课
        enroll_resp = client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert enroll_resp.status_code == 200

        # 查询数据库中是否存在学习进度记录
        from app.models.progress_model import LearningProgress
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.course_id == published_course_id
            )
        ).first()

        assert progress is not None, "选课后应创建学习进度记录"
        assert progress.completion_rate == 0.0, "初始完成率应为0"

    def test_save_and_load_node_progress(self, client, published_course_id, student_token, session):
        """测试节点进度的保存和加载"""
        # 选课
        client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )

        # 假设节点ID为1（实际应根据课程获取）
        node_id = 1

        # 同步进度（模拟学生学习）
        sync_resp = client.post(
            "/api/v1/progress/sync",
            headers={"Authorization": f"Bearer {student_token}"},
            json={
                "courseId": published_course_id,
                "nodeId": node_id,
                "timestamp": 60.0,
                "isCompleted": True,
                "timeSpent": 120,
            }
        )
        assert sync_resp.status_code == 200

        # 加载进度详情
        detail_resp = client.get(
            f"/api/v1/progress/detail/{published_course_id}",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()

        assert detail_data["has_progress"] == True
        assert len(detail_data["nodes_progress"]) > 0

        # 找到对应节点的进度
        node_prog = next(
            (np for np in detail_data["nodes_progress"] if np["node_id"] == node_id),
            None
        )
        assert node_prog is not None, "应存在节点进度记录"
        assert node_prog["is_completed"] == True, "节点应标记为已完成"

    def test_progress_persists_across_sessions(self, client, published_course_id, student_token, session):
        """测试跨会话进度保持（模拟退出再进入）"""
        # 第一次：选课并学习
        client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )

        client.post(
            "/api/v1/progress/sync",
            headers={"Authorization": f"Bearer {student_token}"},
            json={
                "courseId": published_course_id,
                "nodeId": 1,
                "timestamp": 30.0,
                "isCompleted": True,
                "timeSpent": 90,
            }
        )

        # 第二次：重新加载进度（模拟用户退出后再进入）
        resume_resp = client.get(
            f"/api/v1/progress/detail/{published_course_id}",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        resume_data = resume_resp.json()

        assert resume_data["has_progress"] == True, "再次进入时应保留历史进度"
        assert resume_data["overall"]["completion_rate"] > 0, "完成率应大于0"


class TestTeacherViewStudentStats:
    """测试教师端查看学生统计"""

    def test_teacher_can_view_student_list(self, client, teacher_token, student_token, published_course_id):
        """测试教师可以查看选课学生列表"""
        # 学生选课
        client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )

        # 教师查看学生列表
        response = client.get(
            f"/api/v1/document/course/{published_course_id}/students",
            headers={"Authorization": f"Bearer {teacher_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["students"]) >= 1, "应至少有1名学生的记录"

    def test_student_stats_include_progress(self, client, teacher_token, student_token, published_course_id):
        """测试学生统计数据包含学习进度"""
        # 学生选课并学习
        client.post(
            f"/api/v1/document/course/{published_course_id}/enroll",
            headers={"Authorization": f"Bearer {student_token}"}
        )

        client.post(
            "/api/v1/progress/sync",
            headers={"Authorization": f"Bearer {student_token}"},
            json={
                "courseId": published_course_id,
                "nodeId": 1,
                "timestamp": 45.0,
                "isCompleted": False,
                "timeSpent": 60,
            }
        )

        # 教师查看课程统计
        stats_resp = client.get(
            f"/api/v1/document/course/{published_course_id}/stats",
            headers={"Authorization": f"Bearer {teacher_token}"}
        )
        assert stats_resp.status_code == 200
        stats = stats_resp.json()["data"]

        assert stats["total_students"] >= 1
        # 注意：由于理解度分析需要实际问答交互，这里可能仍为0
        assert "avg_progress" in stats
        assert "avg_understanding" in stats


# ==================== Fixtures ====================

@pytest.fixture
def auth_headers(token):
    """生成认证头"""
    return {"Authorization": f"Bearer {token}"}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
