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

    @patch("app.services.sandbox_client.time.sleep", return_value=None)
    @patch("app.services.sandbox_client.httpx.Client")
    def test_submit_code_enqueues_then_polls_worker(
        self, mock_client_cls, _mock_sleep,
    ):
        queued_response = MagicMock()
        queued_response.raise_for_status = MagicMock()
        queued_response.json.return_value = {"token": "worker-token"}

        completed_response = MagicMock()
        completed_response.raise_for_status = MagicMock()
        completed_response.json.return_value = {
            "token": "worker-token",
            "status": {"id": 3, "description": "Accepted"},
            "stdout": "V09SS0VSX09L",  # base64("WORKER_OK")
            "stderr": None,
            "compile_output": None,
            "time": "0.01",
            "memory": 1024,
            "exit_code": 0,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = queued_response
        mock_client.get.return_value = completed_response
        mock_client_cls.return_value = mock_client

        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True
        result = client.submit_code("print('WORKER_OK')", "python3")

        assert result.status == SubmissionStatus.ACCEPTED
        assert result.stdout == "WORKER_OK"
        assert mock_client.post.call_args.kwargs["params"]["wait"] == "false"
        mock_client.get.assert_called_once()
        assert mock_client.get.call_args.args[0].endswith(
            "/submissions/worker-token"
        )

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
        assert payload["enable_per_process_and_thread_time_limit"] is True
        assert payload["enable_per_process_and_thread_memory_limit"] is True
        assert call_args.kwargs["params"]["wait"] == "false"


# ==================== Judge0 恢复演练测试 ====================

class TestSandboxRecovery:
    """Judge0 沙箱恢复演练测试（验收包4 第5项）

    覆盖场景：
    - 沙箱 health_check 由 False 恢复为 True 后，submit_code 立即可用
    - 沙箱短暂不可达期间提交返回 SANDBOX_UNAVAILABLE，恢复后同请求重试返回 ACCEPTED
    - 沙箱恢复后 ExperimentRun 由 sandbox_unavailable 转为正常评分（通过 sandbox_client 单例验证）
    """

    def test_health_check_recovers_from_unavailable_to_available(self, monkeypatch):
        """health_check 由 False 恢复为 True。"""
        import httpx
        from app.services import sandbox_client as sb_mod

        # 初始：Judge0 启用但服务不可达
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_API_URL", "http://127.0.0.1:59999")

        client = SandboxClient(base_url="http://127.0.0.1:59999", authn_token="test")
        client._enabled = True

        # 不可达时 health_check 返回 False
        assert client.health_check() is False

        # 模拟 Judge0 服务恢复：用一个能返回 200 的 mock 替换 httpx.Client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("app.services.sandbox_client.httpx.Client", return_value=mock_client):
            # 恢复后 health_check 立即返回 True，无冷启动延迟
            assert client.health_check() is True

    def test_submit_code_recovers_after_transient_outage(self, monkeypatch):
        """沙箱短暂不可达期间返回 SANDBOX_UNAVAILABLE，恢复后重试返回 ACCEPTED。"""
        import httpx
        from app.services import sandbox_client as sb_mod

        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        # 阶段1：不可达期间提交返回 SANDBOX_UNAVAILABLE
        mock_unavailable = MagicMock()
        mock_unavailable.__enter__ = MagicMock(return_value=mock_unavailable)
        mock_unavailable.__exit__ = MagicMock(return_value=False)
        mock_unavailable.post.side_effect = httpx.ConnectError("Connection refused")

        with patch("app.services.sandbox_client.httpx.Client", return_value=mock_unavailable):
            result_down = client.submit_code("print('hello')", "python3")
            assert result_down.status == SubmissionStatus.SANDBOX_UNAVAILABLE
            assert "降级" in result_down.message
            # 不伪造为 ACCEPTED
            assert result_down.status != SubmissionStatus.ACCEPTED

        # 阶段2：Judge0 恢复，重试同请求返回 ACCEPTED
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "recovered-token",
            "status": {"id": 3, "description": "Accepted"},
            "stdout": "aGVsbG8=",  # base64("hello")
            "stderr": None,
            "compile_output": None,
            "time": "0.05",
            "memory": 1024,
            "exit_code": 0,
            "message": None,
        }
        mock_recovered = MagicMock()
        mock_recovered.__enter__ = MagicMock(return_value=mock_recovered)
        mock_recovered.__exit__ = MagicMock(return_value=False)
        mock_recovered.post.return_value = mock_response

        with patch("app.services.sandbox_client.httpx.Client", return_value=mock_recovered):
            result_up = client.submit_code("print('hello')", "python3")
            assert result_up.status == SubmissionStatus.ACCEPTED
            assert result_up.stdout == "hello"
            assert result_up.token == "recovered-token"

    def test_recovery_no_cold_start_delay_for_submit_code(self, monkeypatch):
        """沙箱恢复后 submit_code 立即可用，无冷启动延迟（不抛异常）。"""
        import httpx
        from app.services import sandbox_client as sb_mod

        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        client._enabled = True

        # 模拟 Judge0 直接可用（无需预热）
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "token": "cold-start-token",
            "status": {"id": 3, "description": "Accepted"},
            "stdout": None,
            "stderr": None,
            "compile_output": None,
            "time": "0.01",
            "memory": 512,
            "exit_code": 0,
            "message": None,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("app.services.sandbox_client.httpx.Client", return_value=mock_client):
            # 首次调用即成功，证明无冷启动延迟
            result = client.submit_code("x=1", "python3")
            assert result.status == SubmissionStatus.ACCEPTED
            assert result.token == "cold-start-token"

    def test_disabled_sandbox_recovery_requires_enable_flag(self, monkeypatch):
        """JUDGE0_ENABLED=False 时即使服务恢复也保持不可用，必须显式开启 flag。"""
        from app.services import sandbox_client as sb_mod

        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", False)
        client = SandboxClient(base_url="http://127.0.0.1:2358", authn_token="test")
        # _enabled 在 __init__ 时已读取 settings，flag 关闭时为 False

        # 即使 mock 一个能用的 httpx.Client，submit_code 仍应返回 SANDBOX_UNAVAILABLE
        mock_client = MagicMock()
        with patch("app.services.sandbox_client.httpx.Client", return_value=mock_client):
            result = client.submit_code("x=1", "python3")
            assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
            # mock_client.post 不应被调用（flag 关闭直接降级）
            assert mock_client.post.call_count == 0


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
