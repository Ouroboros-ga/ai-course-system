"""
文档处理API接口
流程：上传文件 -> Docling解析为Markdown -> 豆包AI生成智课脚本 -> 存储到数据库 -> 返回结果
Updated: 2026-03-28 - 集成Docling解析和豆包AI，添加用户认证
Updated: 2026-04-09 - 重构：解析逻辑迁移到document_service服务层
"""

import os
import uuid
import tempfile
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, text, func

from app.schemas.document_schema import (
    DocumentUploadResponse,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
)
from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_only
from app.models.database import get_session
from app.models.course_model import (
    Course,
    CourseScript,
    ScriptNode,
    DoclingDocument,
    DoclingGroup,
    DoclingTable,
    DoclingTableCell,
    DoclingText,
    DoclingPicture,
    StudentEnrollment,
    CourseStatus,
    ParseStatus,
    ScriptNodeType,
)
from app.models.user_model import ChatHistory
from app.services.document_service import document_service
from app.services import smart_course_service

router = APIRouter(tags=["文档处理"])

UPLOAD_DIR = Path(tempfile.gettempdir()) / "ai_course_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

document_cache = {}


@router.post("/upload", response_model=UnifiedResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="上传的文档文件 (PDF, DOCX, PPTX等)"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    上传文档并解析，存储到数据库，生成智课脚本
    
    需要用户登录认证
    
    流程：
    1. 验证用户身份
    2. 存储文件信息到 courses 表
    3. 创建 docling_documents 记录 (status = PENDING)
    4. 调用document_service处理文档（解析+RAG+脚本生成）
    5. 存储解析结果到数据库
    6. 创建聊天记录归档
    7. 返回结果
    """
    try:
        user_id = int(current_user["user_id"])
        username = current_user.get("username", "user")
        print(f"[认证] 用户 {username} (ID: {user_id}) 上传文件")

        document_id = str(uuid.uuid4())

        file_ext = Path(file.filename).suffix.lower()
        safe_filename = f"{document_id}{file_ext}"
        file_path = UPLOAD_DIR / safe_filename

        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        file_size = file_path.stat().st_size
        if file_size > 50 * 1024 * 1024:
            file_path.unlink()
            return unified_response(
                code=400,
                message="文件大小超过限制（最大50MB）",
                data=None
            )

        print(f"[步骤1] 存储文件信息到 courses 表")
        print(f"  文件已保存: {file_path}")

        course = Course(
            fanya_course_id=f"local_{document_id[:8]}",
            fanya_course_name=file.filename,
            title=Path(file.filename).stem,
            description=f"从文件 {file.filename} 导入的课程",
            teacher_id=user_id,
            status=CourseStatus.DRAFT,
            is_ai_generated=False,
            source_file_name=file.filename,
            source_file_path=str(file_path),
            source_mimetype=file.content_type or "application/octet-stream",
            total_pages=0,
        )
        session.add(course)
        session.commit()
        session.refresh(course)
        print(f"  创建课程记录: ID={course.id}, 标题={course.title}")

        print(f"[步骤2] 创建 docling_documents 记录 (status = PENDING)")
        docling_doc = DoclingDocument(
            course_id=course.id,
            schema_name="DoclingDocument",
            version="1.10.0",
            doc_name=file.filename,
            origin_filename=file.filename,
            origin_mimetype=file.content_type,
            origin_binary_hash=document_id,
            source_file_path=str(file_path),
            status=ParseStatus.PENDING,
        )
        session.add(docling_doc)
        session.commit()
        session.refresh(docling_doc)
        print(f"  创建文档解析记录: ID={docling_doc.id}, status=PENDING")

        print(f"[步骤3] 调用document_service处理文档")
        docling_doc.status = ParseStatus.PROCESSING
        session.commit()
        print(f"  更新状态: PROCESSING")

        process_result = await document_service.process_document(
            file_path=file_path,
            filename=file.filename,
            enable_rag=True,
            enable_script=True,
        )
        
        parse_result = process_result.parse_result
        structure_result = process_result.structure_result
        script_result = process_result.script_result
        rag_result = process_result.rag_result
        mind_map = process_result.mind_map

        print(f"  文档解析完成: {parse_result.parse_method}, {len(parse_result.markdown_content)} 字符")
        print(f"  RAG预处理: 公式{rag_result.formula_count}个, 表格{rag_result.table_count}个, 知识点{len(rag_result.knowledge_points)}个")
        print(f"  脚本生成: {len(script_result.nodes)} 个节点")

        print(f"[步骤4] 存储解析结果到相关表")
        total_texts = 0
        total_tables = 0
        total_pictures = 0
        total_groups = 0

        for group_data in structure_result.groups:
            group = DoclingGroup(
                doc_id=docling_doc.id,
                self_ref=group_data.get("self_ref", f"#/groups/{total_groups}"),
                name=group_data.get("name", f"Section {total_groups + 1}"),
                label=group_data.get("label", "section"),
                content_layer=group_data.get("content_layer", "body"),
                sort_order=total_groups,
            )
            session.add(group)
            session.commit()
            session.refresh(group)
            total_groups += 1
        print(f"  存储 {total_groups} 个分组记录")

        for idx, text_data in enumerate(structure_result.texts):
            text_record = DoclingText(
                doc_id=docling_doc.id,
                group_id=None,
                self_ref=text_data.get("self_ref", f"#/texts/{idx}"),
                label=text_data.get("label", "text"),
                text=text_data.get("text", ""),
                page_no=text_data.get("page_no", 1),
                sort_order=idx,
            )
            session.add(text_record)
            total_texts += 1
        session.commit()
        print(f"  存储 {total_texts} 条文本记录")

        docling_doc.status = ParseStatus.COMPLETED
        docling_doc.total_groups = total_groups
        docling_doc.total_texts = total_texts
        docling_doc.total_tables = total_tables
        docling_doc.total_pictures = total_pictures
        docling_doc.raw_json = {
            "groups": structure_result.groups,
            "texts": structure_result.texts,
            "tables": structure_result.tables,
            "pictures": structure_result.pictures,
            "raw_content": structure_result.raw_content,
        }
        docling_doc.updated_at = datetime.utcnow()
        session.commit()
        print(f"  更新状态: COMPLETED")

        print(f"[步骤5] 存储智课脚本到数据库")
        course_script = CourseScript(
            course_id=course.id,
            version=1,
            version_name="v1.0",
            script_content=script_result.script_content,
            summary_text=script_result.summary,
            keywords=json.dumps(script_result.keywords, ensure_ascii=False),
            is_active=True,
            audio_url=None,
            audio_duration=0,
            created_by=user_id,
        )
        session.add(course_script)
        session.commit()
        session.refresh(course_script)
        print(f"  创建课程脚本记录: ID={course_script.id}")

        print(f"[步骤6] 拆分脚本节点")
        for idx, node in enumerate(script_result.nodes):
            script_node = ScriptNode(
                script_id=course_script.id,
                chapter_id=node.chapter_id,
                node_index=idx,
                node_type=ScriptNodeType(node.node_type),
                title=node.title,
                content=node.content,
                page_start=node.page_start,
                page_end=node.page_end,
                duration=node.duration,
                is_key_point=node.is_key_point,
            )
            session.add(script_node)
        session.commit()
        print(f"  创建 {len(script_result.nodes)} 个 script_nodes 记录")

        course.total_nodes = len(script_result.nodes)
        course.total_duration = script_result.total_duration
        course.is_ai_generated = True
        course.updated_at = datetime.utcnow()
        session.commit()
        print(f"  更新课程统计: total_nodes={course.total_nodes}, total_duration={course.total_duration}")

        print(f"[步骤7] 创建聊天记录归档")
        chat_record = ChatHistory(
            user_id=user_id,
            content=f"{file.filename} 解析",
        )
        session.add(chat_record)
        session.commit()
        session.refresh(chat_record)
        chat_id = chat_record.id
        print(f"  创建聊天记录: ID={chat_id}")

        document_cache[document_id] = {
            "course_id": course.id,
            "script_id": course_script.id,
            "doc_id": docling_doc.id,
            "chat_id": chat_id,
            "filename": file.filename,
            "markdown_content": parse_result.markdown_content,
            "script_content": script_result.script_content,
            "file_path": str(file_path),
            "rag_knowledge_points": rag_result.knowledge_points,
        }

        print(f"[步骤8] 返回结果给前端")
        
        return unified_response(
            code=200,
            message="上传并解析成功",
            data={
                "fullContent": script_result.beautiful_markdown,
                "rawContent": parse_result.markdown_content,
                "title": course.title,
                "audioUrl": None,
                "mindMapJson": mind_map,
                "chatId": chat_id,
                "courseId": course.id,
                "ragInfo": {
                    "formulaCount": rag_result.formula_count,
                    "tableCount": rag_result.table_count,
                    "domainTermCount": rag_result.domain_term_count,
                    "treeNodeCount": rag_result.tree_node_count,
                    "knowledgePointCount": len(rag_result.knowledge_points),
                } if not rag_result.error else None,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"文档处理失败: {str(e)}",
            data={"error": str(e)}
        )


@router.post("/analyze", response_model=DocumentAnalyzeResponse)
async def analyze_document(request: DocumentAnalyzeRequest):
    """
    对已有文档进行AI分析
    """
    try:
        if request.document_id not in document_cache:
            raise HTTPException(status_code=404, detail="文档不存在或已过期")
        
        doc_data = document_cache[request.document_id]
        
        return DocumentAnalyzeResponse(
            success=True,
            message="分析完成",
            analysis=doc_data.get("script_content", {}).get("summary", "无摘要")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return DocumentAnalyzeResponse(
            success=False,
            message="分析失败",
            error=str(e)
        )


# ==================== 课程列表接口 (必须在 /{document_id} 之前) ====================

@router.get("/courses")
async def get_courses_list(
    status: Optional[str] = Query(None, description="课程状态筛选 (published/draft/archived)"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取课程列表（学生可查看已发布的课程）

    需要用户登录认证
    学生只能看到已发布的课程
    老师可以看到自己创建的所有课程 + 其他老师的已发布课程
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        statement = select(Course)

        if user_role == "student":
            statement = statement.where(Course.status == CourseStatus.PUBLISHED)
        else:
            from sqlmodel import or_
            statement = statement.where(
                or_(
                    Course.teacher_id == user_id,
                    Course.status == CourseStatus.PUBLISHED
                )
            )

        if status:
            try:
                status_enum = CourseStatus(status)
                statement = statement.where(Course.status == status_enum)
            except ValueError:
                pass

        statement = statement.order_by(Course.created_at.desc())
        courses = session.exec(statement).all()

        courses_data = []
        for course in courses:
            teacher_name = "未知教师"
            teacher_record = session.execute(
                text("SELECT username FROM users WHERE id = :uid"),
                {"uid": course.teacher_id}
            ).fetchone()
            if teacher_record:
                teacher_name = teacher_record[0]

            courses_data.append({
                "id": course.id,
                "title": course.title,
                "description": course.description,
                "status": course.status.value,
                "teacher_id": course.teacher_id,
                "teacher_name": teacher_name,
                "total_nodes": course.total_nodes,
                "total_duration": course.total_duration,
                "source_file_name": course.source_file_name,
                "is_ai_generated": course.is_ai_generated,
                "created_at": course.created_at.isoformat() if course.created_at else None,
            })

        return unified_response(
            code=200,
            message="获取课程列表成功",
            data={
                "courses": courses_data,
                "total": len(courses_data),
            }
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取课程列表失败: {str(e)}",
            data=None
        )


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    session: Session = Depends(get_session),
):
    """
    获取文档信息（从数据库读取）
    """
    if document_id not in document_cache:
        raise HTTPException(status_code=404, detail="文档不存在或已过期")

    doc_data = document_cache[document_id]
    course_id = doc_data.get("course_id")

    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    script = session.exec(
        select(CourseScript).where(CourseScript.course_id == course_id).where(CourseScript.is_active == True)
    ).first()

    nodes = []
    if script:
        nodes = session.exec(
            select(ScriptNode).where(ScriptNode.script_id == script.id).order_by(ScriptNode.node_index)
        ).all()

    return {
        "document_id": document_id,
        "course": {
            "id": course.id,
            "title": course.title,
            "status": course.status.value,
            "total_nodes": course.total_nodes,
            "total_duration": course.total_duration,
        },
        "script": {
            "id": script.id if script else None,
            "version": script.version if script else None,
            "summary": script.summary_text if script else None,
        } if script else None,
        "nodes_count": len(nodes),
        "nodes": [
            {
                "index": n.node_index,
                "type": n.node_type.value,
                "title": n.title,
                "duration": n.duration,
            }
            for n in nodes
        ],
    }


@router.post("/course/{course_id}/save")
async def save_course_nodes(
    course_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    保存老师修改后的课程节点内容到数据库

    需要老师权限
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        if user_role != "teacher":
            return unified_response(code=403, message="只有教师可以保存课程内容", data=None)

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权修改此课程", data=None)

        body = await request.json()
        nodes_data = body.get("nodes", [])

        updated_count = 0
        for node_data in nodes_data:
            node_id = node_data.get("id")
            if not node_id:
                continue

            node = session.get(ScriptNode, node_id)
            if node and node.script_id:
                script = session.get(CourseScript, node.script_id)
                if script and script.course_id == course_id:
                    if "title" in node_data:
                        node.title = node_data["title"]
                    if "content" in node_data:
                        node.content = node_data["content"]
                    if "page_start" in node_data:
                        node.page_start = node_data["page_start"]
                    if "page_end" in node_data:
                        node.page_end = node_data["page_end"]
                    if "extra_data" in node_data:
                        node.extra_data = node_data["extra_data"]
                    session.add(node)
                    updated_count += 1

        session.commit()

        return unified_response(code=200, message=f"成功保存 {updated_count} 个节点的修改", data={"updated_count": updated_count})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"保存失败: {str(e)}", data=None)


@router.get("/course/{course_id}")
async def get_course_detail(
    course_id: int,
    session: Session = Depends(get_session),
):
    """
    获取课程完整详情（包括脚本和节点）
    """
    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    
    script = session.exec(
        select(CourseScript).where(CourseScript.course_id == course_id).where(CourseScript.is_active == True)
    ).first()
    
    nodes = []
    if script:
        nodes = session.exec(
            select(ScriptNode).where(ScriptNode.script_id == script.id).order_by(ScriptNode.node_index)
        ).all()
    
    docling_doc = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()
    
    return unified_response(
        code=200,
        message="获取课程详情成功",
        data={
            "course": {
                "id": course.id,
                "title": course.title,
                "description": course.description,
                "status": course.status.value,
                "source_file_name": course.source_file_name,
                "total_pages": course.total_pages,
                "total_nodes": course.total_nodes,
                "total_duration": course.total_duration,
                "created_at": course.created_at.isoformat() if course.created_at else None,
            },
            "script": {
                "id": script.id,
                "version": script.version,
                "version_name": script.version_name,
                "summary_text": script.summary_text,
                "keywords": script.keywords,
                "script_content": script.script_content,
                "audio_url": script.audio_url,
                "audio_duration": script.audio_duration,
            } if script else None,
            "nodes": [
                {
                    "id": n.id,
                    "node_index": n.node_index,
                    "node_type": n.node_type.value,
                    "title": n.title,
                    "content": n.content,
                    "page_start": n.page_start,
                    "page_end": n.page_end,
                    "duration": n.duration,
                    "is_key_point": n.is_key_point,
                    "extra_data": n.extra_data,
                }
                for n in nodes
            ],
            "parse_info": {
                "status": docling_doc.status.value if docling_doc else None,
                "total_texts": docling_doc.total_texts if docling_doc else 0,
                "total_tables": docling_doc.total_tables if docling_doc else 0,
                "total_pictures": docling_doc.total_pictures if docling_doc else 0,
            } if docling_doc else None,
        }
    )


@router.get("/courses")
async def get_courses_list(
    status: Optional[str] = Query(None, description="课程状态筛选 (published/draft/archived)"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取课程列表（学生可查看已发布的课程）
    
    需要用户登录认证
    学生只能看到已发布的课程
    老师可以看到自己创建的所有课程 + 其他老师的已发布课程
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")
        
        statement = select(Course)
        
        if user_role == "student":
            # 学生只能看到已发布的课程
            statement = statement.where(Course.status == CourseStatus.PUBLISHED)
        else:
            # 老师可以看到自己所有课程 + 已发布的其他课程
            from sqlmodel import or_
            statement = statement.where(
                or_(
                    Course.teacher_id == user_id,
                    Course.status == CourseStatus.PUBLISHED
                )
            )
        
        if status:
            try:
                status_enum = CourseStatus(status)
                statement = statement.where(Course.status == status_enum)
            except ValueError:
                pass
        
        statement = statement.order_by(Course.created_at.desc())
        courses = session.exec(statement).all()
        
        courses_data = []
        for course in courses:
            teacher_name = "未知教师"
            teacher_record = session.execute(
                text("SELECT username FROM users WHERE id = :uid"),
                {"uid": course.teacher_id}
            ).fetchone()
            if teacher_record:
                teacher_name = teacher_record[0]
            
            courses_data.append({
                "id": course.id,
                "title": course.title,
                "description": course.description,
                "status": course.status.value,
                "teacher_id": course.teacher_id,
                "teacher_name": teacher_name,
                "total_nodes": course.total_nodes,
                "total_duration": course.total_duration,
                "source_file_name": course.source_file_name,
                "is_ai_generated": course.is_ai_generated,
                "created_at": course.created_at.isoformat() if course.created_at else None,
            })
        
        return unified_response(
            code=200,
            message="获取课程列表成功",
            data={
                "courses": courses_data,
                "total": len(courses_data),
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"获取课程列表失败: {str(e)}",
            data=None
        )


@router.post("/course/{course_id}/save")
async def save_course_nodes(
    course_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    保存老师修改后的课程节点内容到数据库
    
    需要老师权限
    
    请求体格式:
    {
        "nodes": [
            {
                "id": 1,
                "title": "章节标题",
                "content": "修改后的内容"
            }
        ]
    }
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")
        
        if user_role != "teacher":
            return unified_response(
                code=403,
                message="只有教师可以保存课程内容",
                data=None
            )
        
        course = session.get(Course, course_id)
        if not course:
            return unified_response(
                code=404,
                detail="课程不存在"
            )
        
        if course.teacher_id != user_id:
            return unified_response(
                code=403,
                message="无权修改此课程",
                data=None
            )
        
        body = await request.json()
        nodes_data = body.get("nodes", [])
        
        updated_count = 0
        for node_data in nodes_data:
            node_id = node_data.get("id")
            if not node_id:
                continue
            
            node = session.get(ScriptNode, node_id)
            if node and node.script_id:
                script = session.get(CourseScript, node.script_id)
                if script and script.course_id == course_id:
                    if "title" in node_data:
                        node.title = node_data["title"]
                    if "content" in node_data:
                        node.content = node_data["content"]
                    session.add(node)
                    updated_count += 1
        
        session.commit()
        
        return unified_response(
            code=200,
            message=f"成功保存 {updated_count} 个节点的修改",
            data={"updated_count": updated_count}
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(
            code=500,
            message=f"保存失败: {str(e)}",
            data=None
        )


# ==================== TTS语音合成接口 ====================

from app.common.tts_client import tts_client
from fastapi.responses import Response


@router.post("/tts/synthesize")
async def synthesize_speech(
    text: str = File(..., description="要合成的文本"),
    voice: Optional[str] = File(None, description="音色"),
    sample_rate: Optional[int] = File(16000, description="采样率"),
    output_format: Optional[str] = File("mp3", description="输出格式"),
):
    """
    语音合成接口（支持长文本，自动分段合成）
    
    将文本转换为语音，返回音频文件。
    长文本（>2000字）会自动分段合成后拼接。
    
    参数:
    - text: 要合成的文本（支持长文本）
    - voice: 音色（可选，默认使用配置中的音色）
    - sample_rate: 采样率（可选，默认16000）
    - output_format: 输出格式（可选，默认mp3）
    
    返回:
    - 音频文件（二进制数据）
    """
    try:
        text_length = len(text)
        print(f"[TTS] 开始合成语音: 文本长度={text_length}字, 前50字: {text[:50]}...")
        
        # 长文本分段处理（每段不超过2000字，按句号分割）
        MAX_SEGMENT_LENGTH = 2000
        if text_length <= MAX_SEGMENT_LENGTH:
            response = await tts_client.synthesize(
                text=text,
                voice=voice,
                sample_rate=sample_rate,
                output_format=output_format
            )
            audio_data = response.audio_data
            total_latency = response.latency_ms
        else:
            # 按句号分段
            segments = []
            current_segment = ""
            for sentence in text.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").replace("；", "；\n").split("\n"):
                if len(current_segment) + len(sentence) > MAX_SEGMENT_LENGTH and current_segment:
                    segments.append(current_segment.strip())
                    current_segment = sentence
                else:
                    current_segment += sentence
            if current_segment.strip():
                segments.append(current_segment.strip())
            
            print(f"[TTS] 长文本分段: {len(segments)}段")
            
            # 逐段合成
            audio_parts = []
            total_latency = 0
            for i, seg in enumerate(segments):
                seg_response = await tts_client.synthesize(
                    text=seg,
                    voice=voice,
                    sample_rate=sample_rate,
                    output_format=output_format
                )
                audio_parts.append(seg_response.audio_data)
                total_latency += seg_response.latency_ms
                print(f"[TTS] 段{i+1}/{len(segments)}完成, {len(seg_response.audio_data)}字节")
            
            audio_data = b"".join(audio_parts)
        
        print(f"[TTS] 合成成功，音频大小: {len(audio_data)} 字节")
        
        content_type_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "pcm": "audio/pcm",
        }
        
        content_type = content_type_map.get(output_format.lower(), "audio/mpeg")
        
        return Response(
            content=audio_data,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{output_format}",
                "X-Latency-Ms": str(total_latency),
            }
        )
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[TTS] 错误详情:\n{error_detail}")
        raise HTTPException(status_code=500, detail=f"语音合成失败: {str(e)}")


# ==================== 脚本版本管理接口 ====================

import copy


@router.post("/course/{course_id}/script/snapshot")
async def create_script_snapshot(
    course_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    创建脚本版本快照
    
    将当前激活脚本的所有节点保存为新版本。
    请求体: { "version_name": "可选版本名称" }
    """
    try:
        user_id = int(current_user["user_id"])
        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)
        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权操作此课程", data=None)

        # 获取当前激活脚本
        active_script = session.exec(
            select(CourseScript).where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
        ).first()
        if not active_script:
            return unified_response(code=404, message="未找到激活脚本", data=None)

        # 获取当前所有节点
        current_nodes = session.exec(
            select(ScriptNode).where(ScriptNode.script_id == active_script.id).order_by(ScriptNode.node_index)
        ).all()

        body = await request.json() if request else {}
        version_name = body.get("version_name", f"v{active_script.version + 1} 快照")

        # 创建新脚本版本（深拷贝script_content）
        new_script = CourseScript(
            course_id=course_id,
            version=active_script.version + 1,
            version_name=version_name,
            script_content=copy.deepcopy(active_script.script_content),
            summary_text=active_script.summary_text,
            keywords=active_script.keywords,
            is_active=True,
            created_by=user_id,
        )
        # 旧版本设为非激活
        active_script.is_active = False
        session.add(active_script)
        session.add(new_script)
        session.flush()  # 获取new_script.id

        # 拷贝所有节点到新脚本
        for node in current_nodes:
            new_node = ScriptNode(
                script_id=new_script.id,
                chapter_id=node.chapter_id,
                node_index=node.node_index,
                node_type=node.node_type,
                title=node.title,
                content=node.content,
                page_start=node.page_start,
                page_end=node.page_end,
                timestamp_start=node.timestamp_start,
                timestamp_end=node.timestamp_end,
                duration=node.duration,
                is_key_point=node.is_key_point,
                extra_data=copy.deepcopy(node.extra_data) if node.extra_data else None,
            )
            session.add(new_node)

        session.commit()
        session.refresh(new_script)

        return unified_response(
            code=200,
            message=f"已创建版本快照: {version_name}",
            data={
                "version": new_script.version,
                "version_name": new_script.version_name,
                "script_id": new_script.id,
                "node_count": len(current_nodes),
            },
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"创建快照失败: {str(e)}", data=None)


@router.get("/course/{course_id}/script/versions")
async def get_script_versions(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取脚本版本列表
    """
    try:
        scripts = session.exec(
            select(CourseScript)
            .where(CourseScript.course_id == course_id)
            .order_by(CourseScript.version.desc())
        ).all()

        versions = []
        for s in scripts:
            node_count = len(session.exec(
                select(ScriptNode).where(ScriptNode.script_id == s.id)
            ).all())
            versions.append({
                "id": s.id,
                "version": s.version,
                "version_name": s.version_name,
                "is_active": s.is_active,
                "node_count": node_count,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            })

        return unified_response(code=200, message="获取版本列表成功", data=versions)

    except Exception as e:
        return unified_response(code=500, message=f"获取版本列表失败: {str(e)}", data=None)


@router.post("/course/{course_id}/script/rollback/{script_id}")
async def rollback_script_version(
    course_id: int,
    script_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    回滚到指定脚本版本
    
    将指定版本设为激活，当前激活版本设为非激活。
    """
    try:
        user_id = int(current_user["user_id"])
        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, message="课程不存在", data=None)
        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权操作此课程", data=None)

        target_script = session.get(CourseScript, script_id)
        if not target_script or target_script.course_id != course_id:
            return unified_response(code=404, message="目标版本不存在", data=None)

        # 取消当前激活版本
        current_active = session.exec(
            select(CourseScript).where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
        ).first()
        if current_active:
            current_active.is_active = False
            session.add(current_active)

        # 激活目标版本
        target_script.is_active = True
        session.add(target_script)
        session.commit()

        return unified_response(
            code=200,
            message=f"已回滚到版本 v{target_script.version}",
            data={"version": target_script.version, "version_name": target_script.version_name},
        )

    except Exception as e:
        return unified_response(code=500, message=f"回滚失败: {str(e)}", data=None)


# ==================== 课程发布与选课管理接口 ====================

@router.post("/course/{course_id}/publish")
async def publish_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    发布课程（老师操作）
    
    将课程状态从 draft 改为 published，学生可以看到并选择该课程
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        if user_role != "teacher":
            return unified_response(code=403, message="只有教师可以发布课程", data=None)

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权操作此课程", data=None)

        if course.status == CourseStatus.PUBLISHED:
            return unified_response(code=200, message="课程已是发布状态", data={"status": "published"})

        # 更新状态为已发布
        course.status = CourseStatus.PUBLISHED
        course.updated_at = datetime.utcnow()
        session.add(course)
        session.commit()

        return unified_response(code=200, message="课程发布成功", data={"status": "published"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"发布失败: {str(e)}", data=None)


@router.post("/course/{course_id}/unpublish")
async def unpublish_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    取消发布课程（老师操作）
    
    将课程状态从 published 改为 draft，学生无法再看到该课程
    已选课的学生保留选课记录但标记为不活跃
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        if user_role != "teacher":
            return unified_response(code=403, message="只有教师可以取消发布课程", data=None)

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权操作此课程", data=None)

        # 更新状态为草稿
        course.status = CourseStatus.DRAFT
        course.updated_at = datetime.utcnow()
        session.add(course)
        session.commit()

        return unified_response(code=200, message="课程已取消发布", data={"status": "draft"})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"取消发布失败: {str(e)}", data=None)


@router.delete("/course/{course_id}")
async def delete_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    删除课程（老师操作）

    完全删除课程及其所有关联数据（脚本、选课记录、学习进度等）
    此操作不可恢复，需要二次确认
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        if user_role != "teacher":
            return unified_response(code=403, message="只有教师可以删除课程", data=None)

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权删除此课程", data=None)

        # 检查是否有学生已选课
        enrollments_count = session.exec(
            select(func.count()).select_from(StudentEnrollment).where(
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True
            )
        ).one() or 0

        # 删除所有相关数据（按依赖顺序）
        try:
            from app.models.progress_model import LearningProgress, NodeProgress
            from app.models.course_model import CourseScript, ScriptNode

            # 1. 删除该课程的所有学习进度和节点进度
            learning_progresses = session.exec(
                select(LearningProgress).where(LearningProgress.course_id == course_id)
            ).all()

            for lp in learning_progresses:
                node_progresses = session.exec(
                    select(NodeProgress).where(NodeProgress.learning_progress_id == lp.id)
                ).all()
                for np in node_progresses:
                    session.delete(np)
                session.delete(lp)

            # 2. 删除该课程的选课记录
            all_enrollments = session.exec(
                select(StudentEnrollment).where(StudentEnrollment.course_id == course_id)
            ).all()
            for enrollment in all_enrollments:
                session.delete(enrollment)

            # 3. 删除课程脚本节点
            scripts = session.exec(
                select(CourseScript).where(CourseScript.course_id == course_id)
            ).all()
            for script in scripts:
                nodes = session.exec(
                    select(ScriptNode).where(ScriptNode.script_id == script.id)
                ).all()
                for node in nodes:
                    session.delete(node)
                session.delete(script)

            # 4. 最后删除课程本身
            session.delete(course)
            session.commit()

            print(f"[删除课程] 教师 {current_user.get('username')} 删除了课程 {course.title} (ID:{course_id})，影响 {enrollments_count} 名学生")

            return unified_response(code=200, message=f"课程《{course.title}》已成功删除", data={
                "deleted_course_id": course_id,
                "affected_students": enrollments_count,
            })

        except Exception as e:
            session.rollback()
            raise e

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"删除失败: {str(e)}", data=None)


@router.post("/course/{course_id}/enroll")
async def enroll_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    学生选择/加入课程

    学生可以加入老师发布的课程
    选课成功后会自动初始化学习进度记录
    """
    try:
        student_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        if user_role != "student":
            return unified_response(code=403, message="只有学生可以选择课程", data=None)

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        if course.status != CourseStatus.PUBLISHED:
            return unified_response(code=400, message="该课程尚未发布，无法选择", data=None)

        # 检查是否已经选过
        existing = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == student_id,
                StudentEnrollment.course_id == course_id
            )
        ).first()

        if existing and existing.is_active:
            # 已选课，检查是否需要初始化进度数据
            _ensure_learning_progress(session, student_id, course_id, course.total_nodes or 0)
            return unified_response(code=200, message="您已选择过此课程", data={
                "enrollment_id": existing.id,
                "already_enrolled": True
            })

        # 如果有历史记录但不活跃，重新激活
        if existing and not existing.is_active:
            existing.is_active = True
            existing.enrolled_at = datetime.utcnow()
            session.add(existing)
            session.commit()
            # 初始化学习进度
            _ensure_learning_progress(session, student_id, course_id, course.total_nodes or 0)
            return unified_response(code=200, message="重新加入课程成功", data={
                "enrollment_id": existing.id,
                "reactivated": True
            })

        # 创建新的选课记录
        enrollment = StudentEnrollment(
            student_id=student_id,
            course_id=course_id,
            total_nodes_count=course.total_nodes or 0,
        )
        session.add(enrollment)
        session.commit()
        session.refresh(enrollment)

        # 初始化学习进度记录（关键：确保学生学习数据能正确保存）
        _init_learning_progress_for_student(session, student_id, course_id, course.total_nodes or 0)

        print(f"[选课] 学生 {current_user.get('username')} 成功加入课程 {course.title} (ID:{course_id})")

        return unified_response(code=200, message="选课成功！您现在可以开始学习了。", data={
            "enrollment_id": enrollment.id,
            "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrollment_at else None,
            "total_nodes": course.total_nodes or 0,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"选课失败: {str(e)}", data=None)


def _init_learning_progress_for_student(session: Session, student_id: int, course_id: int, total_nodes: int):
    """
    为新选课的学生初始化学习进度记录

    创建LearningProgress和NodeProgress记录，确保后续学习数据能正确保存到数据库
    """
    try:
        from app.models.progress_model import LearningProgress, NodeProgress

        # 检查是否已有进度记录
        existing_progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.student_id == student_id,
                LearningProgress.course_id == course_id
            )
        ).first()

        if existing_progress:
            print(f"[进度初始化] 学生{student_id} 课程{course_id} 进度记录已存在")
            return

        # 创建总的学习进度记录
        learning_progress = LearningProgress(
            student_id=student_id,
            course_id=course_id,
            current_node_index=0,
            overall_progress=0.0,
            total_study_time=0,
            last_access_time=datetime.utcnow(),
        )
        session.add(learning_progress)
        session.commit()
        session.refresh(learning_progress)

        print(f"[进度初始化] 创建LearningProgress ID={learning_progress.id}")

        # 如果有节点信息，为每个节点创建初始进度记录
        if total_nodes > 0:
            from sqlmodel import select as sql_select
            script = session.exec(
                sql_select(CourseScript).where(CourseScript.course_id == course_id).where(CourseScript.is_active == True)
            ).first()

            if script:
                nodes = session.exec(
                    sql_select(ScriptNode).where(ScriptNode.script_id == script.id).order_by(ScriptNode.node_index)
                ).all()

                for node in nodes:
                    node_progress = NodeProgress(
                        learning_progress_id=learning_progress.id,
                        node_id=node.id,
                        node_index=node.node_index,
                        is_completed=False,
                        completion_rate=0.0,
                        understanding_score=0.0,
                        study_time=0,
                        question_count=0,
                    )
                    session.add(node_progress)

                session.commit()
                print(f"[进度初始化] 为 {len(nodes)} 个节点创建初始进度记录")

    except Exception as e:
        print(f"[进度初始化] 失败: {e}")
        import traceback
        traceback.print_exc()


def _ensure_learning_progress(session: Session, student_id: int, course_id: int, total_nodes: int):
    """确保学生的学习进度记录存在"""
    try:
        from app.models.progress_model import LearningProgress

        existing = session.exec(
            select(LearningProgress).where(
                LearningProgress.student_id == student_id,
                LearningProgress.course_id == course_id
            )
        ).first()

        if not existing:
            _init_learning_progress_for_student(session, student_id, course_id, total_nodes)

    except Exception as e:
        print(f"[确保进度] 检查失败: {e}")


@router.post("/course/{course_id}/unenroll")
async def unenroll_course(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    学生退出课程
    """
    try:
        student_id = int(current_user["user_id"])

        enrollment = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == student_id,
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True
            )
        ).first()

        if not enrollment:
            return unified_response(code=400, message="未找到选课记录", data=None)

        enrollment.is_active = False
        session.add(enrollment)
        session.commit()

        return unified_response(code=200, message="已退出课程", data=None)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"退出课程失败: {str(e)}", data=None)


@router.get("/course/{course_id}/students")
async def get_course_students(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取课程的学生列表及学习进度（老师查看）
    
    返回所有选择了该课程的活跃学生及其学习进度统计
    """
    try:
        user_id = int(current_user["user_id"])
        user_role = current_user.get("role", "student")

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        # 权限检查：只有课程老师或管理员可以查看
        if course.teacher_id != user_id and user_role != "admin":
            return unified_response(code=403, message="无权查看此课程的学生数据", data=None)

        # 查询所有活跃的选课记录
        enrollments = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True
            ).order_by(StudentEnrollment.enrolled_at.desc())
        ).all()

        students_data = []
        for enr in enrollments:
            # 获取学生用户名
            from sqlmodel import text
            user_result = session.execute(
                text("SELECT username FROM users WHERE id = :uid"),
                {"uid": enr.student_id}
            ).fetchone()
            username = user_result[0] if user_result else f"学生{enr.student_id}"

            students_data.append({
                "enrollment_id": enr.id,
                "student_id": enr.student_id,
                "username": username,
                "enrolled_at": enr.enrolled_at.isoformat() if enr.enrolled_at else None,
                "overall_progress": round(enr.overall_progress, 1),
                "avg_understanding_score": round(enr.avg_understanding_score * 100, 1) if enr.avg_understanding_score else 0,
                "understanding_level": enr.avg_understanding_level,
                "total_study_minutes": enr.total_study_minutes,
                "last_study_time": enr.last_study_time.isoformat() if enr.last_study_time else None,
                "nodes_completed": enr.total_nodes_completed,
                "nodes_total": enr.total_nodes_count,
            })

        return unified_response(code=200, message="获取成功", data={
            "course_id": course_id,
            "course_title": course.title,
            "total_students": len(students_data),
            "students": students_data
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"获取学生列表失败: {str(e)}", data=None)


@router.get("/course/{course_id}/stats")
async def get_course_stats(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    获取课程统计数据（老师查看）
    
    返回：总选课人数、平均进度、平均理解度等统计信息
    """
    try:
        user_id = int(current_user["user_id"])

        course = session.get(Course, course_id)
        if not course:
            return unified_response(code=404, detail="课程不存在")

        if course.teacher_id != user_id:
            return unified_response(code=403, message="无权查看此课程数据", data=None)

        # 统计活跃选课数
        active_count = session.exec(
            select(func.count()).select_from(StudentEnrollment).where(
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True
            )
        ).one()

        # 计算平均进度和理解度
        all_enrollments = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True
            )
        ).all()

        total_students = len(all_enrollments)
        avg_progress = 0.0
        avg_understanding = 0.0
        total_study_time = 0

        if total_students > 0:
            avg_progress = sum(e.overall_progress for e in all_enrollments) / total_students
            avg_understanding = sum(e.avg_understanding_score for e in all_enrollments) / total_students
            total_study_time = sum(e.total_study_minutes for e in all_enrollments)

        # 进度分布
        progress_distribution = {
            "not_started": sum(1 for e in all_enrollments if e.overall_progress == 0),
            "beginner": sum(1 for e in all_enrollments if 0 < e.overall_progress < 30),
            "intermediate": sum(1 for e in all_enrollments if 30 <= e.overall_progress < 70),
            "advanced": sum(1 for e in all_enrollments if 70 <= e.overall_progress < 100),
            "completed": sum(1 for e in all_enrollments if e.overall_progress >= 100),
        }

        return unified_response(code=200, message="获取成功", data={
            "course_id": course_id,
            "course_title": course.title,
            "status": course.status.value,
            "total_students": total_students,
            "total_nodes": course.total_nodes or 0,
            "avg_progress": round(avg_progress, 1),
            "avg_understanding": round(avg_understanding * 100, 1) if avg_understanding else 0,
            "total_study_hours": round(total_study_time / 60, 1),
            "progress_distribution": progress_distribution,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"获取统计失败: {str(e)}", data=None)
