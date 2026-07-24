"""
引用稳定定位 API
根据课程和节点定位原文位置，使用已有的 DoclingDocument / ScriptNode 数据。
不依赖 admin-only evidence-v2 影子端点。
"""

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from typing import Optional

from app.core.security import get_current_user
from app.core.exceptions import unified_response
from app.models.database import get_session
from app.models.course_model import Course, CourseScript, ScriptNode, DoclingDocument, DoclingText, StudentEnrollment

router = APIRouter()


@router.get("/locate")
async def locate_citation(
    course_id: int = Query(..., description="课程ID"),
    node_id: Optional[int] = Query(None, description="节点ID"),
    query: Optional[str] = Query(None, description="搜索关键词"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """根据课程+节点定位原文位置"""
    user_id = int(current_user["user_id"])
    user_role = current_user.get("role", "student")

    course = session.get(Course, course_id)
    if not course:
        return unified_response(code=404, message="课程不存在", data=None)

    # 权限校验：教师须为课程归属者，学生须已选课，管理员放行
    if user_role != "admin":
        if user_role == "teacher" and str(course.teacher_id) != str(user_id):
            return unified_response(code=403, message="无权访问此课程", data=None)
        if user_role == "student":
            enrollment = session.exec(
                select(StudentEnrollment).where(
                    StudentEnrollment.course_id == course_id,
                    StudentEnrollment.student_id == user_id,
                )
            ).first()
            if not enrollment:
                return unified_response(code=403, message="您尚未选修此课程", data=None)

    # 查询关联的 DoclingDocument
    docling_doc = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()

    if not docling_doc:
        return unified_response(
            code=200,
            message="课程暂未关联原文文档",
            data={
                "document_id": None,
                "course_id": course_id,
                "node_id": node_id,
                "page_start": None,
                "page_end": None,
                "snippet": None,
                "match_type": "none",
                "source_file": None,
            },
        )

    document_id = str(docling_doc.id)
    source_file = docling_doc.origin_filename or ""

    page_start = None
    page_end = None
    snippet = None
    match_type = "none"

    if node_id:
        node = session.get(ScriptNode, node_id)
        if node:
            page_start = node.page_start
            page_end = node.page_end
            if page_start is not None:
                match_type = "exact"

            # 尝试获取原文片段
            if page_start is not None:
                texts = session.exec(
                    select(DoclingText)
                    .where(DoclingText.doc_id == docling_doc.id)
                    .where(DoclingText.page_no == page_start)
                    .order_by(DoclingText.sort_order)
                ).all()
                if texts:
                    snippet = " ".join([t.text for t in texts[:5]])[:500]

    # 如果有 query 参数，尝试文本匹配
    if query and not snippet:
        texts = session.exec(
            select(DoclingText)
            .where(DoclingText.doc_id == docling_doc.id)
            .where(DoclingText.text.contains(query))
        ).all()
        if texts:
            snippet = texts[0].text[:500]
            match_type = "approximate"
            if texts[0].page_no:
                page_start = texts[0].page_no

    return unified_response(
        code=200,
        message="定位成功",
        data={
            "document_id": document_id,
            "course_id": course_id,
            "node_id": node_id,
            "page_start": page_start,
            "page_end": page_end,
            "snippet": snippet,
            "match_type": match_type,
            "source_file": source_file,
        },
    )
