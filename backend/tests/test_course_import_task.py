"""Contract tests for the navigation-safe course creation path."""
from __future__ import annotations

import json

from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.course_build_model import CourseBuildDraft, CourseBuildStep, SourceMaterial, SourceMaterialVersion
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
    import app.services.course_material_upload_service as upload_service
    monkeypatch.setattr(upload_service, "get_object_storage", lambda: storage)

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
    assert json.loads(task.input_payload)["run_id"] == data["run_id"]


def test_empty_course_then_multiple_material_uploads_share_one_workspace(client, session, monkeypatch):
    teacher = User(
        username="p0_multi_material_teacher",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    token = create_access_token({"sub": str(teacher.id), "username": teacher.username, "role": "teacher"})

    storage = _MemoryObjectStorage()
    import app.services.course_material_upload_service as upload_service
    monkeypatch.setattr(upload_service, "get_object_storage", lambda: storage)

    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/api/v1/courses", json={
        "title": "数据结构",
        "description": "面向大一学生",
        "subject": "计算机科学",
        "course_type": "专业基础课",
        "teaching_audience": "本科一年级",
    }, headers=headers)
    assert created.status_code == 200
    assert created.json()["code"] == 201
    course_id = created.json()["data"]["course_id"]

    assert session.get(Course, course_id).status == CourseStatus.DRAFT
    assert session.exec(select(CourseBuildDraft).where(CourseBuildDraft.course_id == course_id)).one()
    assert len(session.exec(select(CourseBuildStep).where(CourseBuildStep.course_id == course_id)).all()) == 7

    response = client.post(
        f"/api/v1/courses/{course_id}/materials",
        files=[
            ("files", ("slides.pptx", b"slide", "application/vnd.openxmlformats-officedocument.presentationml.presentation")),
            ("files", ("book.pdf", b"pdf", "application/pdf")),
            ("files", ("guide.docx", b"docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ("material_roles", (None, "primary_courseware")),
            ("material_roles", (None, "textbook")),
            ("material_roles", (None, "experiment_guide")),
        ],
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 202
    assert len(body["data"]["items"]) == 3
    assert {item["parse_status"] for item in body["data"]["items"]} == {"uploaded"}

    materials = session.exec(select(SourceMaterial).where(SourceMaterial.course_id == course_id)).all()
    assert {material.material_role for material in materials} == {
        "primary_courseware", "textbook", "experiment_guide",
    }
    assert len(session.exec(select(TaskRecord).where(TaskRecord.course_id == course_id)).all()) == 3
