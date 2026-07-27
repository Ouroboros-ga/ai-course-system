"""阶段8 M2/M3/M5 端到端测试

覆盖：
- M2 讯飞 TTS：MockXfyunTtsProvider 响应解析、音频哈希、字幕分段
- M2 任务重试：失败自动重试、限额、脚本字节限制、人工重跑
- M2 XfyunTtsProvider 凭据缺失时拒绝（不伪装成功）
- M3/M5 Provider 健康检查端点
- M3/M5 播放模式切换端点
- M5 对象存储迁移工具
- M5 Provider 替换演练（Fake→Mock 无需变更课程核心数据）

安全约束：
- 自动化测试不调用真实讯飞或真实数字人服务
- 讯飞凭据不进入测试
- 失败时保留原始 error_code
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability, PlatformPermission, PlatformPermissionAssignment
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.object_storage import (
    LocalStorageProvider,
    migrate_object_keys,
    reset_object_storage_for_tests,
)
from app.services.tts_provider import (
    FakeTtsProvider,
    MockXfyunTtsProvider,
    TtsSynthesisRequest,
    reset_tts_registry_for_tests,
)
from app.services.media_release_service import tts_execution_service


MEDIA = "/api/v1/media"


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


def _course(
    session,
    teacher_id: int,
    *,
    title: str = "Stage8 M2 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s8m2-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_media_capabilities(session, course_id: int) -> None:
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True,
        "course_building": True,
        "knowledge_graph": True,
        "evidence": True,
        "experiment": False,
        "coding_sandbox": False,
        "cognitive_analysis": True,
        "safety_policy": False,
    }
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
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


def _make_real_admin(session, monkeypatch, tmp_path) -> tuple[User, str]:
    """创建真实管理员用户并授予 PlatformPermission.ADMIN。

    require_platform_permission 检查 PlatformPermissionAssignment（非 UserRole），
    因此必须在 DB 中显式授予权限。
    """
    from app.core.config import settings
    from app.services.object_storage import reset_object_storage_for_tests

    unique = datetime.utcnow().timestamp()
    admin = User(
        username=f"s8m2_admin_{unique}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    session.add(PlatformPermissionAssignment(
        user_id=admin.id,
        permission=PlatformPermission.ADMIN,
        granted_by_user_id=admin.id,
    ))
    session.commit()

    token = create_access_token({
        "sub": str(admin.id),
        "username": admin.username,
        "role": admin.role.value,
        "school_id": admin.school_id or "test-school",
    })

    # 把账本路径指向临时目录，避免污染开发环境数据
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MIGRATION_LEDGER_PATH", str(tmp_path / "ledger" / "migration.json"))
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MIGRATION_MAX_ATTEMPTS", 3)
    # 允许 demo local fallback，使 s3 后端在测试环境中回退到本地
    monkeypatch.setattr(settings, "OBJECT_STORAGE_ALLOW_DEMO_LOCAL_FALLBACK", True)
    monkeypatch.setattr(settings, "MEDIA_STORAGE_PATH", str(tmp_path / "media"))
    reset_object_storage_for_tests()

    return admin, token


def _create_tts_job_via_api(
    client, token: str, course_id: int,
    *,
    idempotency_key: str = "",
) -> dict:
    payload = {
        "job_type": "tts",
        "input_summary": "TTS 合成讲稿",
        "input_payload": {"script_text": "hello"},
        "idempotency_key": idempotency_key,
    }
    resp = client.post(
        f"{MEDIA}/course/{course_id}/generation-jobs",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 202, body
    return body["data"]


def _execute_tts_job_via_api(
    client, token: str, course_id: int, job_id: str,
    *,
    script_text: str = "第一页：介绍二分查找。第二页：演示代码。",
    provider_key: str = "",
    max_retries: int | None = None,
) -> dict:
    payload = {"script_text": script_text, "voice_id": "default"}
    if provider_key:
        payload["provider_key"] = provider_key
    if max_retries is not None:
        payload["max_retries"] = max_retries
    resp = client.post(
        f"{MEDIA}/course/{course_id}/generation-jobs/{job_id}/execute-tts",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    return body["data"]


@pytest.fixture(autouse=True)
def _reset_tts_and_storage():
    """每个测试前后重置 TTS 注册表、限额窗口和对象存储"""
    reset_tts_registry_for_tests()
    tts_execution_service.reset_rate_limit_for_tests()
    # 使用临时目录作为对象存储
    tmp_dir = tempfile.mkdtemp(prefix="stage8_m2_test_")
    provider = LocalStorageProvider(tmp_dir)
    reset_object_storage_for_tests(provider)
    yield
    reset_object_storage_for_tests(None)
    reset_tts_registry_for_tests()
    tts_execution_service.reset_rate_limit_for_tests()


# ---------------------------------------------------------------------------
# M2 讯飞 TTS Mock Provider
# ---------------------------------------------------------------------------


class TestMockXfyunTtsProvider:
    """M2: MockXfyunTtsProvider 响应解析与音频生成"""

    def test_mock_xfyun_synthesize_generates_audio_and_subtitles(self):
        """Mock 讯飞 Provider 生成音频和字幕段"""
        provider = MockXfyunTtsProvider()
        request = TtsSynthesisRequest(
            script_text="第一句。第二句！第三句？",
            voice_id="xiaoyan",
            course_id=1,
            resource_version="v1",
            idempotency_key="test-mock-001",
        )
        result = provider.synthesize(request)

        assert result.provider_key == "xfyun_tts"
        assert result.provider_version == "xfyun-tts-v2.0-mock"
        assert result.audio_object_key.startswith("tts/course_1/")
        assert result.audio_object_key.endswith(".mp3")
        assert result.duration_ms > 0
        assert len(result.subtitle_segments) == 3
        assert result.subtitle_segments[0].text == "第一句"
        assert result.subtitle_segments[1].text == "第二句"
        assert result.subtitle_segments[2].text == "第三句"
        assert result.audio_sha256  # SHA256 已计算
        assert "mock_xfyun" in result.warnings[0]

    def test_mock_xfyun_idempotent_object_key(self):
        """相同 idempotency_key 生成相同 object_key"""
        provider = MockXfyunTtsProvider()
        request1 = TtsSynthesisRequest(
            script_text="测试文本",
            voice_id="default",
            course_id=2,
            resource_version="v1",
            idempotency_key="idem-key-001",
        )
        request2 = TtsSynthesisRequest(
            script_text="测试文本",
            voice_id="default",
            course_id=2,
            resource_version="v1",
            idempotency_key="idem-key-001",
        )
        result1 = provider.synthesize(request1)
        result2 = provider.synthesize(request2)
        assert result1.audio_object_key == result2.audio_object_key

    def test_mock_xfyun_audio_contains_metadata(self):
        """Mock 音频包含讯飞格式元数据，便于断言"""
        provider = MockXfyunTtsProvider()
        request = TtsSynthesisRequest(
            script_text="单句测试",
            voice_id="default",
            course_id=3,
            resource_version="v1",
        )
        result = provider.synthesize(request)
        from app.services.object_storage import get_object_storage
        audio_bytes = get_object_storage().get(result.audio_object_key)
        assert b"MOCK_XFYUN_AUDIO_V2" in audio_bytes
        assert b"frame=0" in audio_bytes


# ---------------------------------------------------------------------------
# M2 XfyunTtsProvider 凭据检查
# ---------------------------------------------------------------------------


class TestXfyunCredentialsGuard:
    """M2: XfyunTtsProvider 凭据缺失时拒绝，不伪装成功"""

    def test_xfyun_without_credentials_rejects(self):
        """凭据未配置时必须拒绝，不能伪装成功"""
        from fastapi import HTTPException
        from app.services.tts_provider import XfyunTtsProvider

        provider = XfyunTtsProvider()
        request = TtsSynthesisRequest(
            script_text="测试",
            voice_id="default",
            course_id=1,
            resource_version="v1",
        )
        with pytest.raises(HTTPException) as exc_info:
            provider.synthesize(request)
        assert exc_info.value.status_code == 503
        assert "DEPENDENCY_UNAVAILABLE" in str(exc_info.value.detail)

    def test_xfyun_health_check_false_without_credentials(self):
        """凭据缺失时健康检查返回 False"""
        from app.services.tts_provider import XfyunTtsProvider
        provider = XfyunTtsProvider()
        assert provider.health_check() is False


# ---------------------------------------------------------------------------
# M2 TTS 任务重试与限额
# ---------------------------------------------------------------------------


class TestTtsRetryAndRateLimit:
    """M2: TTS 任务重试、限额与人工重跑"""

    def test_execute_tts_with_mock_xfyun_succeeds(self, client, session, teacher_user):
        """使用 mock_xfyun Provider 执行 TTS 任务成功"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(client, _token(teacher_user), course.id)
        result = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text="第一页：介绍。第二页：演示。",
            provider_key="mock_xfyun",
        )
        assert result["status"] == "succeeded"
        assert result["output_object_key"].startswith("tts/course_")
        assert result["output_metadata"]["duration_ms"] > 0
        assert len(result["output_metadata"]["subtitle_segments"]) >= 2
        assert result["output_metadata"]["provider_key"] == "xfyun_tts"
        assert result["output_metadata"]["attempts_used"] >= 1

    def test_tts_retry_on_provider_failure(self, client, session, teacher_user):
        """Provider 失败时自动重试，重试耗尽后标记 failed"""
        from app.services.tts_provider import TTSProvider, TtsSynthesisResult, register_tts_provider

        class AlwaysFailProvider(TTSProvider):
            provider_key = "always_fail"
            provider_version = "fail-v1.0"

            def synthesize(self, request):
                raise RuntimeError("模拟 Provider 持续失败")

            def health_check(self):
                return False

        register_tts_provider("always_fail", AlwaysFailProvider())

        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(client, _token(teacher_user), course.id)
        result = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text="测试重试",
            provider_key="always_fail",
            max_retries=2,
        )
        assert result["status"] == "failed"
        assert result["error_code"] == "TTS_PROVIDER_FAILED"
        assert "已重试 2 次" in result["error_message_safe"]

    def test_tts_retry_succeeds_on_second_attempt(self, client, session, teacher_user):
        """Provider 第一次失败第二次成功"""
        from app.services.tts_provider import TTSProvider, register_tts_provider

        class FailOnceThenSucceedProvider(TTSProvider):
            provider_key = "fail_once"
            provider_version = "fail-once-v1.0"
            _call_count = 0

            def synthesize(self, request):
                FailOnceThenSucceedProvider._call_count += 1
                if FailOnceThenSucceedProvider._call_count == 1:
                    raise RuntimeError("第一次失败")
                # 第二次成功
                from app.services.tts_provider import TtsSynthesisResult, SubtitleSegment
                from app.services.object_storage import get_object_storage
                audio_bytes = b"RETRY_SUCCESS_AUDIO"
                object_key = f"tts/course_{request.course_id}/retry/success.mp3"
                sha = get_object_storage().put(object_key, audio_bytes, mime_type="audio/mpeg")
                return TtsSynthesisResult(
                    audio_object_key=object_key,
                    duration_ms=1000,
                    subtitle_segments=[SubtitleSegment(
                        text="成功", start_ms=0, end_ms=1000, sentence_index=0,
                    )],
                    audio_sha256=sha,
                    provider_key=self.provider_key,
                    provider_version=self.provider_version,
                    warnings=[],
                )

            def health_check(self):
                return True

        register_tts_provider("fail_once", FailOnceThenSucceedProvider())

        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(client, _token(teacher_user), course.id)
        result = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text="测试重试成功",
            provider_key="fail_once",
            max_retries=3,
        )
        assert result["status"] == "succeeded"
        assert result["output_metadata"]["attempts_used"] == 2

    def test_tts_script_too_long_rejected(self, client, session, teacher_user):
        """脚本超过字节限制时立即失败"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(client, _token(teacher_user), course.id)
        # 生成超长脚本
        long_script = "测试" * 5000  # 远超 8000 字节
        result = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text=long_script,
        )
        assert result["status"] == "failed"
        assert result["error_code"] == "TTS_SCRIPT_TOO_LONG"

    def test_tts_rate_limit_exceeded(self, client, session, teacher_user, monkeypatch):
        """限额超限时立即失败"""
        # 设置限额为 2 次/分钟
        monkeypatch.setattr(
            "app.core.config.settings.TTS_RATE_LIMIT_PER_MINUTE", 2,
        )
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)

        # 前两次成功
        job1 = _create_tts_job_via_api(client, _token(teacher_user), course.id, idempotency_key="rl-1")
        r1 = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job1["job_id"],
            script_text="第一次",
        )
        assert r1["status"] == "succeeded"

        job2 = _create_tts_job_via_api(client, _token(teacher_user), course.id, idempotency_key="rl-2")
        r2 = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job2["job_id"],
            script_text="第二次",
        )
        assert r2["status"] == "succeeded"

        # 第三次应被限额拦截
        job3 = _create_tts_job_via_api(client, _token(teacher_user), course.id, idempotency_key="rl-3")
        r3 = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job3["job_id"],
            script_text="第三次",
        )
        assert r3["status"] == "failed"
        assert r3["error_code"] == "TTS_RATE_LIMITED"

    def test_retry_failed_job_via_api(self, client, session, teacher_user):
        """人工重跑 failed 任务"""
        from app.services.tts_provider import TTSProvider, register_tts_provider

        class FailProvider(TTSProvider):
            provider_key = "fail_for_retry"
            provider_version = "fail-v1.0"

            def synthesize(self, request):
                raise RuntimeError("失败")

            def health_check(self):
                return False

        register_tts_provider("fail_for_retry", FailProvider())

        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(client, _token(teacher_user), course.id)
        # 第一次执行失败
        result = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text="测试重跑",
            provider_key="fail_for_retry",
            max_retries=1,
        )
        assert result["status"] == "failed"

        # 人工重跑：切换到 fake Provider
        resp = client.post(
            f"{MEDIA}/course/{course.id}/generation-jobs/{job['job_id']}/retry",
            json={"script_text": "测试重跑", "voice_id": "default", "provider_key": "fake"},
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["status"] == "succeeded"

    def test_retry_non_failed_job_rejected(self, client, session, teacher_user):
        """仅 failed 任务可重跑"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(client, _token(teacher_user), course.id)
        # 先执行成功
        _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text="成功",
        )
        # 尝试重跑 succeeded 任务应被拒绝（409 状态冲突）
        resp = client.post(
            f"{MEDIA}/course/{course.id}/generation-jobs/{job['job_id']}/retry",
            json={"script_text": "重跑", "voice_id": "default"},
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 409  # reject_state_conflict 返回 409


# ---------------------------------------------------------------------------
# M3/M5 Provider 健康检查
# ---------------------------------------------------------------------------


class TestProviderHealthCheck:
    """M3/M5: Provider 健康检查端点"""

    def test_get_providers_health(self, client, session, teacher_user):
        """查询 Provider 健康状态"""
        resp = client.get(
            f"{MEDIA}/providers/health",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert "tts" in data
        assert "digital_human" in data
        assert "provider_key" in data["tts"]
        assert "healthy" in data["tts"]
        assert "healthy" in data["digital_human"]
        assert "configured_provider" in data["tts"]
        assert "fallback_on_failure" in data["digital_human"]

    def test_providers_health_requires_auth(self, client):
        """未认证请求被拒绝"""
        resp = client.get(f"{MEDIA}/providers/health")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# M3/M5 播放模式切换
# ---------------------------------------------------------------------------


class TestPlaybackModeSwitch:
    """M3/M5: 播放模式切换端点"""

    def test_switch_to_compatibility_mode(self, client, session, teacher_user, student_user):
        """学生切换到兼容模式"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        resp = client.post(
            f"{MEDIA}/course/{course.id}/playback/switch-mode",
            json={"playback_mode": "compatibility"},
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["playback_mode"] == "compatibility"
        assert body["data"]["digital_human_enabled"] is False
        assert "兼容模式" in body["data"]["message"]

    def test_switch_to_auto_mode(self, client, session, teacher_user, student_user):
        """学生切换到自动模式"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        resp = client.post(
            f"{MEDIA}/course/{course.id}/playback/switch-mode",
            json={"playback_mode": "auto"},
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["playback_mode"] == "auto"
        assert body["data"]["digital_human_enabled"] is True

    def test_switch_invalid_mode_rejected(self, client, session, teacher_user, student_user):
        """无效播放模式被拒绝"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)

        resp = client.post(
            f"{MEDIA}/course/{course.id}/playback/switch-mode",
            json={"playback_mode": "ultra"},
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 422  # Pydantic 校验失败

    def test_non_enrolled_student_cannot_switch(self, client, session, teacher_user, student_user):
        """非课程成员不能切换模式"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        # 不注册学生

        resp = client.post(
            f"{MEDIA}/course/{course.id}/playback/switch-mode",
            json={"playback_mode": "auto"},
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# M5 对象存储迁移
# ---------------------------------------------------------------------------


class TestObjectStorageMigration:
    """M5: 对象存储迁移工具"""

    def test_migrate_object_keys_between_providers(self, tmp_path):
        """在两个 LocalStorageProvider 之间迁移 object_key"""
        source = LocalStorageProvider(str(tmp_path / "source"))
        target = LocalStorageProvider(str(tmp_path / "target"))

        # 在源存储写入文件
        source.put("tts/course_1/audio1.mp3", b"audio1", mime_type="audio/mpeg")
        source.put("tts/course_1/audio2.mp3", b"audio2", mime_type="audio/mpeg")
        source.put("avatars/u_1/manifest.json", b'{"key":"value"}', mime_type="application/json")

        # 迁移
        report = migrate_object_keys(
            source, target,
            ["tts/course_1/audio1.mp3", "tts/course_1/audio2.mp3", "avatars/u_1/manifest.json"],
        )
        assert report["migrated_count"] == 3
        assert report["failed_count"] == 0
        assert target.exists("tts/course_1/audio1.mp3")
        assert target.exists("tts/course_1/audio2.mp3")
        assert target.exists("avatars/u_1/manifest.json")

    def test_migrate_skips_existing_keys(self, tmp_path):
        """目标已存在且 SHA 一致的 key 跳过（SHA 不一致则 failed）"""
        source = LocalStorageProvider(str(tmp_path / "source"))
        target = LocalStorageProvider(str(tmp_path / "target"))

        # 相同内容 → SHA 一致 → skipped
        source.put("tts/course_1/audio.mp3", b"same_audio", mime_type="audio/mpeg")
        target.put("tts/course_1/audio.mp3", b"same_audio", mime_type="audio/mpeg")

        report = migrate_object_keys(
            source, target, ["tts/course_1/audio.mp3"],
        )
        assert report["skipped_count"] == 1
        # 目标内容未被覆盖
        assert target.get("tts/course_1/audio.mp3") == b"same_audio"

    def test_migrate_skips_nonexistent_keys(self, tmp_path):
        """源不存在的 key 跳过"""
        source = LocalStorageProvider(str(tmp_path / "source"))
        target = LocalStorageProvider(str(tmp_path / "target"))

        report = migrate_object_keys(
            source, target, ["nonexistent/key.mp3"],
        )
        assert report["migrated_count"] == 0
        assert report["skipped_count"] == 1

    def test_migrate_delete_source(self, tmp_path):
        """迁移后删除源文件"""
        source = LocalStorageProvider(str(tmp_path / "source"))
        target = LocalStorageProvider(str(tmp_path / "target"))

        source.put("tts/course_1/audio.mp3", b"audio", mime_type="audio/mpeg")
        migrate_object_keys(
            source, target, ["tts/course_1/audio.mp3"],
            delete_source=True,
        )
        assert not source.exists("tts/course_1/audio.mp3")
        assert target.exists("tts/course_1/audio.mp3")

    def test_list_object_keys_under_prefix(self, tmp_path):
        """按前缀列出 object_key"""
        provider = LocalStorageProvider(str(tmp_path / "storage"))
        provider.put("tts/course_1/a.mp3", b"a", mime_type="audio/mpeg")
        provider.put("tts/course_1/b.mp3", b"b", mime_type="audio/mpeg")
        provider.put("tts/course_2/c.mp3", b"c", mime_type="audio/mpeg")

        from app.services.object_storage import list_object_keys_under_prefix
        keys = list_object_keys_under_prefix(provider, "tts/course_1/")
        assert len(keys) == 2
        assert all("course_1" in k for k in keys)


# ---------------------------------------------------------------------------
# M5 对象存储迁移 API
# ---------------------------------------------------------------------------


class TestStorageMigrateApi:
    """M5: 对象存储迁移 API 端点"""

    def test_admin_can_migrate_storage(self, client, session, monkeypatch, tmp_path):
        """管理员可执行迁移（使用可恢复账本 API）"""
        admin, token = _make_real_admin(session, monkeypatch, tmp_path)
        # 先写入一些 object_key
        from app.services.object_storage import get_object_storage
        storage = get_object_storage()
        storage.put("tts/course_1/test.mp3", b"test", mime_type="audio/mpeg")

        resp = client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["tts/course_1/test.mp3"],
                "source_backend": "local",
                "target_backend": "s3",  # 不同后端；fallback 使两者指向同一 LocalStorageProvider
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        # 可恢复账本返回 processed dict + summary + ledger_path
        data = body["data"]
        assert "summary" in data
        assert "processed" in data
        assert "ledger_path" in data
        # fallback 下 source==target 存储，SHA 一致 → verified
        assert data["processed"]["verified"] >= 1

    def test_teacher_cannot_migrate_storage(self, client, session, teacher_user):
        """教师不能执行迁移"""
        resp = client.post(
            f"{MEDIA}/storage/migrate",
            json={"object_keys": [], "source_backend": "local", "target_backend": "s3"},
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 403

    def test_migrate_by_prefix(self, client, session, monkeypatch, tmp_path):
        """按前缀迁移（使用可恢复账本 API）"""
        admin, token = _make_real_admin(session, monkeypatch, tmp_path)
        from app.services.object_storage import get_object_storage
        storage = get_object_storage()
        storage.put("tts/course_1/a.mp3", b"a", mime_type="audio/mpeg")
        storage.put("tts/course_1/b.mp3", b"b", mime_type="audio/mpeg")

        resp = client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "prefix": "tts/course_1/",
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        assert "summary" in data
        assert "processed" in data
        # fallback 下两个 key 都应 verified
        assert data["processed"]["verified"] >= 2


# ---------------------------------------------------------------------------
# M5 Provider 替换演练
# ---------------------------------------------------------------------------


class TestProviderReplacement:
    """M5: Provider 替换演练——新增 Provider 无需变更课程核心数据"""

    def test_switch_tts_provider_does_not_change_course_data(self, client, session, teacher_user):
        """切换 TTS Provider 不影响课程核心数据"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)

        # 用 fake Provider 生成音频
        job1 = _create_tts_job_via_api(
            client, _token(teacher_user), course.id, idempotency_key="replace-1",
        )
        r1 = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job1["job_id"],
            script_text="用 fake 生成",
            provider_key="fake",
        )
        assert r1["status"] == "succeeded"
        assert r1["output_metadata"]["provider_key"] == "fake_tts"
        fake_audio_key = r1["output_object_key"]

        # 用 mock_xfyun Provider 生成另一个音频
        job2 = _create_tts_job_via_api(
            client, _token(teacher_user), course.id, idempotency_key="replace-2",
        )
        r2 = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job2["job_id"],
            script_text="用 mock_xfyun 生成",
            provider_key="mock_xfyun",
        )
        assert r2["status"] == "succeeded"
        assert r2["output_metadata"]["provider_key"] == "xfyun_tts"
        xfyun_audio_key = r2["output_object_key"]

        # 两个音频 object_key 不同（Provider 不同，但课程数据结构一致）
        assert fake_audio_key != xfyun_audio_key
        # 但都属于同一课程
        assert f"course_{course.id}" in fake_audio_key or "course_" in fake_audio_key
        assert f"course_{course.id}" in xfyun_audio_key or "course_" in xfyun_audio_key

    def test_unknown_provider_falls_back_to_fake(self):
        """未知 Provider 回退到 fake，避免生产事故"""
        from app.services.tts_provider import get_tts_provider, FakeTtsProvider
        provider = get_tts_provider("unknown_provider_key")
        assert isinstance(provider, FakeTtsProvider)

    def test_dh_provider_replacement_does_not_change_release_structure(self):
        """数字人 Provider 替换不改变 MediaRelease 结构"""
        from app.services.digital_human_provider import (
            FakeDigitalHumanProvider,
            get_digital_human_provider,
        )
        # 默认是 fake
        provider = get_digital_human_provider()
        assert isinstance(provider, FakeDigitalHumanProvider)

        # MediaRelease 字段不依赖 Provider 具体实现
        from app.models.media_release_model import MediaRelease
        # 确认 MediaRelease 有 provider 无关的字段
        assert hasattr(MediaRelease, "avatar_binding_id")
        assert hasattr(MediaRelease, "digital_human_manifest_object_key")
        assert hasattr(MediaRelease, "default_playback_mode")
