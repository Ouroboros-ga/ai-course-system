"""阶段8 媒体生成与发布端到端测试

覆盖路线图 §11 验收与 PageDesign前端API契约规划.md §3.11：
- TTS 任务创建/执行（Fake Provider）：生成音频资产 + 字幕分段
- MediaRelease 创建/冻结 Cue/激活/回滚/撤回
- 学生端 playback：返回音频+字幕+PPT 时间轴
- 三档播放模式（auto/low_resource/compatibility）
- 数字人未绑定走兼容模式
- 跨课程拒绝（403/404）
- 任务失败保留原始 error_code（不伪装成功）
- idempotency_key 幂等
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.media_release_model import (
    MediaGenerationJob,
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaRelease,
    MediaReleaseStatus,
)
from app.models.media_timeline_model import (
    CueType,
    MediaAsset,
    MediaTimelineCue,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.object_storage import (
    LocalStorageProvider,
    build_object_storage_provider,
    get_object_storage,
    reset_object_storage_for_tests,
    resolve_local_storage_root,
)
from app.services.tts_provider import (
    FakeTtsProvider,
    reset_tts_registry_for_tests,
)


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
    title: str = "Stage8 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s8-{teacher_id}-{datetime.utcnow().timestamp()}",
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


def _create_tts_job_via_api(
    client, token: str, course_id: int,
    *,
    idempotency_key: str = "",
    input_payload: dict | None = None,
) -> dict:
    payload = {
        "job_type": "tts",
        "input_summary": "TTS 合成讲稿",
        "input_payload": input_payload or {"script_text": "hello"},
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
    *, script_text: str = "第一页：介绍二分查找。第二页：演示代码。",
) -> dict:
    resp = client.post(
        f"{MEDIA}/course/{course_id}/generation-jobs/{job_id}/execute-tts",
        json={"script_text": script_text, "voice_id": "default"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    return body["data"]


def test_relative_local_storage_path_is_backend_rooted(monkeypatch, tmp_path):
    """Starting the API at the repo root or backend/ must address one tree."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "MEDIA_STORAGE_PATH", "./media")
    resolved = resolve_local_storage_root(settings.MEDIA_STORAGE_PATH)
    assert resolved.replace("\\", "/").endswith("/backend/media")
    assert build_object_storage_provider("local").root_dir == resolved

    explicit = str(tmp_path / "isolated-media")
    assert resolve_local_storage_root(explicit) == explicit
    assert LocalStorageProvider(explicit).root_dir == explicit


def _create_release_via_api(
    client, token: str, course_id: int,
    *,
    label: str = "v1",
    audio_object_key: str | None = None,
    default_playback_mode: str = "auto",
) -> dict:
    payload = {
        "label": label,
        "default_playback_mode": default_playback_mode,
    }
    if audio_object_key:
        payload["audio_object_key"] = audio_object_key
    resp = client.post(
        f"{MEDIA}/course/{course_id}/releases",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


def _seed_timeline_cues(session, course_id: int, node_id: int = 1) -> list[MediaTimelineCue]:
    """直接落库 MediaTimelineCue 用于 freeze-cues 测试"""
    cues = [
        MediaTimelineCue(
            course_id=course_id,
            script_id=1,
            node_id=node_id,
            cue_index=0,
            start_time=0.0,
            end_time=3.5,
            cue_type=CueType.NARRATION,
            ppt_page=1,
            subtitle_text="第一页：介绍二分查找。",
            audio_object_key=f"tts/course_{course_id}/cue_0.mp3",
            resource_version="v1",
            is_active=True,
        ),
        MediaTimelineCue(
            course_id=course_id,
            script_id=1,
            node_id=node_id,
            cue_index=1,
            start_time=3.5,
            end_time=7.0,
            cue_type=CueType.NARRATION,
            ppt_page=2,
            subtitle_text="第二页：演示代码。",
            audio_object_key=f"tts/course_{course_id}/cue_1.mp3",
            resource_version="v1",
            is_active=True,
        ),
    ]
    for c in cues:
        session.add(c)
    session.commit()
    return cues


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_providers():
    """每个测试前后重置 TTS / 对象存储单例，避免状态污染"""
    reset_tts_registry_for_tests()
    reset_object_storage_for_tests()
    yield
    reset_tts_registry_for_tests()
    reset_object_storage_for_tests()


# ---------------------------------------------------------------------------
# TTS 生成任务
# ---------------------------------------------------------------------------


class TestTtsGenerationJob:
    """TTS 生成任务：创建/执行/幂等/失败保留原因"""

    def test_create_tts_job_returns_202_with_task_id(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        data = _create_tts_job_via_api(
            client, _token(teacher_user), course.id,
            idempotency_key="tts-1",
        )
        assert data["job_id"].startswith("mgj_")
        assert data["task_id"]
        assert data["status"] == "pending"
        assert data["job_type"] == "tts"

    def test_execute_tts_job_with_fake_provider_succeeds(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        job = _create_tts_job_via_api(
            client, _token(teacher_user), course.id,
            idempotency_key="tts-exec-1",
        )
        result = _execute_tts_job_via_api(
            client, _token(teacher_user), course.id, job["job_id"],
            script_text="第一页：介绍二分查找。第二页：演示代码。",
        )
        assert result["status"] == "succeeded"
        assert result["output_object_key"].startswith("tts/course_")
        assert result["output_metadata"]["duration_ms"] > 0
        assert len(result["output_metadata"]["subtitle_segments"]) >= 2
        assert result["output_metadata"]["audio_sha256"]
        assert result["output_metadata"]["provider_key"] == "fake_tts"
        assert result["output_metadata"]["provider_version"] == "fake-v1.1-playable"
        assert result["output_object_key"].endswith(".wav")

        # Fake TTS is intentionally not speech, but the emitted diagnostic
        # track must be a real browser-decodable WAV and remain course-scoped.
        asset = session.exec(select(MediaAsset).where(
            MediaAsset.object_key == result["output_object_key"],
        )).first()
        assert asset is not None
        assert asset.course_id == course.id
        assert asset.mime_type == "audio/wav"
        raw_audio = get_object_storage().get(asset.object_key)
        assert raw_audio[:4] == b"RIFF"
        assert raw_audio[8:12] == b"WAVE"

        content = client.get(
            f"{MEDIA}/assets/{asset.object_key}/content",
            params={"token": _token(teacher_user)},
        )
        assert content.status_code == 200, content.text
        assert content.headers["content-type"].startswith("audio/wav")
        assert content.content[:4] == b"RIFF"
        assert content.content[8:12] == b"WAVE"


    def test_idempotency_key_deduplicates(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        first = _create_tts_job_via_api(
            client, token, course.id, idempotency_key="idem-1",
        )
        second = _create_tts_job_via_api(
            client, token, course.id, idempotency_key="idem-1",
        )
        assert first["job_id"] == second["job_id"]

    def test_same_tts_input_reuses_persisted_media_cache(self, client, session, teacher_user):
        """A new job with the same normalized TTS input must not synthesize twice."""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        script = "相同讲稿应命中同一份已生成音频。"

        first_job = _create_tts_job_via_api(
            client, token, course.id, idempotency_key="cache-first",
        )
        first = _execute_tts_job_via_api(
            client, token, course.id, first_job["job_id"], script_text=script,
        )
        assert first["status"] == "succeeded"
        assert first["output_metadata"]["cache_hit"] is False

        second_job = _create_tts_job_via_api(
            client, token, course.id, idempotency_key="cache-second",
        )
        second = _execute_tts_job_via_api(
            client, token, course.id, second_job["job_id"], script_text=script,
        )
        assert second["status"] == "succeeded"
        assert second["output_metadata"]["cache_hit"] is True
        assert second["output_metadata"]["cache_source_job_id"] == first_job["job_id"]
        assert second["output_object_key"] == first["output_object_key"]

    def test_cache_hit_restores_missing_media_asset_ledger(self, client, session, teacher_user):
        """A cache hit must repair pre-ledger rows without resynthesizing audio."""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        script = "缓存资产台账兼容验证。"

        first_job = _create_tts_job_via_api(client, token, course.id, idempotency_key="ledger-first")
        first = _execute_tts_job_via_api(client, token, course.id, first_job["job_id"], script_text=script)
        asset = session.exec(select(MediaAsset).where(
            MediaAsset.object_key == first["output_object_key"],
        )).first()
        assert asset is not None
        session.delete(asset)
        session.commit()

        second_job = _create_tts_job_via_api(client, token, course.id, idempotency_key="ledger-second")
        second = _execute_tts_job_via_api(client, token, course.id, second_job["job_id"], script_text=script)
        assert second["output_metadata"]["cache_hit"] is True
        repaired = session.exec(select(MediaAsset).where(
            MediaAsset.object_key == first["output_object_key"],
        )).first()
        assert repaired is not None
        assert repaired.course_id == course.id

    def test_student_cannot_create_tts_job(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        resp = client.post(
            f"{MEDIA}/course/{course.id}/generation-jobs",
            json={"job_type": "tts", "input_payload": {}},
            headers=_auth(_token(student_user)),
        )
        # 学生无 course.media.generate 权限
        assert resp.status_code == 403

    def test_cross_course_access_denied(self, client, session, teacher_user):
        c1 = _course(session, teacher_user.id, title="c1")
        c2 = _course(session, teacher_user.id, title="c2")
        _enable_media_capabilities(session, c1.id)
        _enable_media_capabilities(session, c2.id)
        job = _create_tts_job_via_api(
            client, _token(teacher_user), c1.id, idempotency_key="cross-1",
        )
        # 用 c2 的 course_id 访问 c1 的 job
        resp = client.get(
            f"{MEDIA}/course/{c2.id}/generation-jobs/{job['job_id']}",
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 404  # 跨课程拒绝


# ---------------------------------------------------------------------------
# MediaRelease 发布与回滚
# ---------------------------------------------------------------------------


class TestMediaReleaseLifecycle:
    """媒体发布版本生命周期：草稿→激活→撤回→回滚"""

    def test_create_release_as_draft(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        data = _create_release_via_api(
            client, _token(teacher_user), course.id,
            label="首版", audio_object_key="tts/course_1/full.mp3",
        )
        assert data["release_id"].startswith("mrel_")
        assert data["version_number"] == 1
        assert data["status"] == "draft"
        assert data["audio_object_key"] == "tts/course_1/full.mp3"

    def test_activate_release_supersedes_old_active(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        r1 = _create_release_via_api(client, token, course.id, label="v1")
        r2 = _create_release_via_api(client, token, course.id, label="v2")

        # 激活 v1
        resp = client.post(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/activate",
            headers=_auth(token),
        )
        assert resp.json()["data"]["status"] == "active"

        # 激活 v2，v1 应被 superseded
        resp = client.post(
            f"{MEDIA}/course/{course.id}/releases/{r2['release_id']}/activate",
            headers=_auth(token),
        )
        assert resp.json()["data"]["status"] == "active"

        # /releases/current 应返回 v2
        resp = client.get(
            f"{MEDIA}/course/{course.id}/releases/current",
            headers=_auth(token),
        )
        assert resp.json()["data"]["release_id"] == r2["release_id"]

    def test_rollback_to_superseded_release(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        r1 = _create_release_via_api(client, token, course.id, label="v1")
        r2 = _create_release_via_api(client, token, course.id, label="v2")

        client.post(f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/activate", headers=_auth(token))
        client.post(f"{MEDIA}/course/{course.id}/releases/{r2['release_id']}/activate", headers=_auth(token))

        # 回滚到 v1
        resp = client.post(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/rollback",
            headers=_auth(token),
        )
        assert resp.json()["data"]["status"] == "active"

        resp = client.get(f"{MEDIA}/course/{course.id}/releases/current", headers=_auth(token))
        assert resp.json()["data"]["release_id"] == r1["release_id"]

    def test_withdraw_release_hides_from_current(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        r1 = _create_release_via_api(client, token, course.id, label="v1")
        client.post(f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/activate", headers=_auth(token))

        # 撤回
        resp = client.post(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/withdraw",
            headers=_auth(token),
        )
        assert resp.json()["data"]["status"] == "withdrawn"

        # /releases/current 不应返回该版本
        resp = client.get(f"{MEDIA}/course/{course.id}/releases/current", headers=_auth(token))
        assert resp.json()["data"]["available"] is False

    def test_freeze_cues_creates_snapshot(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)

        # 落库 MediaTimelineCue
        _seed_timeline_cues(session, course.id)

        r1 = _create_release_via_api(client, token, course.id, label="v1")
        resp = client.post(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/freeze-cues",
            json={"cue_ids": []},
            headers=_auth(token),
        )
        body = resp.json()
        assert body["data"]["frozen_count"] == 2
        assert body["data"]["timeline_content_hash"]

        # 详情应包含 cue 快照
        resp = client.get(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}",
            headers=_auth(token),
        )
        cues = resp.json()["data"]["cues"]
        assert len(cues) == 2
        assert cues[0]["ppt_page"] == 1
        assert "二分查找" in cues[0]["subtitle_text"]

    def test_avatar_cues_endpoint_submits_one_non_billable_worker(
        self, client, session, teacher_user, monkeypatch,
    ):
        """P2 endpoint only dispatches a Cue Worker; it never re-runs TTS."""
        from app.platform.tasks.worker import local_task_worker

        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        source = client.post(
            f"{MEDIA}/course/{course.id}/generation-jobs",
            json={
                "job_type": "tts",
                "node_id": 1,
                "input_payload": {"script_text": "P2 cue fixture"},
                "idempotency_key": "p2-cue-source",
            },
            headers=_auth(token),
        ).json()["data"]
        _execute_tts_job_via_api(
            client, token, course.id, source["job_id"], script_text="P2 Cue 讲解。",
        )
        release = _create_release_via_api(client, token, course.id, label="P2 Cue")

        submitted: list[tuple[str, dict]] = []

        def capture_submit(_session_factory, task_id, payload):
            submitted.append((task_id, payload))
            return None

        monkeypatch.setattr(local_task_worker, "submit", capture_submit)
        endpoint = f"{MEDIA}/course/{course.id}/releases/{release['release_id']}/avatar-cues"
        resp = client.post(
            endpoint,
            json={"tts_job_id": source["job_id"]},
            headers=_auth(token),
        )
        body = resp.json()
        assert resp.status_code == 200, resp.text
        assert body["code"] == 202
        assert body["data"]["job_type"] == "timeline_publish"
        assert body["data"]["async"] is True
        assert len(submitted) == 1
        assert submitted[0][1]["source_tts_job_id"] == source["job_id"]

        # Same release/source pair is idempotent and must not enqueue a second
        # worker before the first queued task has been claimed.
        second = client.post(endpoint, json={"tts_job_id": source["job_id"]}, headers=_auth(token))
        assert second.json()["data"]["job_id"] == body["data"]["job_id"]
        assert len(submitted) == 1

    def test_student_can_read_releases_but_not_create(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)
        stu_token = _token(student_user)

        r1 = _create_release_via_api(client, token, course.id, label="v1")
        client.post(f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/activate", headers=_auth(token))

        # 学生可读
        resp = client.get(f"{MEDIA}/course/{course.id}/releases/current", headers=_auth(stu_token))
        assert resp.json()["data"]["release_id"] == r1["release_id"]

        # 学生不可创建
        resp = client.post(
            f"{MEDIA}/course/{course.id}/releases",
            json={"label": "hack"},
            headers=_auth(stu_token),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 学生端统一播放清单
# ---------------------------------------------------------------------------


class TestPlaybackManifest:
    """学生端播放清单：音频+字幕+PPT 时间轴+三档模式"""

    def test_playback_returns_audio_subtitle_ppt_timeline(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)
        stu_token = _token(student_user)

        _seed_timeline_cues(session, course.id)
        r1 = _create_release_via_api(
            client, token, course.id,
            label="v1", audio_object_key="tts/course_1/full.mp3",
        )
        client.post(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/freeze-cues",
            json={"cue_ids": []}, headers=_auth(token),
        )
        client.post(f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/activate", headers=_auth(token))

        resp = client.get(f"{MEDIA}/course/{course.id}/playback", headers=_auth(stu_token))
        body = resp.json()["data"]
        assert body["available"] is True
        assert body["audio_url"]  # 签名 URL
        assert len(body["subtitle_segments"]) == 2
        assert len(body["ppt_timeline"]) == 2
        assert body["ppt_timeline"][0]["ppt_page"] == 1
        assert body["default_playback_mode"] == "auto"

    def test_playback_without_digital_human_falls_back_to_compatibility(
        self, client, session, teacher_user, student_user,
    ):
        """未绑定数字人时 fallback_mode 应为 compatibility"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)
        stu_token = _token(student_user)

        _seed_timeline_cues(session, course.id)
        r1 = _create_release_via_api(client, token, course.id, label="v1")
        client.post(
            f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/freeze-cues",
            json={"cue_ids": []}, headers=_auth(token),
        )
        client.post(f"{MEDIA}/course/{course.id}/releases/{r1['release_id']}/activate", headers=_auth(token))

        resp = client.get(f"{MEDIA}/course/{course.id}/playback", headers=_auth(stu_token))
        body = resp.json()["data"]
        # 未绑定数字人 → manifest 为 None，fallback_mode 为 compatibility
        assert body["digital_human_manifest"] is None
        assert body["fallback_mode"] == "compatibility"

    def test_playback_when_no_active_release(self, client, session, teacher_user, student_user):
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        resp = client.get(f"{MEDIA}/course/{course.id}/playback", headers=_auth(_token(student_user)))
        body = resp.json()["data"]
        assert body["available"] is False
        assert body["reason"] == "no_active_release"

    def test_three_playback_modes_supported(self, client, session, teacher_user):
        """验证 auto/low_resource/compatibility 三档模式都接受"""
        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)
        for mode in ["auto", "low_resource", "compatibility"]:
            data = _create_release_via_api(
                client, token, course.id,
                label=f"mode-{mode}", default_playback_mode=mode,
            )
            assert data["default_playback_mode"] == mode


# ---------------------------------------------------------------------------
# 任务失败保留原因
# ---------------------------------------------------------------------------


class TestTaskFailureSemantics:
    """任务失败必须保留原始 error_code，禁止伪装成功"""

    def test_tts_failure_preserves_error_code(self, client, session, teacher_user):
        """注册一个总是失败的 TTS Provider，验证失败时 error_code 写入"""
        from app.services.tts_provider import (
            TTSProvider,
            TtsSynthesisRequest,
            TtsSynthesisResult,
            register_tts_provider,
        )

        class AlwaysFailTtsProvider(TTSProvider):
            provider_key = "always_fail"
            provider_version = "fail-v1.0"

            def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
                raise RuntimeError("讯飞服务不可用 (503)")

        register_tts_provider("always_fail", AlwaysFailTtsProvider())

        course = _course(session, teacher_user.id)
        _enable_media_capabilities(session, course.id)
        token = _token(teacher_user)

        job = _create_tts_job_via_api(
            client, token, course.id, idempotency_key="fail-1",
        )
        resp = client.post(
            f"{MEDIA}/course/{course.id}/generation-jobs/{job['job_id']}/execute-tts",
            json={
                "script_text": "测试失败",
                "voice_id": "default",
                "provider_key": "always_fail",
            },
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200  # HTTP 200，但任务状态为 failed
        data = body["data"]
        assert data["status"] == "failed"
        assert data["error_code"] == "TTS_PROVIDER_FAILED"
        assert "讯飞服务不可用" in data["error_message_safe"]
        assert data["output_object_key"] is None  # 禁止伪造产物
