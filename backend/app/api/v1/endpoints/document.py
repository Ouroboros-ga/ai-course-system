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

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.schemas.document_schema import (
    DocumentUploadResponse,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
)
from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user
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
    语音合成接口
    
    将文本转换为语音，返回音频文件
    
    参数:
    - text: 要合成的文本
    - voice: 音色（可选，默认使用配置中的音色）
    - sample_rate: 采样率（可选，默认16000）
    - output_format: 输出格式（可选，默认mp3）
    
    返回:
    - 音频文件（二进制数据）
    """
    try:
        print(f"[TTS] 开始合成语音: {text[:50]}...")
        
        response = await tts_client.synthesize(
            text=text,
            voice=voice,
            sample_rate=sample_rate,
            output_format=output_format
        )
        
        print(f"[TTS] 合成成功，音频大小: {len(response.audio_data)} 字节")
        
        content_type_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "pcm": "audio/pcm",
        }
        
        content_type = content_type_map.get(output_format.lower(), "audio/mpeg")
        
        return Response(
            content=response.audio_data,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{output_format}",
                "X-Latency-Ms": str(response.latency_ms),
            }
        )
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[TTS] 错误详情:\n{error_detail}")
        raise HTTPException(status_code=500, detail=f"语音合成失败: {str(e)}")
