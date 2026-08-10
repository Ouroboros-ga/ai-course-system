from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, OutlineNodeType
from app.models.unified_learning_model import LearningEventType
from datetime import datetime, timedelta, timezone

from app.services.unified_learning_service import ordered_outline_nodes, record_event, student_context
from app.api.v1.endpoints.player import _learner_outline_nodes


def _release_with_knowledge_points(session, teacher_id, count=14):
    course = Course(
        fanya_course_id=f"fanya-{teacher_id}-{count}",
        fanya_course_name="统一学习投影测试课程",
        title="统一学习投影测试课程",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()
    outline = CourseOutlineVersion(
        course_id=course.id,
        version=1,
        lifecycle_status="published",
        created_by=teacher_id,
    )
    session.add(outline)
    session.flush()
    nodes = []
    for index in range(count):
        node = CourseOutlineNode(
            course_id=course.id,
            outline_version_id=outline.outline_version_id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=f"知识点 {index + 1}",
            order_index=index,
        )
        nodes.append(node)
        session.add(node)
    release = CourseRelease(
        course_id=course.id,
        release_id=f"release-{teacher_id}-{count}",
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline.outline_version_id,
    )
    session.add(release)
    session.flush()
    return course, release, nodes


def test_student_context_uses_knowledge_point_denominator_and_event_idempotency(session, teacher_user, student_user):
    course, release, nodes = _release_with_knowledge_points(session, teacher_user.id)

    initial = student_context(session, student_id=student_user.id, course_id=course.id)
    assert initial["total"] == 14
    assert initial["completed"] == 0

    first_event, first_projection = record_event(
        session,
        student_id=student_user.id,
        course_id=course.id,
        release_id=release.release_id,
        outline_node_id=nodes[0].outline_node_id,
        event_type=LearningEventType.EXPLICIT_COMPLETE,
        idempotency_key="complete-kp-1",
    )
    duplicate_event, duplicate_projection = record_event(
        session,
        student_id=student_user.id,
        course_id=course.id,
        release_id=release.release_id,
        outline_node_id=nodes[0].outline_node_id,
        event_type=LearningEventType.EXPLICIT_COMPLETE,
        idempotency_key="complete-kp-1",
    )
    assert duplicate_event.event_id == first_event.event_id
    assert duplicate_projection.id == first_projection.id

    try:
        record_event(
            session,
            student_id=student_user.id,
            course_id=course.id,
            release_id=release.release_id,
            outline_node_id=nodes[1].outline_node_id,
            event_type=LearningEventType.EXPLICIT_COMPLETE,
            idempotency_key="complete-kp-1",
        )
    except ValueError as exc:
        assert str(exc) == "IDEMPOTENCY_KEY_CONFLICT"
    else:
        raise AssertionError("idempotency key reuse across nodes must fail closed")

    for index in range(1, 5):
        record_event(
            session,
            student_id=student_user.id,
            course_id=course.id,
            release_id=release.release_id,
            outline_node_id=nodes[index].outline_node_id,
            event_type=LearningEventType.MEDIA_PROGRESS,
            idempotency_key=f"media-kp-{index + 1}",
            payload={"progress_ratio": 0.8},
        )

    context = student_context(session, student_id=student_user.id, course_id=course.id)
    assert context["total"] == 14
    assert context["completed"] == 5
    assert context["completion_rate"] == 5 / 14
    assert sum(item["learning"]["status"] == "completed" for item in context["items"]) == 5


def test_player_release_filter_excludes_non_learning_outline_nodes():
    nodes = [
        CourseOutlineNode(node_type=OutlineNodeType.CHAPTER),
        CourseOutlineNode(node_type=OutlineNodeType.SECTION),
        CourseOutlineNode(node_type=OutlineNodeType.KNOWLEDGE_POINT),
        CourseOutlineNode(node_type=OutlineNodeType.EXAMPLE),
        CourseOutlineNode(node_type=OutlineNodeType.PRACTICE_SUGGESTION),
    ]
    learner_nodes = _learner_outline_nodes(nodes, release_id="release-1")
    assert [node.node_type for node in learner_nodes] == [OutlineNodeType.KNOWLEDGE_POINT]
    assert len(_learner_outline_nodes(nodes, release_id=None, content_status="preview")) == 5


def test_outline_order_is_tree_preorder_not_flat_sibling_order(session, teacher_user):
    course, release, nodes = _release_with_knowledge_points(session, teacher_user.id, count=2)
    chapter_a = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=release.outline_version_id,
        node_type=OutlineNodeType.CHAPTER,
        title="章节 A",
        order_index=0,
    )
    chapter_b = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=release.outline_version_id,
        node_type=OutlineNodeType.CHAPTER,
        title="章节 B",
        order_index=1,
    )
    nodes[0].parent_node_id = chapter_a.outline_node_id
    nodes[1].parent_node_id = chapter_b.outline_node_id
    session.add(chapter_a)
    session.add(chapter_b)
    session.add(nodes[0])
    session.add(nodes[1])
    session.commit()

    ordered = ordered_outline_nodes(session, outline_version_id=release.outline_version_id)
    assert [node.title for node in ordered] == ["章节 A", "知识点 1", "章节 B", "知识点 2"]
    assert [node.title for node in ordered if node.node_type == OutlineNodeType.KNOWLEDGE_POINT] == ["知识点 1", "知识点 2"]


def test_record_event_accepts_naive_utc_and_clamps_malformed_progress(session, teacher_user, student_user):
    course, release, nodes = _release_with_knowledge_points(session, teacher_user.id, count=1)
    _, projection = record_event(
        session,
        student_id=student_user.id,
        course_id=course.id,
        release_id=release.release_id,
        outline_node_id=nodes[0].outline_node_id,
        event_type=LearningEventType.MEDIA_PROGRESS,
        idempotency_key="malformed-progress",
        occurred_at=datetime(2026, 8, 8, 10, 0, 0),
        payload={"progress_ratio": "not-a-number", "current_timestamp": "bad", "current_page": "bad", "time_spent_delta": "bad"},
    )
    assert projection.exposure_status.value == "in_progress"
    assert projection.current_timestamp == 0
    assert projection.current_page == 1
    assert projection.exposure_seconds == 0


def test_record_event_normalizes_persisted_sqlite_timestamp(session, teacher_user, student_user):
    """A second browser event must not compare SQLite-naive and aware times."""
    course, release, nodes = _release_with_knowledge_points(session, teacher_user.id, count=1)
    first_time = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    record_event(
        session,
        student_id=student_user.id,
        course_id=course.id,
        release_id=release.release_id,
        outline_node_id=nodes[0].outline_node_id,
        event_type=LearningEventType.NODE_OPENED,
        idempotency_key="sqlite-aware-first",
        occurred_at=first_time,
    )
    session.commit()
    session.expire_all()

    _, projection = record_event(
        session,
        student_id=student_user.id,
        course_id=course.id,
        release_id=release.release_id,
        outline_node_id=nodes[0].outline_node_id,
        event_type=LearningEventType.MEDIA_PROGRESS,
        idempotency_key="sqlite-aware-second",
        occurred_at=first_time + timedelta(seconds=5),
        payload={"current_timestamp": 5},
    )

    assert projection.last_accessed_at.tzinfo is not None
    assert projection.last_accessed_at == first_time + timedelta(seconds=5)
