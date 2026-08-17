"""Released-course player timestamps: 80% threshold completion support tests.

回归目标（2026-08-16）：
- 已发布课程（有冻结媒体数据）的节点必须携带累计 timestamp_start/end 与
  duration，使前端 media_progress 的 progress_ratio = 播放位置/节点时长，
  80% 阈值完成规则可用；
- 无任何媒体时长的节点保持 0（仅显式完成），不伪造时间轴。
"""
from __future__ import annotations

import uuid

from app.api.v1.endpoints.player import _versioned_player_data
from app.core.security import get_password_hash
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.media_release_model import (
    MediaRelease,
    MediaReleaseItem,
    MediaReleaseStatus,
)
from app.models.user_model import User, UserRole


def _released_course(session, *, with_media: bool = True, durations_ms=None):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"player-duration-{suffix}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(user)
    session.flush()
    course = Course(
        fanya_course_id=f"player-duration-{suffix}",
        fanya_course_name="播放时长回归课程",
        title="播放时长回归课程",
        teacher_id=user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()

    outline = CourseOutlineVersion(
        course_id=course.id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
    )
    session.add(outline)
    session.flush()

    outline_nodes = []
    for index, title in enumerate(["二分查找", "二叉树遍历"]):
        node = CourseOutlineNode(
            outline_version_id=outline.outline_version_id,
            course_id=course.id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=title,
            order_index=index,
            page_range="1-2",
        )
        session.add(node)
        session.flush()
        outline_nodes.append(node)

    script = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline.outline_version_id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
    )
    session.add(script)
    session.flush()

    script_nodes = []
    for node in outline_nodes:
        script_node = TeachingScriptNode(
            script_version_id=script.script_version_id,
            course_id=course.id,
            outline_node_id=node.outline_node_id,
            content=f"{node.title}的讲稿内容",
        )
        session.add(script_node)
        session.flush()
        script_nodes.append(script_node)

    release = CourseRelease(
        course_id=course.id,
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline.outline_version_id,
        script_version_id=script.script_version_id,
    )
    media_release_id = f"mrel-duration-{suffix}"
    if with_media:
        release.media_snapshot = {"media_release_id": media_release_id}
    session.add(release)
    session.flush()

    if with_media:
        session.add(MediaRelease(
            release_id=media_release_id,
            course_id=course.id,
            version_number=1,
            status=MediaReleaseStatus.ACTIVE,
            created_by=user.id,
        ))
        session.flush()
        for script_node, duration_ms in zip(
            script_nodes, durations_ms or [60_000, 90_000]
        ):
            session.add(MediaReleaseItem(
                release_id=media_release_id,
                course_id=course.id,
                node_id=script_node.id,
                outline_node_id=script_node.outline_node_id,
                order_index=0,
                status="ready",
                duration_ms=duration_ms,
            ))
    session.commit()
    return course, outline, script, release


def test_released_course_nodes_carry_cumulative_durations(session):
    course, outline, script, release = _released_course(session)
    data = _versioned_player_data(
        session,
        course=course,
        user_id=1,
        outline=outline,
        script=script,
        release_id=release.release_id,
    )
    assert len(data.nodes) == 2
    assert [node["duration"] for node in data.nodes] == [60.0, 90.0]
    assert data.nodes[0]["timestamp_start"] == 0.0
    assert data.nodes[0]["timestamp_end"] == 60.0
    assert data.nodes[1]["timestamp_start"] == 60.0
    assert data.nodes[1]["timestamp_end"] == 150.0
    assert data.total_duration == 150.0


def test_released_course_without_media_keeps_zero_timestamps(session):
    course, outline, script, release = _released_course(session, with_media=False)
    data = _versioned_player_data(
        session,
        course=course,
        user_id=1,
        outline=outline,
        script=script,
        release_id=release.release_id,
    )
    assert data.total_duration == 0.0
    for node in data.nodes:
        assert node["duration"] == 0.0
        assert node["timestamp_start"] == 0.0
        assert node["timestamp_end"] == 0.0


def test_released_course_partial_media_keeps_missing_node_at_zero(session):
    course, outline, script, release = _released_course(
        session, durations_ms=[60_000, 0]
    )
    data = _versioned_player_data(
        session,
        course=course,
        user_id=1,
        outline=outline,
        script=script,
        release_id=release.release_id,
    )
    assert data.nodes[0]["duration"] == 60.0
    assert data.nodes[0]["timestamp_end"] == 60.0
    # 无媒体时长的节点保持 0，不占用时间轴。
    assert data.nodes[1]["duration"] == 0.0
    assert data.nodes[1]["timestamp_end"] == 0.0
    assert data.total_duration == 60.0
