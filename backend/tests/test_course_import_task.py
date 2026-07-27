"""Contract tests for the navigation-safe course creation path."""
from __future__ import annotations

from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.course_build_model import SourceMaterial, SourceMaterialVersion
from app.models.course_model import Course, CourseStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole


class _MemoryObjectStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put(self, object_key, content, *, mime_type=""):
        self.objects[object_key] = content if isinstance(content, bytes) else content.read()
        return "test-sha"

    def delete(self, object_key):
        self.objects.pop(object_key, None)
        return True


def test_course_import_persists_draft_material_and_parse_task(client, session, monkeypatch):
    """The request may finish, but parsing is represented by durable DB state."""
    teacher = User(
        username="course_import_teacher",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    token = create_access_token({"sub": str(teacher.id), "username": teacher.username, "role": "teacher"})

    storage = _MemoryObjectStorage()
    import app.api.v1.endpoints.document as document_endpoint
    monkeypatch.setattr(document_endpoint, "get_object_storage", lambda: storage)

    response = client.post(
        "/api/v1/document/course-imports",
        files={"file": ("intro.pptx", b"demo-pptx-bytes", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 202
    data = body["data"]
    course = session.get(Course, data["course_id"])
    assert course is not None
    assert course.status == CourseStatus.DRAFT
    assert course.invite_code is None
    assert course.source_file_path in storage.objects

    material = session.exec(select(SourceMaterial).where(SourceMaterial.material_id == data["material_id"])).first()
    version = session.exec(select(SourceMaterialVersion).where(SourceMaterialVersion.version_id == data["material_version_id"])).first()
    task = session.exec(select(TaskRecord).where(TaskRecord.task_id == data["task_id"])).first()
    assert material is not None and material.course_id == course.id
    assert version is not None and version.parse_task_id == data["task_id"]
    assert task is not None and task.course_id == course.id and task.status == "pending"
