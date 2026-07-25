"""G3 代码沙箱测试

验证：
- 沙箱不可用时降级
- 不允许的语言被拒绝
- 资源限制正确传递
- 健康检查
- 权限校验（需要 membership，不依赖旧 teacher_id）
- 跨课程隔离
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import select

from app.core.security import get_password_hash, create_access_token
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    establish_course_access_baseline,
    activate_student_membership,
)
from app.services.sandbox_client import (
    SandboxClient,
    SandboxResourceLimits,
    SandboxResult,
    SubmissionStatus,
    ALLOWED_LANGUAGES,
    sandbox_client,
)


def _user(session, name: str, role: UserRole = UserRole.STUDENT) -> User:
    user = User(
        username=name,
        hashed_password=get_password_hash("test"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"sb-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="Sandbox Course",
        title="Sandbox Course",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _setup_course(session, teacher, student, enable_experiment: bool = True):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    activate_student_membership(session, course.id, student.id)
    if enable_experiment:
        from app.models.access_control_model import CourseCapability
        cap = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == course.id)
        ).first()
        if cap:
            cap.experiment = True
            cap.coding_sandbox = True
            session.add(cap)
    session.commit()
    return course


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
    })


# ==================== 沙箱客户端测试 ====================

class TestSandboxClient:
    """沙箱客户端单元测试（不需要数据库）"""

    def test_disabled_sandbox_returns_unavailable(self):
        """沙箱未启用时返回 SANDBOX_UNAVAILABLE"""
        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = False

        result = client.submit_code("print('hello')", "python3")

        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        assert "降级" in result.message

    def test_disallowed_language_rejected(self):
        """不允许的语言被拒绝"""
        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        with pytest.raises(ValueError, match="不在允许列表中"):
            client.submit_code("code", "bash")

    def test_allowed_languages_list(self):
        """允许的语言列表包含主要语言"""
        assert "python3" in ALLOWED_LANGUAGES
        assert "c" in ALLOWED_LANGUAGES
        assert "cpp" in ALLOWED_LANGUAGES
        assert "java" in ALLOWED_LANGUAGES
        assert "javascript" in ALLOWED_LANGUAGES

    def test_health_check_disabled_returns_false(self):
        """沙箱未启用时健康检查返回 False"""
        client = SandboxClient()
        client._enabled = False
        assert client.health_check() is False

    def test_resource_limits_defaults(self):
        """默认资源限制正确"""
        limits = SandboxResourceLimits()
        assert limits.cpu_time_limit == 5
        assert limits.memory_limit == 128000
        assert limits.wall_time_limit == 10
        assert limits.enable_network is False  # 始终关闭网络

    @patch("app.services.sandbox_client.httpx.Client")
    def test_submit_code_parses_accepted_result(self, mock_client_cls):
        """正确解析 Accepted 结果"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "test-token",
            "status": {"id": 3, "description": "Accepted"},
            "stdout": "aGVsbG8=\n",  # base64("hello")
            "stderr": None,
            "compile_output": None,
            "time": "0.01",
            "memory": 3328,
            "exit_code": 0,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        result = client.submit_code("print('hello')", "python3")

        assert result.is_accepted
        assert result.stdout == "hello"
        assert result.time == 0.01
        assert result.memory == 3328

    @patch("app.services.sandbox_client.httpx.Client")
    def test_submit_code_parses_compilation_error(self, mock_client_cls):
        """正确解析编译错误"""
        import base64
        error_msg = base64.b64encode(b"Error: syntax error").decode()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "test-token",
            "status": {"id": 8, "description": "Compilation Error"},
            "stdout": None,
            "stderr": None,
            "compile_output": error_msg,
            "time": None,
            "memory": None,
            "exit_code": None,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        result = client.submit_code("invalid code", "cpp")

        assert result.status == SubmissionStatus.COMPILATION_ERROR
        assert result.is_error
        assert "syntax error" in result.compile_output

    @patch("app.services.sandbox_client.httpx.Client")
    def test_submit_code_parses_time_limit(self, mock_client_cls):
        """正确解析超时"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "test-token",
            "status": {"id": 5, "description": "Time Limit Exceeded"},
            "stdout": None,
            "stderr": None,
            "compile_output": None,
            "time": "5.0",
            "memory": 50000,
            "exit_code": None,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        result = client.submit_code("while True: pass", "python3")

        assert result.is_timeout
        assert result.time == 5.0

    @patch("app.services.sandbox_client.httpx.Client")
    def test_submit_code_parses_memory_exceeded(self, mock_client_cls):
        """正确解析内存超限"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "test-token",
            "status": {"id": 6, "description": "Memory Limit Exceeded"},
            "stdout": None,
            "stderr": None,
            "compile_output": None,
            "time": "0.5",
            "memory": 128000,
            "exit_code": None,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        result = client.submit_code("x = [0] * 999999999", "python3")

        assert result.is_memory_exceeded

    @patch("app.services.sandbox_client.httpx.Client")
    def test_submit_code_connection_error_degrades(self, mock_client_cls):
        """连接失败时降级返回 SANDBOX_UNAVAILABLE"""
        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        result = client.submit_code("print('hello')", "python3")

        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        assert "降级" in result.message

    @patch("app.services.sandbox_client.httpx.Client")
    def test_network_always_disabled_in_payload(self, mock_client_cls):
        """提交请求中网络始终关闭"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "t",
            "status": {"id": 3, "description": "Accepted"},
            "stdout": None,
            "stderr": None,
            "compile_output": None,
            "time": None,
            "memory": None,
            "exit_code": 0,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        client.submit_code("print('hello')", "python3")

        # 验证提交的 payload 中 enable_network=False
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["enable_network"] is False


# ==================== API 集成测试 ====================

class TestSandboxAPI:
    """沙箱 API 集成测试"""

    def test_execute_requires_membership(self, client, session):
        """需要 CourseMembership 才能访问"""
        teacher = _user(session, "sb_teacher_no_mem", UserRole.TEACHER)
        course = _course(session, teacher.id)
        # 不建立 membership

        token = _token(teacher)
        response = client.post(
            f"/api/v1/sandbox/course/{course.id}/execute",
            json={"source_code": "print('hello')", "language": "python3"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_execute_with_student_membership(self, client, session, monkeypatch):
        """有 membership 的学生可以执行代码"""
        teacher = _user(session, "sb_teacher_ok", UserRole.TEACHER)
        student = _user(session, "sb_student_ok")
        course = _setup_course(session, teacher, student)

        # Keep this unit test independent from a developer's enabled local Judge0.
        monkeypatch.setattr(sandbox_client, "_enabled", False)
        token = _token(student)
        response = client.post(
            f"/api/v1/sandbox/course/{course.id}/execute",
            json={"source_code": "print('hello')", "language": "python3"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "sandbox_unavailable"

    def test_health_endpoint(self, client, session):
        """健康检查端点"""
        user = _user(session, "sb_health_user")
        response = client.get(
            "/api/v1/sandbox/health",
            headers={"Authorization": f"Bearer {_token(user)}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "enabled" in data
        assert "allowed_languages" in data
        assert "python3" in data["allowed_languages"]

    def test_languages_endpoint(self, client, session):
        """语言列表端点"""
        teacher = _user(session, "sb_teacher_lang", UserRole.TEACHER)
        token = _token(teacher)
        response = client.get(
            "/api/v1/sandbox/languages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "python3" in data["languages"]
        assert "cpp" in data["languages"]

    def test_disallowed_language_rejected_by_api(self, client, session):
        """API 拒绝不允许的语言"""
        teacher = _user(session, "sb_teacher_lang_reject", UserRole.TEACHER)
        student = _user(session, "sb_student_lang_reject")
        course = _setup_course(session, teacher, student)

        token = _token(student)
        response = client.post(
            f"/api/v1/sandbox/course/{course.id}/execute",
            json={"source_code": "rm -rf /", "language": "bash"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    def test_cross_course_isolation(self, client, session):
        """跨课程隔离：学生A在课程1不能访问课程2的沙箱"""
        teacher1 = _user(session, "sb_t1", UserRole.TEACHER)
        teacher2 = _user(session, "sb_t2", UserRole.TEACHER)
        student1 = _user(session, "sb_s1")
        course1 = _setup_course(session, teacher1, student1)
        course2 = _setup_course(session, teacher2, _user(session, "sb_s2"))

        token = _token(student1)
        # 学生1访问课程2应被拒绝
        response = client.post(
            f"/api/v1/sandbox/course/{course2.id}/execute",
            json={"source_code": "print('hello')", "language": "python3"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_platform_admin_cross_course(self, client, session):
        """平台管理员可跨课程访问"""
        teacher = _user(session, "sb_admin_teacher", UserRole.TEACHER)
        student = _user(session, "sb_admin_student")
        course = _setup_course(session, teacher, student)

        admin = _user(session, "sb_platform_admin", UserRole.STUDENT)
        session.add(PlatformPermissionAssignment(
            user_id=admin.id,
            permission=PlatformPermission.ADMIN,
        ))
        session.commit()

        token = _token(admin)
        response = client.post(
            f"/api/v1/sandbox/course/{course.id}/execute",
            json={"source_code": "print('hello')", "language": "python3"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
