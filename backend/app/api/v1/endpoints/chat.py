"""
聊天模块API接口
包含历史聊天记录获取等功能
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.models.database import get_session
from app.models.user_model import ChatHistory

router = APIRouter(tags=["聊天模块"])


@router.get("/history", response_model=UnifiedResponse)
async def get_chat_history(
    userId: int = Query(..., description="用户ID"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    pageSize: int = Query(20, ge=1, le=100, description="每页数量，默认20，最大100"),
    session: Session = Depends(get_session),
):
    """
    获取用户历史聊天记录（分页）
    
    用于分页获取当前用户的侧栏历史聊天记录
    """
    try:
        offset = (page - 1) * pageSize
        
        count_statement = select(ChatHistory).where(ChatHistory.user_id == userId)
        total = len(session.exec(count_statement).all())
        
        statement = (
            select(ChatHistory)
            .where(ChatHistory.user_id == userId)
            .order_by(ChatHistory.created_at.desc())
            .offset(offset)
            .limit(pageSize)
        )
        chat_records = session.exec(statement).all()
        
        list_data = [
            {
                "userId": record.user_id,
                "id": record.id,
                "content": record.content,
                "createTime": record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else "",
            }
            for record in chat_records
        ]
        
        return unified_response(
            code=200,
            message="获取成功",
            data={
                "total": total,
                "page": page,
                "pageSize": pageSize,
                "list": list_data,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取聊天记录失败: {str(e)}",
            data=None
        )


@router.post("/create", response_model=UnifiedResponse)
async def create_chat_record(
    userId: int = Query(..., description="用户ID"),
    content: str = Query(..., description="聊天内容"),
    session: Session = Depends(get_session),
):
    """
    创建新的聊天记录
    
    当用户上传文件或开始新对话时调用
    """
    try:
        chat_record = ChatHistory(
            user_id=userId,
            content=content,
        )
        session.add(chat_record)
        session.commit()
        session.refresh(chat_record)
        
        return unified_response(
            code=200,
            message="创建成功",
            data={
                "userId": chat_record.user_id,
                "id": chat_record.id,
                "content": chat_record.content,
                "createTime": chat_record.created_at.strftime("%Y-%m-%d %H:%M:%S") if chat_record.created_at else "",
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"创建聊天记录失败: {str(e)}",
            data=None
        )


@router.delete("/{chat_id}", response_model=UnifiedResponse)
async def delete_chat_record(
    chat_id: int,
    userId: int = Query(..., description="用户ID"),
    session: Session = Depends(get_session),
):
    """
    删除聊天记录
    """
    try:
        statement = select(ChatHistory).where(
            ChatHistory.id == chat_id,
            ChatHistory.user_id == userId
        )
        chat_record = session.exec(statement).first()
        
        if not chat_record:
            return unified_response(
                code=404,
                message="聊天记录不存在",
                data=None
            )
        
        session.delete(chat_record)
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
            message=f"删除聊天记录失败: {str(e)}",
            data=None
        )
