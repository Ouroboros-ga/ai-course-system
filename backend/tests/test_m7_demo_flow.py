import importlib
import json

from sqlmodel import select

from app.common.llm_client import LLMResponse
from app.models.course_model import (
    Course,
    CourseScript,
    CourseStatus,
    DoclingDocument,
    ParseStatus,
    ScriptNode,
)
from app.models.mapping_model import KnowledgePageMap
from app.models.progress_model import LearningJumpHistory, LearningProgress
from app.models.user_model import ChatMessage, UserRole
from app.models.video_generation_model import GenerationStatus, VideoGenerationTask
from app.services.document_service import ScriptNode as ServiceScriptNode
from test_m4b_main_flows import _create_user, _fake_document_result


def _m7_document_result(filename: str):
    result = _fake_document_result(filename)
    result.structure_result.texts.append({
        "self_ref": "#/texts/1",
        "label": "text",
        "text": "Recursion requires a base case.",
        "page_no": 2,
    })
    result.structure_result.raw_content += " Recursion requires a base case."
    result.script_result.nodes.append(
        ServiceScriptNode(
            chapter_id="kp_upload_2",
            node_type="lecture",
            title="Recursion and Base Cases",
            content="Recursion content with enough text for TTS and prerequisite review testing.",
            page_start=2,
            page_end=2,
            duration=60,
            is_key_point=True,
            timestamp_start=60.0,
            timestamp_end=120.0,
        )
    )
    result.script_result.total_duration = 120
    result.script_result.script_content = {
        "title": "M7 Demo Lesson",
        "nodes": [
            {"title": "Binary Search"},
            {"title": "Recursion and Base Cases"},
        ],
    }
    result.rag_result.knowledge_points.append({
        "id": "kp_upload_2",
        "title": "Recursion",
    })
    return result


def _login_headers(client, username: str) -> dict:
    response = client.post(
        "/api/v1/user/login",
        json={"username": username, "password": "test-password"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    return {"Authorization": f"Bearer {payload['data']['token']}"}


def test_m7_complete_demo_flow_uses_only_controlled_external_fakes(
    client,
    session,
    monkeypatch,
    test_artifact_dir,
):
    teacher = _create_user(session, UserRole.TEACHER, "m7_demo_teacher")
    student = _create_user(session, UserRole.STUDENT, "m7_demo_student")
    teacher_headers = _login_headers(client, teacher.username)
    student_headers = _login_headers(client, student.username)

    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")
    upload_dir = test_artifact_dir / "m7_uploads"
    audio_dir = test_artifact_dir / "m7_audio"
    upload_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(document_endpoint, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(document_endpoint, "AUDIO_STORAGE_DIR", audio_dir)

    async def no_background_audio(course_id: int, script_id: int):
        return None

    async def fake_process_document(file_path, filename, enable_rag=True, enable_script=True, course_id=None):
        return _m7_document_result(filename)

    monkeypatch.setattr(document_endpoint, "_background_synthesize_audio", no_background_audio)
    monkeypatch.setattr(document_endpoint.document_service, "process_document", fake_process_document)

    upload_response = client.post(
        "/api/v1/document/upload",
        headers=teacher_headers,
        files={
            "file": (
                "M7_demo_lesson.md",
                b"# Binary Search\n\nSorted data.\n\n# Recursion\n\nBase case.",
                "text/markdown",
            )
        },
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["code"] == 200
    course_id = upload_payload["data"]["courseId"]

    session.expire_all()
    course = session.get(Course, course_id)
    document = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()
    script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course_id,
            CourseScript.is_active == True,
        )
    ).first()
    nodes = list(
        session.exec(
            select(ScriptNode)
            .where(ScriptNode.script_id == script.id)
            .order_by(ScriptNode.node_index)
        ).all()
    )
    assert course is not None and course.total_nodes == 2
    assert document is not None and document.status == ParseStatus.COMPLETED
    assert document.total_texts == 2
    assert script is not None and len(nodes) == 2

    ppt_service_module = importlib.import_module("app.services.ppt_generation_service")
    slide_converter = importlib.import_module("app.common.slide_converter")
    ppt_dir = test_artifact_dir / "m7_ppt"
    monkeypatch.setattr(ppt_service_module.ppt_generation_service, "ppt_storage_path", str(ppt_dir))
    monkeypatch.setattr(slide_converter, "get_or_create_pdf", lambda path: None)
    ppt_response = client.post(
        "/api/v1/ppt/generate-sync",
        headers=teacher_headers,
        json={
            "topic": "M7 Binary Search and Recursion",
            "outline": "Binary search; recursion; quiz",
            "knowledge_points": ["binary search", "recursion"],
            "template_id": "fake-template",
            "author": "M7",
            "search": False,
            "auto_parse": False,
        },
    )
    assert ppt_response.status_code == 200
    assert ppt_response.json()["code"] == 200

    mapping_response = client.post(f"/api/v1/mapping/{course_id}/auto", headers=teacher_headers)
    assert mapping_response.status_code == 200
    assert mapping_response.json()["code"] == 200
    apply_mapping_response = client.post(
        f"/api/v1/mapping/{course_id}/apply",
        headers=teacher_headers,
    )
    assert apply_mapping_response.status_code == 200
    assert apply_mapping_response.json()["code"] == 200
    session.expire_all()
    assert len(
        session.exec(
            select(KnowledgePageMap).where(KnowledgePageMap.course_id == course_id)
        ).all()
    ) == 2

    tts_response = client.post(
        f"/api/v1/document/course/{course_id}/synthesize-all-audio",
        headers=teacher_headers,
    )
    assert tts_response.status_code == 200
    assert tts_response.json()["code"] == 200
    assert tts_response.json()["data"]["success_count"] == 2
    session.expire_all()
    nodes = [session.get(ScriptNode, node.id) for node in nodes]
    assert all(node.audio_url and node.audio_duration > 0 for node in nodes)

    video_service_module = importlib.import_module("app.services.video_generation_service")
    monkeypatch.setattr(
        video_service_module,
        "AUDIO_ROOT",
        test_artifact_dir / "m7_video_audio",
    )
    monkeypatch.setattr(
        video_service_module,
        "GENERATED_ROOT",
        test_artifact_dir / "m7_video_generated",
    )

    async def fake_resolve_face_video(face_video_asset_id, node, db_session):
        face_path = test_artifact_dir / "m7_face.mp4"
        face_path.write_bytes(b"CONTROLLED_TEST_FACE_VIDEO")
        return str(face_path)

    monkeypatch.setattr(
        video_service_module.video_generation_service,
        "_resolve_face_video",
        fake_resolve_face_video,
    )
    video_response = client.post(
        f"/api/v1/video-gen/node/{nodes[0].id}/generate?force=true",
        headers=teacher_headers,
    )
    assert video_response.status_code == 200
    video_payload = video_response.json()
    assert video_payload["code"] == 200
    assert video_payload["data"]["status"] == GenerationStatus.COMPLETED.value
    task_id = video_payload["data"]["id"]
    task_response = client.get(f"/api/v1/video-gen/task/{task_id}", headers=teacher_headers)
    assert task_response.status_code == 200
    assert task_response.json()["data"]["status"] == GenerationStatus.COMPLETED.value

    publish_response = client.post(
        f"/api/v1/document/course/{course_id}/publish",
        headers=teacher_headers,
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["code"] == 200
    session.expire_all()
    assert session.get(Course, course_id).status == CourseStatus.PUBLISHED

    enroll_response = client.post(
        f"/api/v1/document/course/{course_id}/enroll",
        headers=student_headers,
    )
    assert enroll_response.status_code == 200
    assert enroll_response.json()["code"] == 200
    assert enroll_response.json()["data"]["total_nodes"] == 2

    player_response = client.get(f"/api/v1/player/init/{course_id}", headers=student_headers)
    assert player_response.status_code == 200
    player_payload = player_response.json()
    assert player_payload["course_id"] == course_id
    assert len(player_payload["nodes"]) == 2
    assert player_payload["nodes"][0]["status"] == "completed"
    assert player_payload["nodes"][0]["video_url"]
    assert player_payload["ppt_pages"]

    save_response = client.post(
        "/api/v1/player/progress/save",
        headers=student_headers,
        json={
            "course_id": course_id,
            "current_node_id": nodes[0].id,
            "current_timestamp": 15.0,
            "current_page": 1,
            "completed_nodes": [nodes[0].id],
        },
    )
    assert save_response.status_code == 200
    assert save_response.json()["code"] == 200
    session.expire_all()
    progress = session.exec(
        select(LearningProgress).where(
            LearningProgress.user_id == student.id,
            LearningProgress.course_id == course_id,
        )
    ).first()
    assert progress is not None and progress.current_node_id == nodes[0].id

    chat_response = client.post(
        "/api/v1/chat/ask",
        headers=student_headers,
        json={"courseId": course_id, "question": "Why must binary search use sorted data?"},
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["code"] == 200
    assert chat_payload["data"]["answer"] == "fake llm response"
    assert session.exec(
        select(ChatMessage).where(ChatMessage.chat_id == chat_payload["data"]["chatId"])
    ).all()

    class QuizLLMClient:
        async def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
            return LLMResponse(
                content=json.dumps({
                    "question": "What is required for binary search?",
                    "options": {"A": "Sorted data", "B": "Random data"},
                    "correct_answer": "A",
                    "explanation": "The midpoint comparison relies on ordering.",
                }),
                usage={},
                model="m7-fake-quiz",
                finish_reason="stop",
                latency_ms=1.0,
            )

    qa_service_module = importlib.import_module("app.services.qa_service")
    monkeypatch.setattr(qa_service_module, "llm_client", QuizLLMClient())
    quiz_response = client.post(
        "/api/v1/chat/quiz",
        headers=student_headers,
        json={"courseId": course_id, "nodeId": nodes[0].id},
    )
    assert quiz_response.status_code == 200
    assert quiz_response.json()["data"]["quiz"]["correct_answer"] == "A"

    class FakePrerequisiteAnalyzer:
        async def analyze_prerequisite_gaps(self, **kwargs):
            return {
                "has_gaps": True,
                "overall_confidence": 0.9,
                "weak_prerequisites": [
                    {"prerequisiteId": nodes[0].id, "title": nodes[0].title}
                ],
                "suggested_action": "jump_to_review",
                "analysis_summary": "Review binary search before recursion.",
            }

    prerequisite_endpoint = importlib.import_module("app.api.v1.endpoints.prerequisite")
    monkeypatch.setattr(
        prerequisite_endpoint,
        "prerequisite_analyzer",
        FakePrerequisiteAnalyzer(),
    )
    analyze_response = client.post(
        "/api/v1/prerequisite/analyze-gap",
        headers=student_headers,
        json={
            "courseId": course_id,
            "currentNodeId": nodes[1].id,
            "question": "Why does recursion need a base case?",
            "conversationHistory": [],
        },
    )
    assert analyze_response.status_code == 200
    assert analyze_response.json()["data"]["hasGaps"] is True

    jump_response = client.post(
        "/api/v1/prerequisite/jump",
        headers=student_headers,
        json={
            "courseId": course_id,
            "fromNodeId": nodes[1].id,
            "fromNodeTitle": nodes[1].title,
            "fromNodeIndex": nodes[1].node_index,
            "toPrerequisiteId": nodes[0].id,
            "toNodeTitle": nodes[0].title,
            "toNodeIndex": nodes[0].node_index,
            "triggerQuestion": "Need prerequisite review",
            "gapDescription": "Missing binary-search prerequisite",
            "confidenceScore": 0.9,
            "urgencyLevel": "high",
        },
    )
    assert jump_response.status_code == 200
    jump_id = jump_response.json()["data"]["jumpId"]
    return_response = client.post(
        "/api/v1/prerequisite/return",
        headers=student_headers,
        json={"jumpId": jump_id, "reviewDurationSeconds": 60},
    )
    assert return_response.status_code == 200
    session.expire_all()
    assert session.get(LearningJumpHistory, jump_id) is not None
    assert session.get(VideoGenerationTask, task_id).status == GenerationStatus.COMPLETED
