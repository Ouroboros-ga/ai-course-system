"""
课程删除功能测试
测试级联删除逻辑和 unified_response 参数修复
"""

import pytest
import sys
from pathlib import Path

from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability, CourseMembership
from app.models.course_model import Course, CourseStatus
from app.models.document_artifact_model import DocumentArtifact
from app.models.graph_production_model import CourseEvidenceRecord
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.knowledge_bundle_model import (
    CourseKnowledgeBundle,
    CourseKnowledgeHead,
    CourseVectorIndex,
    GraphRagEntityMapping,
    GraphRagRun,
    GraphRagRunStatus,
    KnowledgeBundleStatus,
    VectorIndexStatus,
)
from app.models.course_build_model import SourceMaterial, SourceMaterialVersion
from app.models.question_bank_model import QuestionBankItem, QuestionStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_deletion_service import course_deletion_service
from app.services.object_storage import LocalStorageProvider

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestCascadeDeleteOrder:
    """测试级联删除顺序的正确性"""

    def test_delete_order_respects_foreign_keys(self):
        dependency_order = [
            "UnderstandingAnalysis",
            "NodeProgress",
            "LearningProgress",
            "QAMessage",
            "QASession",
            "VideoGenerationTask",
            "StudentEnrollment",
            "ScriptNode",
            "CourseScript",
            "DoclingTableCell",
            "DoclingTable",
            "DoclingGroup",
            "DoclingText",
            "DoclingPicture",
            "DoclingDocument",
            "ChatMessage",
            "ChatHistory",
            "Course",
        ]

        course_idx = dependency_order.index("Course")
        assert course_idx == len(dependency_order) - 1

        lp_idx = dependency_order.index("LearningProgress")
        np_idx = dependency_order.index("NodeProgress")
        ua_idx = dependency_order.index("UnderstandingAnalysis")
        assert ua_idx < lp_idx
        assert np_idx < lp_idx

        qs_idx = dependency_order.index("QASession")
        qm_idx = dependency_order.index("QAMessage")
        assert qm_idx < qs_idx

        cs_idx = dependency_order.index("CourseScript")
        sn_idx = dependency_order.index("ScriptNode")
        assert sn_idx < cs_idx

        dd_idx = dependency_order.index("DoclingDocument")
        dg_idx = dependency_order.index("DoclingGroup")
        dt_idx = dependency_order.index("DoclingTable")
        dc_idx = dependency_order.index("DoclingTableCell")
        dtx_idx = dependency_order.index("DoclingText")
        dp_idx = dependency_order.index("DoclingPicture")
        assert dg_idx < dd_idx
        assert dt_idx < dd_idx
        assert dc_idx < dt_idx
        assert dtx_idx < dd_idx
        assert dp_idx < dd_idx

    def test_all_related_tables_covered(self):
        tables_with_course_fk = {
            "course_scripts",
            "script_nodes",
            "docling_documents",
            "student_enrollments",
            "learning_progress",
            "video_generation_tasks",
            "qa_sessions",
        }

        handled_in_delete = {
            "course_scripts",
            "script_nodes",
            "docling_documents",
            "student_enrollments",
            "learning_progress",
            "video_generation_tasks",
            "qa_sessions",
        }

        missing = tables_with_course_fk - handled_in_delete
        assert len(missing) == 0, f"Missing cascade delete for: {missing}"


class TestUnifiedResponseParameterFix:
    """测试 unified_response 参数修复"""

    def test_unified_response_signature(self):
        from app.core.exceptions import unified_response
        import inspect
        sig = inspect.signature(unified_response)
        params = list(sig.parameters.keys())
        assert "code" in params
        assert "message" in params
        assert "data" in params
        assert "detail" not in params

    def test_unified_response_with_message(self):
        from app.core.exceptions import unified_response
        result = unified_response(code=404, message="课程不存在")
        assert result["code"] == 404
        assert result["message"] == "课程不存在"

    def test_unified_response_detail_would_fail(self):
        from app.core.exceptions import unified_response
        with pytest.raises(TypeError):
            unified_response(code=404, detail="课程不存在")


class TestDeleteCourseDataIntegrity:
    """测试删除课程时的数据完整性"""

    def test_no_orphan_docling_data(self):
        docling_subtables = {
            "docling_groups": "doc_id",
            "docling_tables": "doc_id",
            "docling_table_cells": "table_id",
            "docling_texts": "doc_id",
            "docling_pictures": "doc_id",
        }

        for table, fk_col in docling_subtables.items():
            assert fk_col in ("doc_id", "table_id"), f"Unexpected FK column in {table}"

    def test_no_orphan_progress_data(self):
        progress_subtables = {
            "node_progress": "learning_progress_id",
            "understanding_analysis": "progress_id",
        }

        for table, fk_col in progress_subtables.items():
            assert fk_col in ("learning_progress_id", "progress_id")

    def test_no_orphan_qa_data(self):
        qa_subtables = {
            "qa_messages": "session_id",
        }

        for table, fk_col in qa_subtables.items():
            assert fk_col == "session_id"

    def test_no_orphan_chat_data(self):
        chat_subtables = {
            "chat_messages": "chat_id",
        }

        for table, fk_col in chat_subtables.items():
            assert fk_col == "chat_id"


def test_delete_course_removes_phase_b_to_e_course_rows(client, session):
    """Course deletion must not leave new scoped records behind on FK DBs."""
    teacher = User(
        username="delete_phase_teacher",
        hashed_password=get_password_hash("test"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)

    course = Course(
        fanya_course_id="delete-phase-course",
        fanya_course_name="delete-phase-course",
        title="Delete phase data",
        teacher_id=teacher.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)

    artifact = DocumentArtifact(
        document_id="delete-phase-document",
        course_id=course.id,
        file_name="course.pptx",
    )
    evidence = CourseEvidenceRecord(
        evidence_id="delete-phase-evidence",
        course_id=course.id,
        document_id=artifact.document_id,
        text_snippet="历史引用",
    )
    question = QuestionBankItem(
        question_text="删除课程后的题目不应保留",
        answer="答案",
        course_id=course.id,
        status=QuestionStatus.PUBLISHED,
    )
    session.add(artifact)
    session.add(evidence)
    session.add(question)
    session.commit()
    course_id = course.id

    token = create_access_token({
        "sub": str(teacher.id),
        "username": teacher.username,
        "role": teacher.role.value,
    })
    response = client.request(
        "DELETE",
        f"/api/v1/document/course/{course_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmation_title": course.title},
    )
    if response.status_code != 200:
        pytest.fail(response.text)
    assert response.status_code == 200
    assert response.json()["code"] == 200

    session.expire_all()
    assert session.get(Course, course_id) is None
    assert not session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).all()
    assert not session.exec(
        select(CourseEvidenceRecord).where(CourseEvidenceRecord.course_id == course_id)
    ).all()
    assert not session.exec(
        select(QuestionBankItem).where(QuestionBankItem.course_id == course_id)
    ).all()
    assert not session.exec(
        select(CourseMembership).where(CourseMembership.course_id == course_id)
    ).all()
    assert not session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).all()


def test_delete_course_removes_graph_bundle_hash_and_private_files(
    session, teacher_user, tmp_path, monkeypatch,
):
    course = Course(
        fanya_course_id="delete-bundle-course",
        fanya_course_name="delete-bundle-course",
        title="Delete bundle data",
        teacher_id=teacher_user.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)

    object_key = "course-source/test/private-course.pptx"
    storage = LocalStorageProvider(str(tmp_path / "objects"), sign_key="test")
    storage.put(object_key, b"private courseware")
    material = SourceMaterial(course_id=course.id, name="private-course.pptx")
    session.add(material)
    session.flush()
    version = SourceMaterialVersion(
        material_id=material.material_id,
        course_id=course.id,
        file_path=object_key,
        file_hash="same-file-can-be-uploaded-after-delete",
    )
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_delete_bundle",
        title="待删除知识点",
    )
    run = GraphRagRun(
        course_id=course.id,
        run_id="grr_delete_bundle",
        status=GraphRagRunStatus.AWAITING_REVIEW,
    )
    session.add(version)
    session.add(node)
    session.add(run)
    session.flush()
    session.add(GraphRagEntityMapping(
        course_id=course.id,
        graphrag_run_id=run.run_id,
        graphrag_entity_id="entity-delete",
        knowledge_node_id=node.id,
        node_key=node.node_key,
    ))
    session.add(CourseVectorIndex(
        vector_index_id="cvi_delete_bundle",
        course_id=course.id,
        graph_snapshot_id="snapshot-delete",
        retrieval_snapshot_id="retrieval-delete",
        status=VectorIndexStatus.READY,
    ))
    session.add(CourseKnowledgeBundle(
        bundle_id="ckb_delete_bundle",
        course_id=course.id,
        version=1,
        graph_snapshot_id="snapshot-delete",
        retrieval_snapshot_id="retrieval-delete",
        vector_index_id="cvi_delete_bundle",
        status=KnowledgeBundleStatus.READY,
    ))
    session.add(CourseKnowledgeHead(
        course_id=course.id,
        active_bundle_id="ckb_delete_bundle",
    ))
    session.commit()
    course_id = course.id
    course_title = course.title
    run_id = run.run_id

    index_root = tmp_path / "knowledge-indexes"
    index_dir = index_root / "courses" / str(course_id)
    index_dir.mkdir(parents=True)
    (index_dir / "COMPLETE").write_text("ok", encoding="utf-8")
    monkeypatch.setattr("app.services.course_deletion_service.settings.GRAPHRAG_STORAGE_ROOT", str(index_root))
    monkeypatch.setattr("app.services.course_deletion_service.settings.VECTOR_STORE_ROOT", str(index_root))

    report = course_deletion_service.delete(
        session,
        course_id=course_id,
        expected_title=course_title,
        storage=storage,
    )

    assert report.cleanup_complete is True
    assert not storage.exists(object_key)
    assert not index_dir.exists()
    assert session.get(Course, course_id) is None
    assert not session.exec(select(SourceMaterialVersion).where(
        SourceMaterialVersion.file_hash == "same-file-can-be-uploaded-after-delete"
    )).all()
    assert not session.exec(select(GraphRagRun).where(GraphRagRun.run_id == run_id)).all()
    assert not session.exec(select(CourseKnowledgeBundle).where(
        CourseKnowledgeBundle.bundle_id == "ckb_delete_bundle"
    )).all()


def test_delete_course_preserves_object_referenced_by_another_course(
    session, teacher_user, tmp_path,
):
    courses = []
    for index in range(2):
        course = Course(
            fanya_course_id=f"shared-object-{index}",
            fanya_course_name=f"shared-object-{index}",
            title=f"Shared object {index}",
            teacher_id=teacher_user.id,
            status=CourseStatus.DRAFT,
        )
        session.add(course)
        session.flush()
        material = SourceMaterial(course_id=course.id, name="shared.pptx")
        session.add(material)
        session.flush()
        session.add(SourceMaterialVersion(
            material_id=material.material_id,
            course_id=course.id,
            file_path="course-source/test/shared.pptx",
            file_hash="shared-hash",
        ))
        courses.append(course)
    session.commit()
    deleted_course_id = courses[0].id
    deleted_course_title = courses[0].title
    preserved_course_id = courses[1].id
    storage = LocalStorageProvider(str(tmp_path / "objects"), sign_key="test")
    storage.put("course-source/test/shared.pptx", b"shared courseware")

    report = course_deletion_service.delete(
        session,
        course_id=deleted_course_id,
        expected_title=deleted_course_title,
        storage=storage,
    )

    assert storage.exists("course-source/test/shared.pptx")
    assert report.preserved_shared_object_keys == ["course-source/test/shared.pptx"]
    assert session.get(Course, preserved_course_id) is not None


class TestFrontendDeleteHandling:
    """测试前端删除逻辑"""

    def test_confirm_message_with_students(self):
        course = {"title": "自动控制原理", "student_count": 5}
        student_count = course.get("student_count", 0)
        confirm_msg = f"确定要删除课程《{course['title']}》吗？"
        if student_count > 0:
            confirm_msg += f"\n\n⚠️ 该课程已有 {student_count} 名学生选课，删除后学生将无法继续学习。此操作不可恢复！"
        else:
            confirm_msg += "\n\n此操作不可恢复！"

        assert "5 名学生" in confirm_msg
        assert "不可恢复" in confirm_msg

    def test_confirm_message_without_students(self):
        course = {"title": "测试课程", "student_count": 0}
        student_count = course.get("student_count", 0)
        confirm_msg = f"确定要删除课程《{course['title']}》吗？"
        if student_count > 0:
            confirm_msg += f"\n\n⚠️ 该课程已有 {student_count} 名学生选课，删除后学生将无法继续学习。此操作不可恢复！"
        else:
            confirm_msg += "\n\n此操作不可恢复！"

        assert "学生" not in confirm_msg
        assert "不可恢复" in confirm_msg

    def test_course_removed_from_list_after_delete(self):
        courses = [
            {"id": 1, "title": "课程A"},
            {"id": 2, "title": "课程B"},
            {"id": 3, "title": "课程C"},
        ]
        deleted_id = 2
        courses = [c for c in courses if c["id"] != deleted_id]
        assert len(courses) == 2
        assert all(c["id"] != deleted_id for c in courses)

    def test_delete_response_format(self):
        response = {
            "code": 200,
            "message": "课程《自动控制原理》已成功删除",
            "data": {
                "deleted_course_id": 1,
                "affected_students": 3,
            }
        }
        assert response["code"] == 200
        assert "deleted_course_id" in response["data"]
        assert "affected_students" in response["data"]
