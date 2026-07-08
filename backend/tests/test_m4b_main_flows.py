import json
import uuid

import pytest
from sqlmodel import Session, select

from app.common.llm_client import LLMResponse
from app.core.security import create_access_token, get_password_hash
from app.models.course_model import (
    Course,
    CourseScript,
    CourseStatus,
    DoclingDocument,
    DoclingText,
    ParseStatus,
    ScriptNode,
    ScriptNodeType,
    StudentEnrollment,
)
from app.models.mapping_model import KnowledgePageMap
from app.models.progress_model import LearningJumpHistory, LearningProgress, NodeProgress
from app.models.user_model import ChatHistory, ChatMessage, User, UserRole
from app.models.video_generation_model import GenerationStatus, VideoGenerationTask
from app.services.document_service import (
    DocumentProcessResult,
    ParseResult,
    RAGProcessResult,
    ScriptNode as ServiceScriptNode,
    ScriptResult,
    StructureResult,
)
from fakes import BUSINESS_FAILURE_MESSAGE, FakeDigitalHumanClient, FakePPTClient


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _create_user(session: Session, role: UserRole, prefix: str) -> User:
    user = User(
        username=_unique(prefix),
        real_name=prefix.replace("_", " ").title(),
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
        school_id="m4b-school",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _headers(user: User) -> dict:
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "m4b-school",
    })
    return {"Authorization": f"Bearer {token}"}


def _create_course_graph(session: Session, teacher: User, status: CourseStatus = CourseStatus.PUBLISHED):
    suffix = uuid.uuid4().hex[:8]
    course = Course(
        fanya_course_id=f"m4b_{suffix}",
        fanya_course_name=f"M4B Course {suffix}",
        title=f"M4B Regression Course {suffix}",
        description="M4B offline regression fixture",
        teacher_id=teacher.id,
        status=status,
        is_ai_generated=True,
        total_duration=120,
        total_nodes=2,
        source_file_name="m4b_fixture.md",
        source_file_path=f"/tmp/m4b_fixture_{suffix}.md",
        source_mimetype="text/markdown",
        total_pages=4,
    )
    session.add(course)
    session.commit()
    session.refresh(course)

    doc = DoclingDocument(
        course_id=course.id,
        doc_name="m4b_fixture.md",
        origin_filename="m4b_fixture.md",
        origin_mimetype="text/markdown",
        source_file_path=course.source_file_path,
        status=ParseStatus.COMPLETED,
        total_texts=2,
        raw_json={"raw_content": "binary search and recursion lecture notes"},
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    for index, text in enumerate(["Binary search splits sorted data.", "Recursion calls itself with a smaller case."]):
        session.add(DoclingText(
            doc_id=doc.id,
            self_ref=f"#/texts/{index}",
            label="text",
            text=text,
            page_no=index + 1,
            sort_order=index,
        ))
    session.commit()

    script = CourseScript(
        course_id=course.id,
        version=1,
        version_name="v1.0",
        script_content={"title": course.title, "nodes": []},
        summary_text="Offline regression script",
        keywords=json.dumps(["binary search", "recursion"]),
        is_active=True,
        created_by=teacher.id,
    )
    session.add(script)
    session.commit()
    session.refresh(script)

    nodes = []
    for index, title in enumerate(["Binary Search", "Recursion"]):
        node = ScriptNode(
            script_id=script.id,
            chapter_id=f"kp_{index + 1}",
            node_index=index,
            node_type=ScriptNodeType.LECTURE,
            title=title,
            content=f"{title} content for regression testing with enough text for TTS synthesis.",
            page_start=index + 1,
            page_end=index + 1,
            duration=60,
            is_key_point=True,
            timestamp_start=index * 60.0,
            timestamp_end=(index + 1) * 60.0,
        )
        session.add(node)
        nodes.append(node)
    session.commit()
    for node in nodes:
        session.refresh(node)

    return course, script, nodes, doc


def _fake_document_result(filename: str) -> DocumentProcessResult:
    return DocumentProcessResult(
        parse_result=ParseResult(
            markdown_content="# Fake Lesson\n\nBinary search lesson.",
            filename=filename,
            file_path="fake-path",
            file_size=128,
            parse_method="m4b_fake",
            doc_title="Fake Lesson",
        ),
        structure_result=StructureResult(
            groups=[],
            texts=[{"self_ref": "#/texts/0", "label": "text", "text": "Binary search lesson.", "page_no": 1}],
            tables=[],
            pictures=[],
            raw_content="Binary search lesson.",
        ),
        script_result=ScriptResult(
            title="Fake Lesson",
            summary="Fake summary",
            keywords=["binary search"],
            total_duration=60,
            nodes=[
                ServiceScriptNode(
                    chapter_id="kp_upload_1",
                    node_type="lecture",
                    title="Uploaded Node",
                    content="Uploaded lesson content with enough text for follow-up tests.",
                    page_start=1,
                    page_end=1,
                    duration=60,
                    is_key_point=True,
                    timestamp_start=0.0,
                    timestamp_end=60.0,
                )
            ],
            script_content={"title": "Fake Lesson", "nodes": [{"title": "Uploaded Node"}]},
            beautiful_markdown="# Fake Lesson\n\nUploaded Node",
        ),
        rag_result=RAGProcessResult(
            processed_text="Binary search lesson.",
            knowledge_points=[{"id": "kp_upload_1", "title": "Binary search"}],
        ),
        mind_map={"root": "Fake Lesson"},
    )


def test_m4b_user_register_login_and_role_identification(client):
    username = _unique("m4b_register")

    register_response = client.post("/api/v1/user/register", json={"username": username, "password": "test-password"})
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["code"] == 200
    assert register_payload["data"]["token"]
    assert register_payload["data"]["userInfo"]["username"] == username

    login_response = client.post("/api/v1/user/login", json={"username": username, "password": "test-password"})
    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["code"] == 200
    assert login_payload["data"]["token"]

    me_response = client.get("/api/v1/user/me", headers={"Authorization": f"Bearer {login_payload['data']['token']}"})
    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload["code"] == 200
    assert me_payload["data"]["username"] == username
    assert me_payload["data"]["role"] == UserRole.STUDENT.value


def test_m4b_teacher_upload_document_fake_success_and_failure(client, session, monkeypatch, test_artifact_dir):
    teacher = _create_user(session, UserRole.TEACHER, "m4b_upload_teacher")

    import app.api.v1.endpoints.document as document_endpoint

    upload_dir = test_artifact_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(document_endpoint, "UPLOAD_DIR", upload_dir)

    async def no_background_audio(course_id: int, script_id: int):
        return None

    monkeypatch.setattr(document_endpoint, "_background_synthesize_audio", no_background_audio)

    async def fake_process_document(file_path, filename, enable_rag=True, enable_script=True):
        return _fake_document_result(filename)

    monkeypatch.setattr(document_endpoint.document_service, "process_document", fake_process_document)

    success_response = client.post(
        "/api/v1/document/upload",
        headers=_headers(teacher),
        files={"file": ("fake_lesson.md", b"# fake lesson", "text/markdown")},
    )
    assert success_response.status_code == 200
    success_payload = success_response.json()
    assert success_payload["code"] == 200
    course_id = success_payload["data"]["courseId"]
    chat_id = success_payload["data"]["chatId"]

    session.expire_all()
    course = session.get(Course, course_id)
    assert course.status == CourseStatus.PUBLISHED
    assert course.is_ai_generated is True
    assert course.total_nodes == 1
    assert session.get(ChatHistory, chat_id) is not None

    doc = session.exec(select(DoclingDocument).where(DoclingDocument.course_id == course_id)).first()
    assert doc.status == ParseStatus.COMPLETED
    assert doc.total_texts == 1

    async def failing_process_document(file_path, filename, enable_rag=True, enable_script=True):
        raise RuntimeError("fake document parse business failure")

    monkeypatch.setattr(document_endpoint.document_service, "process_document", failing_process_document)
    failure_response = client.post(
        "/api/v1/document/upload",
        headers=_headers(teacher),
        files={"file": ("bad_lesson.md", b"# bad lesson", "text/markdown")},
    )
    assert failure_response.status_code == 200
    failure_payload = failure_response.json()
    assert failure_payload["code"] == 500
    assert "fake document parse business failure" in failure_payload["data"]["error"]


def test_m4b_teacher_script_mapping_publish_enrollment_and_course_lifecycle(client, session):
    teacher = _create_user(session, UserRole.TEACHER, "m4b_flow_teacher")
    student = _create_user(session, UserRole.STUDENT, "m4b_flow_student")
    course, script, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.DRAFT)
    course_id = course.id

    save_response = client.post(
        f"/api/v1/document/course/{course.id}/save",
        headers=_headers(teacher),
        json={"nodes": [{"id": nodes[0].id, "title": "Updated Binary Search", "content": "Updated content."}]},
    )
    assert save_response.status_code == 200
    assert save_response.json()["code"] == 200
    session.expire_all()
    assert session.get(ScriptNode, nodes[0].id).title == "Updated Binary Search"

    detail_response = client.get(f"/api/v1/document/course/{course.id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["code"] == 200

    snapshot_response = client.post(
        f"/api/v1/document/course/{course.id}/script/snapshot",
        headers=_headers(teacher),
        json={"version_name": "m4b snapshot"},
    )
    assert snapshot_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    assert snapshot_payload["code"] == 200
    new_script_id = snapshot_payload["data"]["script_id"]

    versions_response = client.get(f"/api/v1/document/course/{course.id}/script/versions", headers=_headers(teacher))
    assert versions_response.status_code == 200
    assert versions_response.json()["code"] == 200
    assert len(versions_response.json()["data"]) >= 2

    rollback_response = client.post(
        f"/api/v1/document/course/{course.id}/script/rollback/{script.id}",
        headers=_headers(teacher),
    )
    assert rollback_response.status_code == 200
    assert rollback_response.json()["code"] == 200
    session.expire_all()
    assert session.get(CourseScript, script.id).is_active is True
    assert session.get(CourseScript, new_script_id).is_active is False

    auto_mapping_response = client.post(f"/api/v1/mapping/{course.id}/auto", headers=_headers(teacher))
    assert auto_mapping_response.status_code == 200
    assert auto_mapping_response.json()["code"] == 200

    mapping_response = client.get(f"/api/v1/mapping/{course.id}", headers=_headers(teacher))
    assert mapping_response.status_code == 200
    assert mapping_response.json()["code"] == 200

    update_mapping_response = client.put(
        f"/api/v1/mapping/{course.id}/nodes/{nodes[0].id}",
        headers=_headers(teacher),
        json={"node_id": nodes[0].id, "page_start": 2, "page_end": 3},
    )
    assert update_mapping_response.status_code == 200
    assert update_mapping_response.json()["code"] == 200

    apply_mapping_response = client.post(f"/api/v1/mapping/{course.id}/apply", headers=_headers(teacher))
    assert apply_mapping_response.status_code == 200
    assert apply_mapping_response.json()["code"] == 200
    session.expire_all()
    assert session.get(ScriptNode, nodes[0].id).page_start == 2
    assert session.exec(select(KnowledgePageMap).where(KnowledgePageMap.course_id == course.id)).all()

    publish_response = client.post(f"/api/v1/document/course/{course.id}/publish", headers=_headers(teacher))
    assert publish_response.status_code == 200
    assert publish_response.json()["code"] == 200

    enroll_response = client.post(f"/api/v1/document/course/{course.id}/enroll", headers=_headers(student))
    assert enroll_response.status_code == 200
    enroll_payload = enroll_response.json()
    assert enroll_payload["code"] == 200
    assert enroll_payload["data"]["enrollment_id"]
    assert enroll_payload["data"]["enrolled_at"]
    assert enroll_payload["data"]["total_nodes"] == course.total_nodes
    session.expire_all()
    enrollment = session.exec(
        select(StudentEnrollment).where(StudentEnrollment.student_id == student.id, StudentEnrollment.course_id == course.id)
    ).first()
    progress = session.exec(
        select(LearningProgress).where(LearningProgress.user_id == student.id, LearningProgress.course_id == course.id)
    ).first()
    assert enrollment is not None and enrollment.is_active is True
    assert progress is not None

    duplicate_response = client.post(f"/api/v1/document/course/{course.id}/enroll", headers=_headers(student))
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["code"] == 200
    assert duplicate_response.json()["data"]["already_enrolled"] is True

    my_courses_response = client.get("/api/v1/document/my-courses", headers=_headers(student))
    assert my_courses_response.status_code == 200
    my_courses_payload = my_courses_response.json()
    assert my_courses_payload["code"] == 200
    assert my_courses_payload["data"]["total"] >= 1
    assert any(item["course_id"] == course.id for item in my_courses_payload["data"]["courses"])
    assert enrollment.is_active is True

    unenroll_response = client.post(f"/api/v1/document/course/{course.id}/unenroll", headers=_headers(student))
    assert unenroll_response.status_code == 200
    assert unenroll_response.json()["code"] == 200

    unpublish_response = client.post(f"/api/v1/document/course/{course.id}/unpublish", headers=_headers(teacher))
    assert unpublish_response.status_code == 200
    assert unpublish_response.json()["code"] == 200
    session.expire_all()
    assert session.get(Course, course.id).status == CourseStatus.DRAFT

    delete_response = client.delete(f"/api/v1/document/course/{course.id}", headers=_headers(teacher))
    assert delete_response.status_code == 200
    assert delete_response.json()["code"] == 200
    session.expire_all()
    assert session.get(Course, course_id) is None


def test_m4b_student_player_progress_chat_quiz_and_prerequisite_flows(client, session, monkeypatch):
    teacher = _create_user(session, UserRole.TEACHER, "m4b_student_teacher")
    student = _create_user(session, UserRole.STUDENT, "m4b_student_user")
    course, _, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.PUBLISHED)

    student_headers = _headers(student)

    player_init_response = client.get(f"/api/v1/player/init/{course.id}", headers=student_headers)
    assert player_init_response.status_code == 200
    player_payload = player_init_response.json()
    assert player_payload["course_id"] == course.id
    assert len(player_payload["nodes"]) == 2

    player_save_response = client.post(
        "/api/v1/player/progress/save",
        headers=student_headers,
        json={
            "course_id": course.id,
            "current_node_id": nodes[0].id,
            "current_timestamp": 12.5,
            "current_page": 2,
            "completed_nodes": [nodes[0].id],
        },
    )
    assert player_save_response.status_code == 200
    assert player_save_response.json()["code"] == 200

    progress_sync_response = client.post(
        "/api/v1/progress/sync",
        headers=student_headers,
        json={
            "courseId": course.id,
            "nodeId": nodes[0].id,
            "timestamp": 20.0,
            "isCompleted": True,
            "timeSpent": 90,
            "nodeIndex": 0,
            "understandingLevel": "medium",
            "understandingScore": 0.7,
            "totalNodes": 2,
        },
    )
    assert progress_sync_response.status_code == 200
    assert progress_sync_response.json()["code"] == 200

    detail_response = client.get(f"/api/v1/progress/detail/{course.id}", headers=student_headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["code"] == 200

    resume_response = client.get(f"/api/v1/progress/resume/{course.id}", headers=student_headers)
    assert resume_response.status_code == 200
    assert resume_response.json()["code"] == 200
    assert resume_response.json()["data"]["hasProgress"] is True

    chat_response = client.post(
        "/api/v1/chat/ask",
        headers=student_headers,
        json={"courseId": course.id, "question": "What is binary search?"},
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["code"] == 200
    assert chat_payload["data"]["answer"] == "fake llm response"
    session.expire_all()
    assert session.exec(select(ChatMessage).where(ChatMessage.chat_id == chat_payload["data"]["chatId"])).all()

    class QuizLLMClient:
        async def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
            return LLMResponse(
                content=json.dumps({
                    "question": "Which property is required for binary search?",
                    "options": {"A": "Sorted data", "B": "Random data"},
                    "correct_answer": "A",
                    "explanation": "Binary search repeatedly halves a sorted search range.",
                }),
                usage={},
                model="fake-quiz-llm",
                finish_reason="stop",
                latency_ms=1.0,
            )

    import importlib
    qa_service_module = importlib.import_module("app.services.qa_service")
    monkeypatch.setattr(qa_service_module, "llm_client", QuizLLMClient())

    quiz_response = client.post(
        "/api/v1/chat/quiz",
        headers=student_headers,
        json={"courseId": course.id, "nodeId": nodes[0].id},
    )
    assert quiz_response.status_code == 200
    assert quiz_response.json()["code"] == 200
    assert quiz_response.json()["data"]["quiz"]["correct_answer"] == "A"

    class FakePrerequisiteAnalyzer:
        async def analyze_prerequisite_gaps(self, **kwargs):
            return {
                "has_gaps": True,
                "overall_confidence": 0.88,
                "weak_prerequisites": [{"prerequisiteId": nodes[0].id, "title": nodes[0].title}],
                "suggested_action": "jump_to_review",
                "analysis_summary": "Needs prerequisite review.",
            }

    import app.api.v1.endpoints.prerequisite as prerequisite_endpoint
    monkeypatch.setattr(prerequisite_endpoint, "prerequisite_analyzer", FakePrerequisiteAnalyzer())

    analyze_response = client.post(
        "/api/v1/prerequisite/analyze-gap",
        headers=student_headers,
        json={
            "courseId": course.id,
            "currentNodeId": nodes[1].id,
            "question": "Why does recursion need a base case?",
            "conversationHistory": [],
        },
    )
    assert analyze_response.status_code == 200
    assert analyze_response.json()["code"] == 200
    assert analyze_response.json()["data"]["hasGaps"] is True

    jump_response = client.post(
        "/api/v1/prerequisite/jump",
        headers=student_headers,
        json={
            "courseId": course.id,
            "fromNodeId": nodes[1].id,
            "fromNodeTitle": nodes[1].title,
            "fromNodeIndex": nodes[1].node_index,
            "toPrerequisiteId": nodes[0].id,
            "toNodeTitle": nodes[0].title,
            "toNodeIndex": nodes[0].node_index,
            "triggerQuestion": "Need review",
            "gapDescription": "Missing binary search prerequisite",
            "confidenceScore": 0.9,
            "urgencyLevel": "high",
        },
    )
    assert jump_response.status_code == 200
    assert jump_response.json()["code"] == 200
    jump_id = jump_response.json()["data"]["jumpId"]

    return_response = client.post(
        "/api/v1/prerequisite/return",
        headers=student_headers,
        json={"jumpId": jump_id, "reviewDurationSeconds": 65},
    )
    assert return_response.status_code == 200
    assert return_response.json()["code"] == 200
    session.expire_all()
    assert session.get(LearningJumpHistory, jump_id) is not None


def test_m4b_tts_video_and_ppt_fake_external_paths(client, session, monkeypatch, test_artifact_dir):
    teacher = _create_user(session, UserRole.TEACHER, "m4b_media_teacher")
    course, _, nodes, _ = _create_course_graph(session, teacher, status=CourseStatus.PUBLISHED)
    teacher_headers = _headers(teacher)

    import app.api.v1.endpoints.document as document_endpoint
    audio_root = test_artifact_dir / "document_audio"
    audio_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(document_endpoint, "AUDIO_STORAGE_DIR", audio_root)

    tts_response = client.post(
        f"/api/v1/document/course/{course.id}/node/{nodes[0].id}/synthesize-audio",
        headers=teacher_headers,
    )
    assert tts_response.status_code == 200
    assert tts_response.json()["code"] == 200
    session.expire_all()
    assert session.get(ScriptNode, nodes[0].id).audio_url

    import app.services.video_generation_service as video_service_module
    import app.api.v1.endpoints.video_generation as video_endpoint
    monkeypatch.setattr(video_service_module, "AUDIO_ROOT", test_artifact_dir / "video_audio")
    monkeypatch.setattr(video_service_module, "GENERATED_ROOT", test_artifact_dir / "video_generated")

    async def fake_resolve_face_video(face_video_asset_id, node, session):
        face_path = test_artifact_dir / "face.mp4"
        face_path.write_bytes(b"FAKE_FACE_VIDEO")
        return str(face_path)

    monkeypatch.setattr(video_service_module.video_generation_service, "_resolve_face_video", fake_resolve_face_video)

    video_response = client.post(f"/api/v1/video-gen/node/{nodes[0].id}/generate?force=true", headers=teacher_headers)
    assert video_response.status_code == 200
    assert video_response.json()["code"] == 200
    assert video_response.json()["data"]["status"] == GenerationStatus.COMPLETED.value
    task_id = video_response.json()["data"]["id"]

    task_response = client.get(f"/api/v1/video-gen/task/{task_id}", headers=teacher_headers)
    assert task_response.status_code == 200
    assert task_response.json()["code"] == 200

    class UnavailableDigitalHuman:
        api_url = "http://fake-digital-human.local"

        async def check_health(self):
            return False

    monkeypatch.setattr(video_endpoint, "digital_human_client", UnavailableDigitalHuman())
    unavailable_response = client.post(f"/api/v1/video-gen/node/{nodes[1].id}/generate?force=true", headers=teacher_headers)
    assert unavailable_response.status_code == 503

    class TimeoutAfterHealth:
        api_url = "http://fake-digital-human.local"

        async def check_health(self):
            return True

        async def generate_video(self, audio_path, video_path):
            raise TimeoutError("fake service timeout")

    timeout_client = TimeoutAfterHealth()
    monkeypatch.setattr(video_endpoint, "digital_human_client", timeout_client)
    monkeypatch.setattr(video_service_module, "digital_human_client", timeout_client)
    timeout_response = client.post(f"/api/v1/video-gen/node/{nodes[1].id}/generate?force=true", headers=teacher_headers)
    assert timeout_response.status_code == 500
    session.expire_all()
    timeout_task = session.exec(
        select(VideoGenerationTask).where(VideoGenerationTask.node_id == nodes[1].id)
    ).first()
    assert timeout_task is not None
    assert timeout_task.status == GenerationStatus.FAILED
    assert "fake service timeout" in timeout_task.error_message

    business_failure_client = FakeDigitalHumanClient("business_failure")
    monkeypatch.setattr(video_endpoint, "digital_human_client", business_failure_client)
    monkeypatch.setattr(video_service_module, "digital_human_client", business_failure_client)
    business_failure_response = client.post(f"/api/v1/video-gen/node/{nodes[1].id}/generate?force=true", headers=teacher_headers)
    assert business_failure_response.status_code == 200
    business_failure_payload = business_failure_response.json()
    assert business_failure_payload["code"] == 200
    assert business_failure_payload["data"]["status"] == GenerationStatus.FAILED.value
    assert business_failure_payload["data"]["dh_video_path"] in (None, "")
    assert BUSINESS_FAILURE_MESSAGE in business_failure_payload["data"]["error_message"]
    session.expire_all()
    task = session.get(VideoGenerationTask, business_failure_payload["data"]["id"])
    assert task.status == GenerationStatus.FAILED
    assert task.dh_video_path in (None, "")
    assert BUSINESS_FAILURE_MESSAGE in task.error_message

    import app.services.ppt_generation_service as ppt_service_module
    import app.common.slide_converter as slide_converter
    ppt_dir = test_artifact_dir / "pptx"
    ppt_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ppt_service_module.ppt_generation_service, "ppt_storage_path", str(ppt_dir))
    monkeypatch.setattr(slide_converter, "get_or_create_pdf", lambda path: None)

    monkeypatch.setattr(ppt_service_module.ppt_generation_service, "xfyun_client", FakePPTClient("success"))
    ppt_success_response = client.post(
        "/api/v1/ppt/generate-sync",
        headers=teacher_headers,
        json={
            "topic": "M4B Fake PPT Success",
            "outline": "One lesson",
            "knowledge_points": ["binary search"],
            "template_id": "fake-template",
            "author": "M4B",
            "search": False,
            "auto_parse": False,
        },
    )
    assert ppt_success_response.status_code == 200
    assert ppt_success_response.json()["code"] == 200
    assert ppt_success_response.json()["data"]["ppt_file_path"].startswith(str(ppt_dir))

    monkeypatch.setattr(ppt_service_module.ppt_generation_service, "xfyun_client", FakePPTClient("business_failure"))
    ppt_failure_response = client.post(
        "/api/v1/ppt/generate-sync",
        headers=teacher_headers,
        json={
            "topic": "M4B Fake PPT Failure",
            "outline": "One lesson",
            "knowledge_points": ["recursion"],
            "template_id": "fake-template",
            "author": "M4B",
            "search": False,
            "auto_parse": False,
        },
    )
    assert ppt_failure_response.status_code == 200
    ppt_failure_payload = ppt_failure_response.json()
    assert ppt_failure_payload["code"] == 500
    assert ppt_failure_payload["data"]["status"] == "failed"
    assert ppt_failure_payload["data"]["error"] == BUSINESS_FAILURE_MESSAGE