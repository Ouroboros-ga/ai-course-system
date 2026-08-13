"""Local-only Stage 8 fixture invariants used by browser acceptance."""
from __future__ import annotations

import uuid

from sqlmodel import Session, select

from app.core.security import get_password_hash
from app.models.course_build_model import SourceMaterialVersion
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.models.user_model import User, UserRole
from scripts import prepare_stage8_media_demo as stage8_demo


def test_stage8_fixture_assigns_stable_concept_keys_to_every_knowledge_point(
    session: Session,
) -> None:
    """A local media fixture must be usable by release-pinned review lookup."""
    token = uuid.uuid4().hex[:10]
    course_id = 810_000_000 + int(token[:6], 16) % 100_000_000
    teacher = User(
        username=f"stage8-fixture-{token}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.flush()
    course = stage8_demo._ensure_course(session, course_id=course_id, teacher=teacher)
    material = SourceMaterialVersion(
        material_id=f"stage8-fixture-material-{token}",
        course_id=course.id,
        file_path="fixture/stage8.pptx",
        file_hash="fixture",
        file_size=1,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        created_by=teacher.id,
    )
    session.add(material)
    session.flush()

    outline, _ = stage8_demo._ensure_outline_and_scripts(
        session,
        course_id=course.id,
        teacher=teacher,
        material_version=material,
    )
    nodes = list(session.exec(
        select(CourseOutlineNode)
        .where(
            CourseOutlineNode.course_id == course.id,
            CourseOutlineNode.outline_version_id == outline.outline_version_id,
            CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
        )
        .order_by(CourseOutlineNode.order_index)
    ).all())

    assert [node.knowledge_graph_node_id for node in nodes] == [
        f"kg_stage8_media_demo_{course.id}_kp{index}"
        for index in range(1, len(stage8_demo.LESSON_ITEMS) + 1)
    ]
