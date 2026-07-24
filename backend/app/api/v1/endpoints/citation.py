"""Stable course-scoped source-location API."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.models.course_model import Course, CourseScript, DoclingDocument, DoclingText, ScriptNode
from app.models.database import get_session
from app.services.course_access_service import CourseAccessContext, course_permission

router = APIRouter()


@router.get("/locate")
async def locate_citation(
    course_id: int = Query(..., description="课程 ID"),
    node_id: Optional[int] = Query(None, description="节点 ID"),
    query: Optional[str] = Query(None, description="搜索关键词"),
    session: Session = Depends(get_session),
    _access: CourseAccessContext = Depends(course_permission("course.citation.read")),
):
    """Locate a source passage after one course-scoped permission decision."""
    course = session.get(Course, course_id)
    if course is None:
        return unified_response(code=404, message="课程不存在", data=None)

    document = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()
    if document is None:
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

    page_start = None
    page_end = None
    snippet = None
    match_type = "none"
    if node_id is not None:
        node = session.get(ScriptNode, node_id)
        # A node from another script must not be used to locate an unrelated
        # course document.
        script = session.get(CourseScript, node.script_id) if node is not None else None
        if node is not None and script is not None and script.course_id == course_id:
            page_start = node.page_start
            page_end = node.page_end
            match_type = "exact" if page_start is not None else "none"
            if page_start is not None:
                texts = session.exec(
                    select(DoclingText)
                    .where(DoclingText.doc_id == document.id)
                    .where(DoclingText.page_no == page_start)
                    .order_by(DoclingText.sort_order)
                ).all()
                if texts:
                    snippet = " ".join(text.text for text in texts[:5])[:500]

    if query and not snippet:
        texts = session.exec(
            select(DoclingText)
            .where(DoclingText.doc_id == document.id)
            .where(DoclingText.text.contains(query))
            .order_by(DoclingText.page_no, DoclingText.sort_order)
        ).all()
        if texts:
            snippet = texts[0].text[:500]
            page_start = texts[0].page_no
            match_type = "approximate"

    return unified_response(
        code=200,
        message="定位成功",
        data={
            "document_id": str(document.id),
            "course_id": course_id,
            "node_id": node_id,
            "page_start": page_start,
            "page_end": page_end,
            "snippet": snippet,
            "match_type": match_type,
            "source_file": document.origin_filename or "",
        },
    )
