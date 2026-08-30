"""G8 媒体时间轴与数字人测试

验证：
- 时间轴提示包含视频起止、PPT页、字幕片段、讲稿引用
- 外部完整课程视频可按时间轴驱动 PPT
- 讲稿可作为真实字幕/讲解内容展示
- 抽象存储使用 object_key
- 权限校验与跨课程隔离
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlmodel import select

from app.core.security import get_password_hash, create_access_token
from app.models.access_control_model import (
    CourseCapability, CourseMembership, CourseRole, MembershipStatus,
    PlatformPermission, PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus, ScriptNode, CourseScript, ScriptNodeType
from app.models.user_model import User, UserRole
from app.models.media_timeline_model import (
    MediaAsset, MediaTimelineCue, CueType, StorageBackend, DigitalHumanPreset,
)
from app.services.course_access_service import (
    establish_course_access_baseline, activate_student_membership,
)
from app.services.media_timeline_service import (
    create_timeline_cues_from_node, get_node_timeline, get_course_timeline,
    register_media_asset, serialize_cue,
)
from app.services.object_storage import LocalStorageProvider, reset_object_storage_for_tests


def _user(session, name, role=UserRole.TEACHER):
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user); session.commit(); session.refresh(user)
    return user

def _course(session, teacher_id):
    course = Course(
        fanya_course_id=f"mt-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="MT", title="MT", teacher_id=teacher_id, status=CourseStatus.PUBLISHED,
    )
    session.add(course); session.commit(); session.refresh(course)
    return course


@pytest.fixture
def signed_media_storage(tmp_path):
    provider = LocalStorageProvider(str(tmp_path / "media"), sign_key="media-test-sign-key")
    reset_object_storage_for_tests(provider)
    yield provider
    reset_object_storage_for_tests(None)

def _setup(session, teacher, student=None):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    if student:
        activate_student_membership(session, course.id, student.id)
    cap = session.exec(select(CourseCapability).where(CourseCapability.course_id == course.id)).first()
    if cap:
        cap.course_building = True
        session.add(cap)
    session.commit()
    return course

def _token(user):
    return create_access_token({"sub": str(user.id), "username": user.username, "role": user.role.value})


class TestMediaTimelineService:
    """时间轴服务单元测试"""

    def test_create_cues_with_script_segments(self, session):
        """从讲稿创建时间轴提示，讲稿作为字幕"""
        teacher = _user(session, "mt_create_t")
        course = _setup(session, teacher)
        script = CourseScript(course_id=course.id, version=1, is_active=True, script_content="", created_by=teacher.id)
        session.add(script); session.commit(); session.refresh(script)
        node = ScriptNode(script_id=script.id, node_index=0, node_type=ScriptNodeType.LECTURE, content="test")
        session.add(node); session.commit(); session.refresh(node)

        script_content = "第1页 欢迎来到本课程\n第2页 今天我们学习二分查找\n第3页 二分查找的时间复杂度是O(log n)"
        cues = create_timeline_cues_from_node(
            session,
            course_id=course.id, script_id=script.id, node_id=node.id,
            script_content=script_content, audio_duration=30.0,
            ppt_pages=[1, 2, 3],
        )
        assert len(cues) > 0
        # 每个提示包含字幕文本
        for cue in cues:
            assert cue.subtitle_text != ""
            assert cue.start_time < cue.end_time
            assert cue.cue_type == CueType.NARRATION

    def test_cue_contains_ppt_page_and_subtitle(self, session):
        """提示包含 PPT 页码和字幕文本"""
        teacher = _user(session, "mt_cue_t")
        course = _setup(session, teacher)
        script = CourseScript(course_id=course.id, version=1, is_active=True, created_by=teacher.id, script_content={})
        session.add(script); session.commit(); session.refresh(script)
        node = ScriptNode(script_id=script.id, node_index=0, node_type=ScriptNodeType.LECTURE, content="test")
        session.add(node); session.commit(); session.refresh(node)

        cues = create_timeline_cues_from_node(
            session,
            course_id=course.id, script_id=script.id, node_id=node.id,
            script_content="第1页 这是讲稿内容", audio_duration=10.0,
            ppt_pages=[1],
        )
        assert len(cues) > 0
        assert cues[0].ppt_page is not None
        assert "讲稿内容" in cues[0].subtitle_text

    def test_cue_contains_resource_version_and_hash(self, session):
        """提示包含资源版本和内容哈希"""
        teacher = _user(session, "mt_hash_t")
        course = _setup(session, teacher)
        script = CourseScript(course_id=course.id, version=1, is_active=True, created_by=teacher.id, script_content={})
        session.add(script); session.commit(); session.refresh(script)
        node = ScriptNode(script_id=script.id, node_index=0, node_type=ScriptNodeType.LECTURE, content="test")
        session.add(node); session.commit(); session.refresh(node)

        cues = create_timeline_cues_from_node(
            session,
            course_id=course.id, script_id=script.id, node_id=node.id,
            script_content="测试内容", audio_duration=5.0,
            ppt_pages=[1],
        )
        assert cues[0].resource_version == "v1"
        assert cues[0].content_hash != ""

    def test_get_course_timeline(self, session):
        """获取课程完整时间轴"""
        teacher = _user(session, "mt_tl_t")
        course = _setup(session, teacher)
        script = CourseScript(course_id=course.id, version=1, is_active=True, created_by=teacher.id, script_content={})
        session.add(script); session.commit(); session.refresh(script)
        node = ScriptNode(script_id=script.id, node_index=0, node_type=ScriptNodeType.LECTURE, content="test")
        session.add(node); session.commit(); session.refresh(node)

        create_timeline_cues_from_node(
            session,
            course_id=course.id, script_id=script.id, node_id=node.id,
            script_content="第1页 测试内容", audio_duration=10.0,
            ppt_pages=[1],
        )

        timeline = get_course_timeline(session, course.id)
        assert len(timeline) > 0
        assert "ppt_page" in timeline[0]
        assert "subtitle_text" in timeline[0]

    def test_abstract_storage_object_key(self, session):
        """抽象存储使用 object_key"""
        teacher = _user(session, "mt_asset_service_t")
        course = _setup(session, teacher)
        asset = register_media_asset(
            session,
            course_id=course.id,
            object_key="videos/course_1/node_5/segment_3.mp4",
            asset_type="video",
            local_path="videos/segment_3.mp4",
            mime_type="video/mp4",
            duration_seconds=10.5,
        )
        assert asset.object_key == "videos/course_1/node_5/segment_3.mp4"
        assert asset.backend == StorageBackend.LOCAL
        resolved = asset.resolve_url()
        assert "/assets/videos/course_1/node_5/segment_3.mp4/content?" in resolved
        assert "exp=" in resolved and "sig=" in resolved and "scope=" in resolved

    def test_cue_with_video_object_key(self, session):
        """提示关联视频资产的 object_key"""
        teacher = _user(session, "mt_vok_t")
        course = _setup(session, teacher)
        script = CourseScript(course_id=course.id, version=1, is_active=True, created_by=teacher.id, script_content={})
        session.add(script); session.commit(); session.refresh(script)
        node = ScriptNode(script_id=script.id, node_index=0, node_type=ScriptNodeType.LECTURE, content="test")
        session.add(node); session.commit(); session.refresh(node)

        # 注册视频资产
        register_media_asset(
            session,
            course_id=course.id,
            object_key="videos/course_1/node_1/full.mp4",
            asset_type="video",
            local_path="videos/full.mp4",
        )

        cues = create_timeline_cues_from_node(
            session,
            course_id=course.id, script_id=script.id, node_id=node.id,
            script_content="测试", audio_duration=10.0,
            ppt_pages=[1],
            video_object_key="videos/course_1/node_1/full.mp4",
        )
        assert cues[0].video_object_key == "videos/course_1/node_1/full.mp4"


class TestMediaTimelineAPI:
    """媒体时间轴 API 集成测试"""

    def test_get_timeline_requires_membership(self, client, session):
        """获取时间轴需要权限"""
        teacher = _user(session, "mt_api_nm")
        course = _course(session, teacher.id)
        token = _token(teacher)
        response = client.get(
            f"/api/v1/media/course/{course.id}/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_get_timeline_success(self, client, session):
        """成功获取时间轴"""
        teacher = _user(session, "mt_api_get")
        course = _setup(session, teacher)
        token = _token(teacher)
        response = client.get(
            f"/api/v1/media/course/{course.id}/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_register_asset(self, client, session):
        """注册媒体资产"""
        teacher = _user(session, "mt_api_asset")
        course = _setup(session, teacher)
        token = _token(teacher)
        response = client.post(
            "/api/v1/media/assets",
            json={
                "course_id": course.id,
                "object_key": "videos/test/segment_1.mp4",
                "asset_type": "video",
                "local_path": "videos/test.mp4",
                "mime_type": "video/mp4",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["object_key"] == "videos/test/segment_1.mp4"

    def test_cross_course_isolation(self, client, session):
        """跨课程隔离"""
        t1 = _user(session, "mt_iso_t1")
        t2 = _user(session, "mt_iso_t2")
        s1 = _user(session, "mt_iso_s1", UserRole.STUDENT)
        c1 = _setup(session, t1, s1)
        c2 = _setup(session, t2)
        token = _token(s1)
        response = client.get(
            f"/api/v1/media/course/{c2.id}/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_media_asset_metadata_is_course_scoped(self, client, session):
        teacher_a = _user(session, "mt_asset_scope_a")
        teacher_b = _user(session, "mt_asset_scope_b")
        course_a = _setup(session, teacher_a)
        _setup(session, teacher_b)
        object_key = "videos/scoped/asset.mp4"
        register_media_asset(
            session,
            course_id=course_a.id,
            object_key=object_key,
            asset_type="video",
            local_path="videos/scoped/asset.mp4",
        )

        response = client.get(
            f"/api/v1/media/assets/{object_key}",
            headers={"Authorization": f"Bearer {_token(teacher_b)}"},
        )
        assert response.status_code == 403

    def test_local_content_requires_signed_scope_and_rejects_tampering(
        self, client, session, signed_media_storage,
    ):
        teacher = _user(session, "mt_signed_content")
        course = _setup(session, teacher)
        object_key = "audio/signed/course-1.mp3"
        payload = b"signed media bytes"
        signed_media_storage.put(object_key, payload, mime_type="audio/mpeg")
        register_media_asset(
            session, course_id=course.id, object_key=object_key,
            asset_type="audio", mime_type="audio/mpeg", size_bytes=len(payload),
        )
        session.commit()
        url = signed_media_storage.sign_read_url(
            object_key, scope={"course_id": course.id, "purpose": "media_asset"},
        )
        parsed = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        headers = {"Authorization": f"Bearer {_token(teacher)}"}

        ok = client.get(parsed.path, params=query, headers=headers)
        assert ok.status_code == 200
        assert ok.content == payload

        missing = client.get(parsed.path, params={"exp": query["exp"], "sig": query["sig"]}, headers=headers)
        assert missing.status_code in (403, 422)

        tampered = {**query, "scope": "course_id=999;purpose=media_asset"}
        rejected = client.get(parsed.path, params=tampered, headers=headers)
        assert rejected.status_code == 403

        expired_exp = str(int((datetime.now(timezone.utc) - timedelta(seconds=5)).timestamp()))
        expired_sig = signed_media_storage._sign(
            object_key, int(expired_exp), {"course_id": course.id, "purpose": "media_asset"},
        )
        expired = client.get(
            parsed.path,
            params={"exp": expired_exp, "sig": expired_sig, "scope": query["scope"]},
            headers=headers,
        )
        assert expired.status_code == 403

