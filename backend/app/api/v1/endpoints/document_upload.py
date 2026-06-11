"""
文档上传与解析 API
处理文件上传、文档解析、AI 分析
"""

import uuid
import json
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from sqlmodel import Session

from app.schemas.document_schema import (
    DocumentUploadResponse,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
)
from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, _get_user_identity
from app.models.database import get_session
from app.models.course_model import (
    Course, CourseScript, ScriptNode, DoclingDocument,
    DoclingGroup, DoclingText, DoclingTable, DoclingPicture,
    CourseStatus, ParseStatus, ScriptNodeType,
)
from app.models.user_model import ChatHistory
from app.services.document_service import document_service
from .document_utils import UPLOAD_DIR, document_cache, _background_synthesize_audio

router = APIRouter(prefix="/document", tags=["文档上传"])


@router.post("/upload", response_model=UnifiedResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="上传的文档文件 (PDF, DOCX, PPTX等)"),
    session: Session = Depends(get_session),
    user_id: int = Depends(_get_user_id),
    username: str = lambda: "user",
):
    """
    上传文档并解析，存储到数据库，生成智课脚本
    
    流程：验证身份 -> 存储文件 -> 创建课程记录 -> 解析文档 -> 生成脚本 -> 存储结果
    """
    try:
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
            return unified_response(code=400, message="文件大小超过限制（最大50MB）", data=None)

        # 创建课程记录
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

        # PDF 转换
        try:
            from app.common.slide_converter import is_office_file, is_pdf_file, get_or_create_pdf
            if is_office_file(str(file_path)):
                pdf_path = get_or_create_pdf(str(file_path))
                if pdf_path:
                    course.pdf_file_path = pdf_path
                    session.add(course)
                    session.commit()
            elif is_pdf_file(str(file_path)):
                course.pdf_file_path = str(file_path)
                session.add(course)
                session.commit()
        except Exception:
            pass

        # 创建 docling 记录
        docling_doc = DoclingDocument(
            course_id=course.id,
            schema_name="DoclingDocument", version="1.10.0",
            doc_name=file.filename, origin_filename=file.filename,
            origin_mimetype=file.content_type, origin_binary_hash=document_id,
            source_file_path=str(file_path), status=ParseStatus.PENDING,
        )
        session.add(docling_doc)
        session.commit()
        session.refresh(docling_doc)

        # 调用服务层解析
        docling_doc.status = ParseStatus.PROCESSING
        session.commit()

        process_result = await document_service.process_document(
            file_path=file_path, filename=file.filename,
            enable_rag=True, enable_script=True,
        )

        parse_result = process_result.parse_result
        structure_result = process_result.structure_result
        script_result = process_result.script_result
        rag_result = process_result.rag_result
        mind_map = process_result.mind_map

        # 存储结构化数据
        total_groups = 0
        for group_data in structure_result.groups:
            group = DoclingGroup(doc_id=docling_doc.id, **group_data)
            session.add(group)
            session.commit()
            total_groups += 1

        for idx, text_data in enumerate(structure_result.texts):
            text_record = DoclingText(doc_id=docling_doc.id, **text_data)
            session.add(text_record)
        session.commit()

        # 更新 docling 状态
        docling_doc.status = ParseStatus.COMPLETED
        docling_doc.total_groups = total_groups
        docling_doc.raw_json = {
            "groups": structure_result.groups,
            "texts": structure_result.texts,
            "tables": structure_result.tables,
            "pictures": structure_result.pictures,
        }
        docling_doc.updated_at = datetime.utcnow()
        session.commit()

        # 存储脚本
        course_script = CourseScript(
            course_id=course.id, version=1, version_name="v1.0",
            script_content=script_result.script_content,
            summary_text=script_result.summary,
            keywords=json.dumps(script_result.keywords, ensure_ascii=False),
            is_active=True, created_by=user_id,
        )
        session.add(course_script)
        session.commit()
        session.refresh(course_script)

        # 存储节点
        for idx, node in enumerate(script_result.nodes):
            script_node = ScriptNode(
                script_id=course_script.id, node_index=idx,
                chapter_id=node.chapter_id,
                node_type=ScriptNodeType(node.node_type),
                title=node.title, content=node.content,
                page_start=node.page_start, page_end=node.page_end,
                duration=node.duration, is_key_point=node.is_key_point,
                timestamp_start=node.timestamp_start, timestamp_end=node.timestamp_end,
            )
            session.add(script_node)
        session.commit()

        # 更新课程状态
        course.total_nodes = len(script_result.nodes)
        course.total_duration = script_result.total_duration
        course.is_ai_generated = True
        course.status = CourseStatus.PUBLISHED
        course.updated_at = datetime.utcnow()
        session.commit()

        # 启动后台 TTS
        import asyncio
        asyncio.create_task(_background_synthesize_audio(course.id, course_script.id))

        # 创建聊天记录
        chat_record = ChatHistory(user_id=user_id, content=f"{file.filename} 解析")
        session.add(chat_record)
        session.commit()
        session.refresh(chat_record)

        # 缓存结果
        document_cache[document_id] = {
            "course_id": course.id, "script_id": course_script.id,
            "doc_id": docling_doc.id, "chat_id": chat_record.id,
            "filename": file.filename,
            "markdown_content": parse_result.markdown_content,
            "script_content": script_result.script_content,
            "file_path": str(file_path),
            "rag_knowledge_points": rag_result.knowledge_points,
        }

        return unified_response(
            code=200, message="上传并解析成功，TTS语音正在后台生成",
            data={
                "fullContent": script_result.beautiful_markdown,
                "rawContent": parse_result.markdown_content,
                "title": course.title, "audioUrl": None,
                "mindMapJson": mind_map, "chatId": chat_record.id,
                "courseId": course.id, "ttsStatus": "processing",
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
        return unified_response(code=500, message=f"文档处理失败: {str(e)}", data={"error": str(e)})


@router.post("/analyze", response_model=DocumentAnalyzeResponse)
async def analyze_document(request: DocumentAnalyzeRequest):
    """对已有文档进行 AI 分析"""
    try:
        if request.document_id not in document_cache:
            raise HTTPException(status_code=404, detail="文档不存在或已过期")

        doc_data = document_cache[request.document_id]
        return DocumentAnalyzeResponse(
            success=True, message="分析完成",
            analysis=doc_data.get("script_content", {}).get("summary", "无摘要")
        )
    except HTTPException:
        raise
    except Exception as e:
        return DocumentAnalyzeResponse(success=False, message="分析失败", analysis=None)
