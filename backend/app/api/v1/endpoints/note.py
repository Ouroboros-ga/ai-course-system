"""
笔记管理API接口
提供学生笔记的创建、查询、更新、删除功能
"""

from typing import Optional
from app.core.time_utils import utcnow_naive

from fastapi import APIRouter, Depends, Query, Body
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.note_model import (
    Note,
    NoteTriggerSource,
)

router = APIRouter(tags=["笔记管理"])


def _note_to_dict(note: Note) -> dict:
    """将笔记对象序列化为响应字典"""
    return {
        "id": note.id,
        "user_id": note.user_id,
        "course_id": note.course_id,
        "script_id": note.script_id,
        "node_id": note.node_id,
        "node_index": note.node_index,
        "page": note.page,
        "timestamp": note.timestamp,
        "title": note.title,
        "content": note.content,
        "tags": note.tags,
        "trigger_source": note.trigger_source.value if note.trigger_source else None,
        "is_draft": note.is_draft,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


# ==================== 笔记管理接口 ====================

@router.get("", response_model=UnifiedResponse)
async def list_notes(
    course_id: Optional[int] = Query(None, description="课程ID筛选"),
    node_id: Optional[int] = Query(None, description="节点ID筛选"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取笔记列表

    支持按课程、节点筛选，仅返回当前用户的笔记
    """
    try:
        user_id = int(current_user["user_id"])

        statement = select(Note).where(Note.user_id == user_id)
        if course_id is not None:
            statement = statement.where(Note.course_id == course_id)
        if node_id is not None:
            statement = statement.where(Note.node_id == node_id)
        statement = statement.order_by(Note.updated_at.desc())

        notes = session.exec(statement).all()

        return unified_response(
            code=200,
            message="获取成功",
            data=[_note_to_dict(n) for n in notes]
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取笔记列表失败: {str(e)}",
            data=None
        )


@router.post("", response_model=UnifiedResponse)
async def create_note(
    course_id: int = Body(..., description="课程ID（必填）"),
    script_id: Optional[int] = Body(None, description="脚本ID"),
    node_id: Optional[int] = Body(None, description="节点ID"),
    node_index: Optional[int] = Body(None, description="节点索引"),
    page: Optional[int] = Body(None, description="页码"),
    timestamp: Optional[float] = Body(None, description="时间戳"),
    title: str = Body("", description="笔记标题"),
    content: str = Body("", description="笔记内容"),
    tags: list = Body([], description="标签列表"),
    trigger_source: NoteTriggerSource = Body(NoteTriggerSource.LEARN, description="触发来源"),
    is_draft: bool = Body(True, description="是否草稿"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    创建笔记

    自动绑定当前用户，并保存 course/node/page 上下文
    """
    try:
        user_id = int(current_user["user_id"])

        note = Note(
            user_id=user_id,
            course_id=course_id,
            script_id=script_id,
            node_id=node_id,
            node_index=node_index,
            page=page,
            timestamp=timestamp,
            title=title,
            content=content,
            tags=tags,
            trigger_source=trigger_source,
            is_draft=is_draft,
        )
        session.add(note)
        session.commit()
        session.refresh(note)

        return unified_response(
            code=200,
            message="笔记创建成功",
            data=_note_to_dict(note)
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"创建笔记失败: {str(e)}",
            data=None
        )


@router.get("/{note_id}", response_model=UnifiedResponse)
async def get_note(
    note_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取笔记详情（仅本人）
    """
    try:
        user_id = int(current_user["user_id"])

        note = session.get(Note, note_id)
        if not note:
            return unified_response(
                code=404,
                message="笔记不存在",
                data=None
            )

        if note.user_id != user_id:
            return unified_response(
                code=403,
                message="无权查看该笔记",
                data=None
            )

        return unified_response(
            code=200,
            message="获取成功",
            data=_note_to_dict(note)
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取笔记详情失败: {str(e)}",
            data=None
        )


@router.put("/{note_id}", response_model=UnifiedResponse)
async def update_note(
    note_id: int,
    title: Optional[str] = Body(None, description="笔记标题"),
    content: Optional[str] = Body(None, description="笔记内容"),
    tags: Optional[list] = Body(None, description="标签列表"),
    trigger_source: Optional[NoteTriggerSource] = Body(None, description="触发来源"),
    is_draft: Optional[bool] = Body(None, description="是否草稿"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    更新笔记（自动保存草稿，仅本人）
    """
    try:
        user_id = int(current_user["user_id"])

        note = session.get(Note, note_id)
        if not note:
            return unified_response(
                code=404,
                message="笔记不存在",
                data=None
            )

        if note.user_id != user_id:
            return unified_response(
                code=403,
                message="无权修改该笔记",
                data=None
            )

        if title is not None:
            note.title = title
        if content is not None:
            note.content = content
        if tags is not None:
            note.tags = tags
        if trigger_source is not None:
            note.trigger_source = trigger_source
        if is_draft is not None:
            note.is_draft = is_draft

        note.updated_at = utcnow_naive()
        session.add(note)
        session.commit()
        session.refresh(note)

        return unified_response(
            code=200,
            message="笔记更新成功",
            data=_note_to_dict(note)
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"更新笔记失败: {str(e)}",
            data=None
        )


@router.delete("/{note_id}", response_model=UnifiedResponse)
async def delete_note(
    note_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    删除笔记（仅本人）
    """
    try:
        user_id = int(current_user["user_id"])

        note = session.get(Note, note_id)
        if not note:
            return unified_response(
                code=404,
                message="笔记不存在",
                data=None
            )

        if note.user_id != user_id:
            return unified_response(
                code=403,
                message="无权删除该笔记",
                data=None
            )

        session.delete(note)
        session.commit()

        return unified_response(
            code=200,
            message="删除成功",
            data=None
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"删除笔记失败: {str(e)}",
            data=None
        )
