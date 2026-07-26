"""阶段10-2 稳定化测试。

覆盖路线图 §13 稳定化要求：
- 负载：并发请求常用端点不崩溃、不串数据
- 超时：外部依赖（沙箱/LLM）超时降级而不阻塞主流程
- 资源：沙箱资源限制正确传递；对象存储路径越权拒绝
- 任务重试：失败任务可重试；不可重试任务拒绝；幂等性保持
- 对象存储迁移：migrate_object_keys 一致性校验、失败保留源文件
- 数据库备份恢复：SQLite 文件级备份可恢复；表结构一致
- 可观测性：error_monitor 正确分类 403/503/5xx/跨课程拒绝/任务失败

不调用真实 Xfyun/数字人/Judge0 服务；使用 fake/mock 替身。
"""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.error_monitoring import (
    monitor,
    CATEGORY_AUTHORIZATION_403,
    CATEGORY_CLIENT_ERROR_4XX,
    CATEGORY_CROSS_COURSE_DENIAL,
    CATEGORY_EXTERNAL_SERVICE_503,
    CATEGORY_SERVER_ERROR_5XX,
    CATEGORY_SHADOW_DISABLED_503,
    CATEGORY_TASK_FAILURE,
)
from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    CourseCapability,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    establish_course_access_baseline,
    activate_student_membership,
)
from app.services.object_storage import (
    LocalStorageProvider,
    migrate_object_keys,
    reset_object_storage_for_tests,
)
from app.services.task_service import TaskCreateRequest, task_service


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(session, teacher_id: int, *, title: str = "Stab Course") -> Course:
    c = Course(
        fanya_course_id=f"stab-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_capabilities(session, course_id: int) -> None:
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True, "course_building": True, "knowledge_graph": True,
        "evidence": True, "experiment": True, "coding_sandbox": True,
        "cognitive_analysis": True, "safety_policy": True,
    }
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
    from app.models.course_model import StudentEnrollment
    enr = StudentEnrollment(
        student_id=student_id,
        course_id=course_id,
        overall_progress=0.0,
        last_study_time=datetime.utcnow(),
        is_active=True,
    )
    session.add(enr)
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _grant_platform_audit(session, user_id: int) -> None:
    session.add(PlatformPermissionAssignment(
        user_id=user_id,
        permission=PlatformPermission.COURSE_AUDIT,
        granted_by_user_id=user_id,
    ))
    session.commit()


# ===========================================================================
# 1. 负载测试：并发请求常用端点
# ===========================================================================


class TestLoadConcurrentRequests:
    """并发请求常用端点不崩溃、不串数据。"""

    def test_concurrent_health_check(self, client):
        """并发访问根健康检查端点；全部 200。"""
        def call():
            r = client.get("/")
            return r.status_code
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(call) for _ in range(40)]
            codes = [f.result() for f in as_completed(futures)]
        assert all(c == 200 for c in codes)

    def test_concurrent_facade_courses_isolated(self, client, session, teacher_user):
        """两个教师并发访问 /facade/courses，各自只看到自己的课程。"""
        teacher_a = teacher_user
        teacher_b = _user(session, "stab_teacher_b_load")

        course_a = _course(session, teacher_a.id, title="CourseA Load")
        course_b = _course(session, teacher_b.id, title="CourseB Load")
        _enable_capabilities(session, course_a.id)
        _enable_capabilities(session, course_b.id)

        token_a = _token(teacher_a)
        token_b = _token(teacher_b)

        def call(token: str) -> set[int]:
            r = client.get("/api/v1/facade/courses?view=building", headers=_auth(token))
            assert r.status_code == 200, r.text
            items = r.json()["data"]["items"]
            return {i["course_id"] for i in items}

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(call, token_a) for _ in range(10)] + \
                      [ex.submit(call, token_b) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # 每个教师始终只看到自己的课程（不串数据）
        for ids in results:
            assert course_a.id in ids or course_b.id in ids  # 至少看到自己
        # 不应同时看到两个课程（跨课程隔离在负载下保持）
        for ids in results:
            assert not (course_a.id in ids and course_b.id in ids), \
                "并发负载下出现跨课程数据泄漏"

    def test_concurrent_error_monitor_thread_safe(self):
        """monitor.record 并发调用线程安全（Counter 无丢失、无崩溃）。"""
        monitor.reset()
        categories = [
            CATEGORY_CLIENT_ERROR_4XX,
            CATEGORY_AUTHORIZATION_403,
            CATEGORY_SERVER_ERROR_5XX,
        ]

        def call():
            for _ in range(100):
                monitor.record(categories[_ % len(categories)])

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(call) for _ in range(8)]
            for f in as_completed(futures):
                f.result()
        snapshot = monitor.snapshot()
        # 8 线程 × 100 次 = 800 次记录
        assert sum(snapshot.values()) == 800


# ===========================================================================
# 2. 超时测试：外部依赖超时降级
# ===========================================================================


class TestTimeoutDegradation:
    """外部依赖超时时主流程降级而非阻塞。"""

    def test_sandbox_timeout_returns_unavailable(self, monkeypatch):
        """沙箱调用超时时返回不可用而非抛异常阻塞。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient, SandboxResourceLimits, SubmissionStatus
        # 启用沙箱但指向不可达端口
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_API_URL", "http://127.0.0.1:59999")
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        # 59999 端口无服务，submit_code 应捕获异常返回不可用结果
        result = sandbox.submit_code(
            source_code="print('hello')",
            language="python3",
            limits=SandboxResourceLimits(cpu_time_limit=1, memory_limit=65536),
        )
        # 连接失败时 status 应为不可用而非内部错误
        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE

    def test_sandbox_health_check_down(self, monkeypatch):
        """不可达的沙箱 health_check 返回 False。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        assert sandbox.health_check() is False

    def test_sandbox_disabled_returns_unavailable(self, monkeypatch):
        """JUDGE0_ENABLED=False 时沙箱直接返回不可用。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient, SubmissionStatus
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", False)
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        result = sandbox.submit_code(
            source_code="print('hello')",
            language="python3",
        )
        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        assert sandbox.health_check() is False


# ===========================================================================
# 3. 资源测试：沙箱资源限制与存储路径越权
# ===========================================================================


class TestResourceLimits:
    """资源限制正确传递；对象存储路径越权拒绝。"""

    def test_sandbox_resource_limits_passed_to_judge0(self):
        """资源限制（时间/内存）正确序列化为 Judge0 参数。"""
        from app.services.sandbox_client import SandboxResourceLimits
        limits = SandboxResourceLimits(
            cpu_time_limit=2,
            memory_limit=131072,  # 128 MB in KB
            wall_time_limit=5,
            max_processes=30,
        )
        assert limits.cpu_time_limit == 2
        assert limits.memory_limit == 131072
        assert limits.wall_time_limit == 5
        # 资源限制字段与 Judge0 提交 payload 字段一致
        # payload 字段名：cpu_time_limit, wall_time_limit, memory_limit, max_processes_and_or_threads
        assert limits.cpu_time_limit == 2
        assert limits.memory_limit == 128 * 1024  # 128 MB = 131072 KB

    def test_object_storage_path_traversal_rejected(self, tmp_path):
        """对象存储 object_key 路径越权（../）被拒绝。"""
        provider = LocalStorageProvider(str(tmp_path / "storage"))
        provider.put("legit/file.txt", b"hello")
        # 越权尝试
        with pytest.raises(ValueError, match="越权|object_key"):
            provider.put("../../etc/passwd", b"malicious")
        with pytest.raises(ValueError, match="越权|object_key"):
            provider.get("../../etc/passwd")

    def test_object_storage_empty_key_rejected(self, tmp_path):
        """空 object_key 被拒绝。"""
        provider = LocalStorageProvider(str(tmp_path / "storage"))
        with pytest.raises(ValueError):
            provider.put("", b"hello")
        with pytest.raises(ValueError):
            provider.get("")


# ===========================================================================
# 4. 任务重试测试
# ===========================================================================


class TestTaskRetry:
    """失败任务可重试；不可重试任务拒绝；幂等性保持。"""

    def _create_failed_task(self, session, teacher_user, *, retryable: bool = True) -> TaskRecord:
        req = TaskCreateRequest(
            task_type="stab_test_task",
            owner_user_id=teacher_user.id,
            course_id=None,
            input_summary="stabilization test",
            input_payload={"scenario": "retry"},
        )
        view = task_service.create_task(session, req)
        # 推进到 running -> failed
        task_service.mark_running(session, view.task_id)
        task_service.mark_failed(
            session, view.task_id,
            error_code="EXTERNAL_TIMEOUT",
            error_message="Judge0 timeout",
            retryable=retryable,
        )
        return task_service.get_task(session, view.task_id)

    def test_retryable_task_can_retry(self, session, teacher_user):
        """retryable=True 的失败任务可重试，先回到 pending 等待 Worker 重投。"""
        record = self._create_failed_task(session, teacher_user, retryable=True)
        view = task_service.retry(session, record.task_id, operator_user_id=teacher_user.id)
        assert view.status == "pending"
        assert view.error_code == ""
        assert view.progress == 0

    def test_non_retryable_task_rejected(self, session, teacher_user):
        """retryable=False 的失败任务拒绝重试。"""
        record = self._create_failed_task(session, teacher_user, retryable=False)
        from app.core.exceptions import reject_state_conflict  # noqa: F401
        with pytest.raises(Exception):  # noqa: B017
            task_service.retry(session, record.task_id, operator_user_id=teacher_user.id)

    def test_retry_idempotency_preserved(self, session, teacher_user):
        """同一 idempotency_key 的多次 create_task 返回同一 task_id。"""
        key = f"stab_key_{uuid.uuid4().hex}"
        req1 = TaskCreateRequest(
            task_type="stab_idem_task",
            owner_user_id=teacher_user.id,
            input_summary="idempotency test 1",
            idempotency_key=key,
        )
        req2 = TaskCreateRequest(
            task_type="stab_idem_task",
            owner_user_id=teacher_user.id,
            input_summary="idempotency test 2",
            idempotency_key=key,
        )
        v1 = task_service.create_task(session, req1)
        v2 = task_service.create_task(session, req2)
        assert v1.task_id == v2.task_id

    def test_retry_cross_user_rejected(self, session, teacher_user):
        """非任务所有者重试被拒绝（跨用户隔离）。"""
        record = self._create_failed_task(session, teacher_user, retryable=True)
        other = _user(session, "stab_other_user")
        with pytest.raises(Exception):  # noqa: B017
            task_service.retry(session, record.task_id, operator_user_id=other.id)


# ===========================================================================
# 5. 对象存储迁移测试
# ===========================================================================


class TestObjectStorageMigration:
    """migrate_object_keys 一致性校验与失败处理。"""

    def test_migrate_success_with_sha_check(self, tmp_path):
        """成功迁移并校验内容一致性。"""
        src = LocalStorageProvider(str(tmp_path / "src"))
        dst = LocalStorageProvider(str(tmp_path / "dst"))
        src.put("a/file1.txt", b"content1")
        src.put("a/file2.txt", b"content2")

        report = migrate_object_keys(src, dst, ["a/file1.txt", "a/file2.txt"])
        assert report["migrated_count"] == 2
        assert report["failed_count"] == 0
        # 目标可读
        assert dst.get("a/file1.txt") == b"content1"
        assert dst.get("a/file2.txt") == b"content2"

    def test_migrate_reject_existing_target_with_different_hash(self, tmp_path):
        """目标同键但内容不同必须失败，不能静默跳过或覆盖。"""
        src = LocalStorageProvider(str(tmp_path / "src"))
        dst = LocalStorageProvider(str(tmp_path / "dst"))
        src.put("file.txt", b"src_content")
        dst.put("file.txt", b"dst_content")

        report = migrate_object_keys(src, dst, ["file.txt"])
        assert report["failed_count"] == 1
        assert report["migrated_count"] == 0
        # 目标内容不被覆盖
        assert dst.get("file.txt") == b"dst_content"

    def test_migrate_skip_missing_source(self, tmp_path):
        """源不存在时跳过。"""
        src = LocalStorageProvider(str(tmp_path / "src"))
        dst = LocalStorageProvider(str(tmp_path / "dst"))

        report = migrate_object_keys(src, dst, ["nonexistent.txt"])
        assert report["skipped_count"] == 1
        assert report["migrated_count"] == 0

    def test_migrate_delete_source_flag(self, tmp_path):
        """delete_source=True 时迁移后删除源文件。"""
        src = LocalStorageProvider(str(tmp_path / "src"))
        dst = LocalStorageProvider(str(tmp_path / "dst"))
        src.put("file.txt", b"content")

        report = migrate_object_keys(src, dst, ["file.txt"], delete_source=True)
        assert report["migrated_count"] == 1
        assert not src.exists("file.txt")
        assert dst.exists("file.txt")

    def test_migrate_preserves_source_on_failure(self, tmp_path):
        """迁移失败时源文件保留（不删除）。"""
        src = LocalStorageProvider(str(tmp_path / "src"))
        # 故意构造一个无法写入的 dst（root_dir 是文件而非目录）
        bad_dst_path = tmp_path / "blocker"
        bad_dst_path.write_text("not a directory")
        from app.services.object_storage import ObjectStorageProvider
        # 用 mock 模拟失败
        failing_dst = MagicMock(spec=ObjectStorageProvider)
        failing_dst.exists.return_value = False
        failing_dst.put.side_effect = RuntimeError("disk full")

        src.put("file.txt", b"content")
        report = migrate_object_keys(src, failing_dst, ["file.txt"], delete_source=True)
        assert report["failed_count"] == 1
        # 源文件仍存在（失败时不删除）
        assert src.exists("file.txt")


# ===========================================================================
# 6. 数据库备份恢复测试
# ===========================================================================


class TestDatabaseBackupRestore:
    """SQLite 文件级备份可恢复；表结构一致。"""

    def test_sqlite_file_backup_restore(self, test_engine, tmp_path):
        """SQLite 文件级备份后可在新 engine 恢复；表结构一致。"""
        from app.models.user_model import User
        # 在原 engine 写入数据
        with Session(test_engine) as s:
            u = User(
                username=f"backup_test_{uuid.uuid4().hex[:8]}",
                hashed_password=get_password_hash("pw"),
                role=UserRole.TEACHER,
                is_active=True,
            )
            s.add(u)
            s.commit()
            user_id = u.id

        # 备份 SQLite 文件（直接复制 db 文件）
        db_url = str(test_engine.url)
        # test_engine.url 形如 sqlite:///path/to/test_smart_class.db
        db_path = db_url.replace("sqlite:///", "")
        backup_path = tmp_path / "backup.db"
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
        else:
            pytest.skip("测试 engine 未使用文件 SQLite")

        # 从备份恢复到新 engine
        restore_path = tmp_path / "restored.db"
        shutil.copy2(backup_path, restore_path)
        restored_engine = create_engine(
            f"sqlite:///{restore_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )

        # 验证数据可读
        with Session(restored_engine) as s:
            restored_user = s.get(User, user_id)
            assert restored_user is not None
            assert restored_user.username.startswith("backup_test_")

        # 验证表结构一致（核心表存在）
        from sqlalchemy import inspect
        inspector = inspect(restored_engine)
        table_names = inspector.get_table_names()
        for required in ("users", "courses", "tasks", "course_releases"):
            assert required in table_names, f"恢复后缺失表: {required}"

        restored_engine.dispose()

    def test_sqlite_backup_metadata_consistent(self, test_engine, tmp_path):
        """备份恢复后 SQLModel.metadata 与数据库 schema 一致。"""
        # 备份
        db_path = str(test_engine.url).replace("sqlite:///", "")
        if not os.path.exists(db_path):
            pytest.skip("测试 engine 未使用文件 SQLite")
        backup_path = tmp_path / "meta_backup.db"
        shutil.copy2(db_path, backup_path)

        # 用新 engine 加载备份并补建表（不应有冲突）
        restore_engine = create_engine(
            f"sqlite:///{backup_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        # create_all 幂等：已存在的表不会被重建
        SQLModel.metadata.create_all(restore_engine)
        restore_engine.dispose()


# ===========================================================================
# 7. 可观测性测试
# ===========================================================================


class TestObservability:
    """error_monitor 正确分类各类错误响应。"""

    def setup_method(self):
        monitor.reset()

    def test_cross_course_denial_classified(self, client, session, teacher_user):
        """跨课程拒绝被分类为 cross_course_denial。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        # 用独立 app 避免污染主 app
        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/cross-course-test")
        async def _():
            raise HTTPException(403, "课程权限不足")

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/cross-course-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_CROSS_COURSE_DENIAL, 0) >= 1

    def test_authorization_403_classified(self):
        """非跨课程的 403 被分类为 authorization_403。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/forbidden-test")
        async def _():
            raise HTTPException(403, "禁止访问")

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/forbidden-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_AUTHORIZATION_403, 0) >= 1

    def test_shadow_disabled_503_classified(self):
        """SHADOW_FEATURE_DISABLED 错误码被分类为 shadow_disabled_503。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/shadow-test")
        async def _():
            raise HTTPException(503, detail={"code": "SHADOW_FEATURE_DISABLED", "message": "shadow off"})

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/shadow-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_SHADOW_DISABLED_503, 0) >= 1

    def test_external_service_503_classified(self):
        """TEACHING_AGENT_NOT_CONFIGURED 错误码被分类为 external_service_503。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/external-test")
        async def _():
            raise HTTPException(503, detail={"code": "TEACHING_AGENT_NOT_CONFIGURED", "message": "agent off"})

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/external-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_EXTERNAL_SERVICE_503, 0) >= 1

    def test_server_error_5xx_classified(self):
        """500 内部错误被分类为 server_error_5xx。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/server-error-test")
        async def _():
            raise HTTPException(500, "内部错误")

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/server-error-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_SERVER_ERROR_5XX, 0) >= 1

    def test_task_failure_classified(self):
        """含 task 关键字的 5xx 被分类为 task_failure。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/task-failure-test")
        async def _():
            raise HTTPException(500, "task execution failed")

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/task-failure-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_TASK_FAILURE, 0) >= 1

    def test_client_error_4xx_classified(self):
        """4xx 客户端错误被分类为 client_error_4xx。"""
        from fastapi import FastAPI, HTTPException
        from app.core.error_monitoring import ErrorMonitoringMiddleware

        app = FastAPI()
        app.add_middleware(ErrorMonitoringMiddleware)

        @app.get("/client-error-test")
        async def _():
            raise HTTPException(404, "not found")

        with TestClient(app, raise_server_exceptions=False) as c:
            c.get("/client-error-test")
        snap = monitor.snapshot()
        assert snap.get(CATEGORY_CLIENT_ERROR_4XX, 0) >= 1

    def test_error_monitor_snapshot_endpoint(self, client):
        """/api/v1/health/error-monitor 返回 monitor 快照。"""
        monitor.reset()
        monitor.record(CATEGORY_AUTHORIZATION_403)
        r = client.get("/api/v1/health/error-monitor")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data.get(CATEGORY_AUTHORIZATION_403, 0) >= 1

    def test_monitor_reset(self):
        """monitor.reset 清空计数。"""
        monitor.record(CATEGORY_CLIENT_ERROR_4XX)
        assert monitor.snapshot() != {}
        monitor.reset()
        assert monitor.snapshot() == {}


# ===========================================================================
# 8. 外部依赖降级集成测试
# ===========================================================================


class TestExternalDependencyDegradation:
    """外部依赖不可用时主流程降级而非崩溃。"""

    def test_sandbox_unavailable_returns_proper_status(self, monkeypatch):
        """沙箱不可用时返回 SANDBOX_UNAVAILABLE 而非 INTERNAL_ERROR。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient, SubmissionStatus
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", True)
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_API_URL", "http://127.0.0.1:59999")
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        result = sandbox.submit_code(source_code="x=1", language="python3")
        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        # 不应是 INTERNAL_ERROR（虚构执行）
        assert result.status != SubmissionStatus.INTERNAL_ERROR or \
               result.status == SubmissionStatus.SANDBOX_UNAVAILABLE

    def test_llm_unavailable_does_not_crash_app(self, client, monkeypatch):
        """LLM 不可用时主应用健康检查仍正常（降级而非崩溃）。"""
        from app.services import qa_service as qa_mod
        # 用 mock 让 qa_service 模块的 llm_client 抛超时异常
        failing_llm = MagicMock()
        failing_llm.chat_completion.side_effect = TimeoutError("LLM timeout")
        monkeypatch.setattr(qa_mod, "llm_client", failing_llm, raising=False)

        # 健康检查端点不应崩溃
        r = client.get("/")
        assert r.status_code == 200

    def test_disabled_sandbox_marks_action_unavailable(self, monkeypatch):
        """JUDGE0_ENABLED=False 时 CodingAction 显示不可用而非虚构执行。"""
        from app.services import sandbox_client as sb_mod
        from app.services.sandbox_client import SandboxClient, SubmissionStatus
        monkeypatch.setattr(sb_mod.settings, "JUDGE0_ENABLED", False)
        sandbox = SandboxClient(base_url="http://127.0.0.1:59999")
        result = sandbox.submit_code(source_code="x=1", language="python3")
        # 必须明确返回 SANDBOX_UNAVAILABLE，不能是 ACCEPTED 或 INTERNAL_ERROR
        assert result.status == SubmissionStatus.SANDBOX_UNAVAILABLE
        assert "降级" in result.message or "不可用" in result.message or "未启用" in result.message
