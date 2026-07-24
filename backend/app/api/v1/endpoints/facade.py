"""Phase A 前后端契约对齐门面层

新增门面端点，返回统一的 ViewModel，不暴露 Shadow DTO 或数据库 ID。
前端应消费此层而非直接消费零散的 V1 端点响应。

ViewModel 契约:
  - CourseOverviewViewModel: 课程概览，含能力声明、统一 document_id、结构摘要
  - CitationViewModel: 引用定位，含稳定 document_id (UUID)
  - QuizViewModel: 题目视图，含知识点关联和发布状态

所有端点使用 require_course_permission 进行课程级权限校验。
"""
from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.course_model import (
    Course,
    CourseScript,
    DoclingDocument,
    DoclingText,
    ScriptNode,
    StudentEnrollment,
)
from app.models.document_artifact_model import DocumentArtifact
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionStatus,
)
from app.services.course_access_service import (
    require_course_permission,
    serialize_access_context,
    ALL_PERMISSIONS,
)

router = APIRouter(tags=["Phase A 门面层"])


# ==================== CourseOverviewViewModel ====================

@router.get("/course/{course_id}/overview")
async def get_course_overview(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程概览门面 ViewModel

    聚合课程信息、能力声明、统一 document_id、结构摘要。
    前端消费此 ViewModel，不直接消费 V1 端点的零散响应。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])

    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 统一 document_id (DocumentArtifact.document_id UUID)
    artifact = session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).first()
    document_id = artifact.document_id if artifact else None

    # 能力声明
    capabilities = context.capabilities

    # 结构摘要
    active_script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course_id,
            CourseScript.is_active == True,
        )
    ).first()

    node_count = 0
    chapter_count = 0
    if active_script:
        nodes = session.exec(
            select(ScriptNode).where(ScriptNode.script_id == active_script.id)
        ).all()
        node_count = len(nodes)
        chapter_ids = {n.chapter_id for n in nodes if n.chapter_id}
        chapter_count = len(chapter_ids)

    # 进度摘要（学生）
    progress_summary = None
    if context.role and context.role.value == "student":
        enrollment = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == user_id,
                StudentEnrollment.course_id == course_id,
            )
        ).first()
        if enrollment:
            progress_summary = {
                "overall_progress": enrollment.overall_progress or 0,
                "avg_understanding_score": enrollment.avg_understanding_score or 0,
                "total_study_minutes": enrollment.total_study_minutes or 0,
            }

    # 权限视图
    access_view = serialize_access_context(context, ALL_PERMISSIONS)

    return unified_response(
        code=200,
        message="获取课程概览成功",
        data={
            "course_id": course_id,
            "title": course.title,
            "description": course.description or "",
            "status": course.status.value if course.status else "draft",
            "teacher_id": course.teacher_id,
            "document_id": document_id,
            "capabilities": capabilities,
            "access": access_view,
            "structure": {
                "node_count": node_count,
                "chapter_count": chapter_count,
                "total_pages": course.total_pages or 0,
                "total_duration": course.total_duration or 0,
            },
            "progress": progress_summary,
            "role": context.role.value if context.role else None,
            "participation_mode": context.participation_mode.value if context.participation_mode else None,
            "analytics_eligible": context.analytics_eligible,
        },
    )


# ==================== CitationViewModel ====================

@router.get("/course/{course_id}/citation/{node_id}")
async def get_citation_view(
    course_id: int,
    node_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """引用定位门面 ViewModel

    返回统一 document_id (UUID)，与 GET /document/{document_id} 契约一致。
    不暴露 DoclingDocument 整数主键。
    """
    require_course_permission(session, current_user, course_id, "course.citation.read")

    # 查询节点
    node = session.get(ScriptNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 验证节点属于该课程
    script = session.get(CourseScript, node.script_id) if node.script_id else None
    if not script or script.course_id != course_id:
        raise HTTPException(status_code=404, detail="节点不属于该课程")

    # 查询 DocumentArtifact 获取统一 document_id
    artifact = session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).first()
    document_id = artifact.document_id if artifact else None

    # 查询原文片段
    docling_doc = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()

    page_start = node.page_start
    page_end = node.page_end
    snippet = None

    if docling_doc and page_start is not None:
        texts = session.exec(
            select(DoclingText)
            .where(DoclingText.doc_id == docling_doc.id)
            .where(DoclingText.page_no == page_start)
        ).all()
        if texts:
            snippet = " ".join(t.text for t in texts[:5])[:500]

    return unified_response(
        code=200,
        message="获取引用定位成功",
        data={
            "document_id": document_id,
            "course_id": course_id,
            "node_id": node_id,
            "node_title": node.title or node.content[:50] if node.content else "",
            "page_start": page_start,
            "page_end": page_end,
            "snippet": snippet,
            "source_file": artifact.file_name if artifact else (docling_doc.origin_filename if docling_doc else ""),
            "return_anchor": {
                "node_id": node_id,
                "label": node.title or "",
            },
        },
    )


# ==================== QuizViewModel ====================

@router.get("/course/{course_id}/quiz")
async def get_quiz_view(
    course_id: int,
    node_id: Optional[int] = Query(None, description="按知识点筛选"),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """题目视图门面 ViewModel

    返回统一格式的题目列表，学生仅可见 published。
    关联知识点和返回锚点。
    """
    context = require_course_permission(session, current_user, course_id, "question_bank.read")

    stmt = select(QuestionBankItem).where(
        QuestionBankItem.course_id == course_id,
        QuestionBankItem.is_latest == True,
    )

    # 学生只能看 published
    if context.role and context.role.value == "student":
        stmt = stmt.where(QuestionBankItem.status == QuestionStatus.PUBLISHED)

    if node_id:
        stmt = stmt.where(QuestionBankItem.knowledge_node_ids.contains([node_id]))

    stmt = stmt.limit(limit)
    items = session.exec(stmt).all()

    return unified_response(
        code=200,
        message="获取题目视图成功",
        data={
            "course_id": course_id,
            "items": [_serialize_quiz_item(q) for q in items],
            "total": len(items),
            "role": context.role.value if context.role else None,
        },
    )


def _serialize_quiz_item(q: QuestionBankItem) -> dict[str, Any]:
    """序列化题目为 QuizViewModel"""
    return {
        "question_id": q.id,
        "question_text": q.question_text,
        "answer": q.answer,
        "options": q.options,
        "question_type": q.question_type.value,
        "difficulty": q.difficulty.value,
        "knowledge_node_ids": q.knowledge_node_ids,
        "status": q.status.value,
        "version": q.version,
        "return_anchor": {
            "node_id": q.knowledge_node_ids[0] if q.knowledge_node_ids else None,
            "label": q.category or "",
        },
    }
