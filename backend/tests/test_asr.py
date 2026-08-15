"""ASR transcribe 端点必须经 Course Access v1 校验（course.question.ask）。

回归背景：ASR 入口曾不校验 course_id，已登录用户可携任意课程提交录音
（越权缺口）。本测试锁定权限层行为，不触发真实 ffmpeg / 对象存储 / 豆包。
"""
from __future__ import annotations

import io
import wave

from sqlmodel import Session

from app.api.v1.endpoints import asr as asr_module
from app.core.security import create_access_token
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    return buf.getvalue()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _make_course(session: Session, teacher: User, tag: str) -> Course:
    course = Course(
        fanya_course_id=f"asr-{tag}-{teacher.id}",
        fanya_course_name="ASR Course",
        title="ASR Course",
        teacher_id=teacher.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()
    return course


def _post(client, token: str, course_id: int):
    return client.post(
        "/api/v1/asr/transcribe",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("voice.wav", _wav(), "audio/wav")},
        data={"course_id": str(course_id)},
    )


def test_transcribe_rejects_unknown_course(client, session):
    """课程不存在 → 404，不得进入转写流程。"""
    student = User(username="asr-unk-s", hashed_password="h", role=UserRole.STUDENT, is_active=True)
    session.add(student)
    session.commit()
    session.refresh(student)

    response = _post(client, _token(student), 9_999_999)
    assert response.status_code == 404


def test_transcribe_rejects_non_member(client, session):
    """课程存在但用户不是成员 → 403。"""
    teacher = User(username="asr-nm-t", hashed_password="h", role=UserRole.TEACHER, is_active=True)
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    course = _make_course(session, teacher, "non-member")

    student = User(username="asr-nm-s", hashed_password="h", role=UserRole.STUDENT, is_active=True)
    session.add(student)
    session.commit()
    session.refresh(student)

    response = _post(client, _token(student), course.id)
    assert response.status_code == 403


def test_transcribe_allows_active_member_through_access_gate(client, session, monkeypatch):
    """ACTIVE 成员通过权限层；未配置公网 URL 时在业务层明确失败（400），不再 403/404。"""
    teacher = User(username="asr-ok-t", hashed_password="h", role=UserRole.TEACHER, is_active=True)
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    course = _make_course(session, teacher, "member")

    student = User(username="asr-ok-s", hashed_password="h", role=UserRole.STUDENT, is_active=True)
    session.add(student)
    session.commit()
    session.refresh(student)
    session.add(CourseMembership(
        user_id=student.id,
        course_id=course.id,
        role=CourseRole.STUDENT,
        status=MembershipStatus.ACTIVE,
        analytics_excluded=False,
    ))
    session.commit()

    # 隔离权限层之后的真实副作用（ffmpeg/对象存储/豆包），只验证权限放行
    class _FakeStorage:
        def put(self, *args, **kwargs):
            return "fake-hash"

        def delete(self, *args, **kwargs):
            return True

    monkeypatch.setattr(asr_module, "get_object_storage", lambda: _FakeStorage())
    monkeypatch.setattr(asr_module, "_transcode_to_wav", lambda *args, **kwargs: _wav())

    response = _post(client, _token(student), course.id)
    assert response.status_code == 400
    # global_exception_handler 把 HTTPException.detail 放入统一响应的 data
    assert response.json()["data"]["code"] == "ASR_PUBLIC_BASE_URL_NOT_CONFIGURED"
