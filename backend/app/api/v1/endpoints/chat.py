"""
聊天模块API接口
包含历史聊天记录获取、AI对话等功能
需要用户登录认证
"""

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException, Request, Body
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_student_allowed
from app.models.database import get_session
from app.models.user_model import ChatHistory, ChatMessage, MessageRole
from app.models.course_model import Course, CourseScript, DoclingDocument, DoclingText
from app.common.llm_client import llm_client, Message
from app.services.progress_service import progress_service

router = APIRouter(tags=["聊天模块"])


@router.get("/history", response_model=UnifiedResponse)
async def get_chat_history(
    request: Request,
    userId: int = Query(..., description="用户ID"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    pageSize: int = Query(20, ge=1, le=100, description="每页数量，默认20，最大100"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取用户历史聊天记录（分页）
    
    需要用户登录认证
    只能查看自己的聊天记录
    """
    try:
        token_user_id = int(current_user["user_id"])
        if userId != token_user_id:
            return unified_response(
                code=403,
                message="无权访问其他用户的聊天记录",
                data=None
            )
        
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


@router.get("/messages/{chat_id}", response_model=UnifiedResponse)
async def get_chat_messages(
    chat_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取会话中的所有消息
    
    需要用户登录认证
    只能查看自己的会话消息
    """
    try:
        user_id = int(current_user["user_id"])
        
        chat = session.get(ChatHistory, chat_id)
        if not chat:
            return unified_response(
                code=404,
                message="会话不存在",
                data=None
            )
        
        if chat.user_id != user_id:
            return unified_response(
                code=403,
                message="无权访问此会话",
                data=None
            )
        
        statement = (
            select(ChatMessage)
            .where(ChatMessage.chat_id == chat_id)
            .order_by(ChatMessage.created_at.asc())
        )
        messages = session.exec(statement).all()
        
        messages_data = [
            {
                "id": msg.id,
                "role": msg.role.value,
                "content": msg.content,
                "createTime": msg.created_at.strftime("%Y-%m-%d %H:%M:%S") if msg.created_at else "",
            }
            for msg in messages
        ]
        
        return unified_response(
            code=200,
            message="获取成功",
            data={
                "chatId": chat_id,
                "messages": messages_data,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取消息失败: {str(e)}",
            data=None
        )


@router.post("/ask", response_model=UnifiedResponse)
async def ask_question(
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
    chatId: Optional[int] = Body(None, description="会话ID，不传则创建新会话"),
    courseId: Optional[int] = Body(None, description="课程ID，用于基于文档问答"),
    question: str = Body(..., description="用户问题"),
    currentNodeId: Optional[int] = Body(None, description="当前学习节点ID，用于理解度分析"),
):
    """
    AI问答接口
    
    需要用户登录认证
    
    功能：
    1. 如果传入courseId，AI会基于该课程的文档内容回答问题
    2. 如果传入chatId，会在该会话中继续对话
    3. 如果都不传，创建新会话进行普通对话
    4. 如果传入currentNodeId，会进行理解度分析
    """
    try:
        user_id = int(current_user["user_id"])
        username = current_user.get("username", "user")
        print(f"[聊天] 用户 {username} (ID: {user_id}) 提问: {question[:50]}...")
        
        context_content = ""
        if courseId:
            print(f"[聊天] 基于课程 {courseId} 的文档内容回答")
            context_content = await _get_course_context(session, courseId)
        
        if chatId:
            chat = session.get(ChatHistory, chatId)
            if not chat:
                return unified_response(
                    code=404,
                    message="会话不存在",
                    data=None
                )
            if chat.user_id != user_id:
                return unified_response(
                    code=403,
                    message="无权访问此会话",
                    data=None
                )
        else:
            chat = ChatHistory(
                user_id=user_id,
                content=question[:50] + "..." if len(question) > 50 else question,
            )
            session.add(chat)
            session.commit()
            session.refresh(chat)
            chatId = chat.id
            print(f"[聊天] 创建新会话: ID={chatId}")
        
        user_message = ChatMessage(
            chat_id=chatId,
            role=MessageRole.USER,
            content=question,
        )
        session.add(user_message)
        session.commit()
        
        statement = (
            select(ChatMessage)
            .where(ChatMessage.chat_id == chatId)
            .order_by(ChatMessage.created_at.asc())
        )
        history_messages = session.exec(statement).all()
        
        messages = await _build_messages(history_messages, question, context_content)
        
        print(f"[聊天] 调用LLM生成回答...")
        response = await llm_client.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
        )
        ai_answer = response.content
        print(f"[聊天] LLM回答: {ai_answer[:100]}...")
        
        assistant_message = ChatMessage(
            chat_id=chatId,
            role=MessageRole.ASSISTANT,
            content=ai_answer,
        )
        session.add(assistant_message)
        session.commit()
        session.refresh(assistant_message)

        understanding_analysis = None
        if courseId and currentNodeId:
            print(f"[聊天] 进行理解度分析...")
            try:
                analysis_result = await progress_service.handle_student_question(
                    session=session,
                    user_id=user_id,
                    course_id=courseId,
                    question=question,
                    current_node_id=currentNodeId,
                    chat_messages=history_messages,
                )
                understanding_analysis = {
                    "level": analysis_result["understanding"]["level"],
                    "score": analysis_result["understanding"]["score"],
                    "keywordsWeak": analysis_result["understanding"]["keywords_weak"],
                    "suggestions": analysis_result["understanding"]["suggestions"],
                    "paceAdjustment": analysis_result["pace_adjustment"],
                }
                print(f"[聊天] 理解度: {understanding_analysis['level']}, 分数: {understanding_analysis['score']}")
            except Exception as e:
                print(f"[聊天] 理解度分析失败: {str(e)}")
        
        return unified_response(
            code=200,
            message="回答成功",
            data={
                "chatId": chatId,
                "answer": ai_answer,
                "messageId": assistant_message.id,
                "understandingAnalysis": understanding_analysis,
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"问答失败: {str(e)}",
            data=None
        )


async def _get_course_context(session: Session, course_id: int) -> str:
    """
    获取课程的文档内容作为上下文
    """
    course = session.get(Course, course_id)
    if not course:
        return ""
    
    docling_doc = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()
    
    if not docling_doc:
        return ""
    
    context_parts = []
    
    if docling_doc.raw_json and "raw_content" in docling_doc.raw_json:
        context_parts.append(docling_doc.raw_json["raw_content"])
    else:
        texts = session.exec(
            select(DoclingText).where(DoclingText.doc_id == docling_doc.id).order_by(DoclingText.sort_order)
        ).all()
        if texts:
            context_parts.extend([t.text for t in texts if t.text])
    
    course_script = session.exec(
        select(CourseScript).where(CourseScript.course_id == course_id).where(CourseScript.is_active == True)
    ).first()
    
    if course_script and course_script.summary_text:
        context_parts.insert(0, f"【课程摘要】\n{course_script.summary_text}\n")
    
    return "\n\n".join(context_parts)


async def _build_messages(
    history_messages: List[ChatMessage],
    current_question: str,
    context_content: str = ""
) -> List[Message]:
    """
    构建发送给LLM的消息列表
    """
    messages = []
    
    if context_content:
        max_context_length = 8000
        if len(context_content) > max_context_length:
            context_content = context_content[:max_context_length] + "\n\n[内容已截断...]"
        
        system_prompt = f"""你是一个智能课程助手。请基于以下文档内容回答用户的问题。
如果问题与文档内容无关，请礼貌地告知用户你只能回答与文档相关的问题。

【文档内容】
{context_content}

请根据以上内容回答用户的问题，回答要准确、清晰、有帮助。"""
    else:
        system_prompt = """你是一个智能课程助手。请友好、专业地回答用户的问题。
如果用户询问与课程、学习相关的问题，请提供有建设性的建议。"""
    
    messages.append(Message(role="system", content=system_prompt))
    
    for msg in history_messages[-10:]:
        messages.append(Message(role=msg.role.value, content=msg.content))
    
    return messages


@router.post("/create", response_model=UnifiedResponse)
async def create_chat_record(
    userId: int = Query(..., description="用户ID"),
    content: str = Query(..., description="聊天内容"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    创建新的聊天记录
    
    需要用户登录认证
    只能为自己创建聊天记录
    """
    try:
        token_user_id = int(current_user["user_id"])
        if userId != token_user_id:
            return unified_response(
                code=403,
                message="无权为其他用户创建聊天记录",
                data=None
            )
        
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
    current_user: dict = Depends(get_current_user),
):
    """
    删除聊天记录
    
    需要用户登录认证
    只能删除自己的聊天记录
    """
    try:
        token_user_id = int(current_user["user_id"])
        if userId != token_user_id:
            return unified_response(
                code=403,
                message="无权删除其他用户的聊天记录",
                data=None
            )
        
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
        
        msg_statement = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
        messages = session.exec(msg_statement).all()
        for msg in messages:
            session.delete(msg)
        
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
