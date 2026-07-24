"""
知识点↔PPT页面映射管理API
提供映射关系的查询、自动生成、AI匹配、手动调整、应用到脚本等操作
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.course_model import Course, CourseScript, ScriptNode
from app.models.mapping_model import KnowledgePageMap
from app.services.mapping_service import mapping_service
from app.services.course_access_service import CourseAccessContext, course_permission

router = APIRouter(tags=["知识点映射"])


# ---------- 请求模型 ----------

class NodeMappingUpdate(BaseModel):
    """单个节点映射更新"""
    node_id: int
    page_start: int
    page_end: int


class BatchMappingUpdate(BaseModel):
    """批量映射更新"""
    updates: List[NodeMappingUpdate]


# ---------- API接口 ----------

@router.get("/{course_id}")
async def get_mapping(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("knowledge.view")),
):
    """
    获取课程的完整映射详情
    包括：知识点列表、PPT页面文本、当前映射关系
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    detail = mapping_service.get_mapping_detail(session, course_id)
    return unified_response(code=200, message="获取映射详情成功", data=detail)


@router.get("/{course_id}/pages")
async def get_page_texts(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("knowledge.view")),
):
    """
    获取PPT逐页文本内容（用于前端展示）
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    pages = mapping_service.get_page_texts(session, course_id)
    return unified_response(
        code=200,
        message="获取页面文本成功",
        data={"pages": pages, "total": len(pages)},
    )


@router.post("/{course_id}/auto")
async def auto_generate_mapping(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.mapping.edit")),
):
    """
    自动生成映射关系（基于ScriptNode已有的page_start/page_end）
    保留手动调整的映射不变
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    mappings = mapping_service.auto_map_from_nodes(session, course_id)

    return unified_response(
        code=200,
        message=f"自动映射生成成功，共 {len(mappings)} 条映射",
        data={
            "total": len(mappings),
            "mappings": [
                {
                    "id": m.id,
                    "node_id": m.node_id,
                    "page_start": m.page_start,
                    "page_end": m.page_end,
                    "confidence": m.confidence,
                    "is_manual": m.is_manual,
                }
                for m in mappings
            ],
        },
    )


@router.post("/{course_id}/ai-match")
async def ai_match_mapping(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.mapping.edit")),
):
    """
    AI语义匹配：使用LLM分析知识点与PPT页面的语义相似度
    重新计算映射关系，保留手动调整的映射不变
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    mappings = await mapping_service.ai_match_mapping(session, course_id)

    return unified_response(
        code=200,
        message=f"AI匹配完成，共 {len(mappings)} 条映射",
        data={
            "total": len(mappings),
            "mappings": [
                {
                    "id": m.id,
                    "node_id": m.node_id,
                    "page_start": m.page_start,
                    "page_end": m.page_end,
                    "confidence": m.confidence,
                    "is_manual": m.is_manual,
                }
                for m in mappings
            ],
        },
    )


@router.put("/{course_id}/nodes/{node_id}")
async def update_node_mapping(
    course_id: int,
    node_id: int,
    update: NodeMappingUpdate,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.mapping.edit")),
):
    """
    手动调整单个知识点的映射关系
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    node = session.get(ScriptNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="脚本节点不存在")

    if update.page_start < 1 or update.page_end < update.page_start:
        raise HTTPException(status_code=400, detail="页码范围无效")

    mapping = mapping_service.update_node_mapping(
        session, course_id, node_id, update.page_start, update.page_end
    )

    return unified_response(
        code=200,
        message="映射更新成功",
        data={
            "id": mapping.id,
            "node_id": mapping.node_id,
            "page_start": mapping.page_start,
            "page_end": mapping.page_end,
            "is_manual": mapping.is_manual,
        },
    )


@router.put("/{course_id}/batch")
async def batch_update_mapping(
    course_id: int,
    batch: BatchMappingUpdate,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.mapping.edit")),
):
    """
    批量更新映射关系
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    mappings = mapping_service.batch_update_mappings(
        session, course_id, [u.model_dump() for u in batch.updates]
    )

    return unified_response(
        code=200,
        message=f"批量更新成功，共 {len(mappings)} 条",
        data={
            "total": len(mappings),
        },
    )


@router.post("/{course_id}/apply")
async def apply_mapping_to_script(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.mapping.edit")),
):
    """
    将映射关系应用到脚本节点
    更新 ScriptNode 的 page_start/page_end
    视频生成前必须调用此接口
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    success = mapping_service.apply_mappings_to_script(session, course_id)

    if success:
        return unified_response(code=200, message="映射已应用到脚本，视频生成时将使用新的映射关系", data=None)
    else:
        raise HTTPException(status_code=400, detail="没有映射关系可应用，请先生成映射")
