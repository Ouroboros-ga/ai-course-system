"""
F3 · AI生成PPT课件 API
老师输入大纲/主题/知识点 → LLM扩展为结构化教学脚本 → 讯飞PPT API生成.pptx → 自动进入解析管线
"""

import os
import uuid
import json
import logging
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_only
from app.models.database import get_session
from app.models.course_model import (
    Course,
    CourseScript,
    ScriptNode,
    DoclingDocument,
    CourseStatus,
    ParseStatus,
    ScriptNodeType,
)
from app.services.ppt_generation_service import ppt_generation_service
from app.services.document_service import document_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI生成PPT"])


# ---------- 请求模型 ----------

class GeneratePPTRequest(BaseModel):
    """AI生成PPT请求"""
    topic: str = Field(..., description="课程主题", min_length=1, max_length=500)
    outline: Optional[str] = Field(default=None, description="课程大纲")
    knowledge_points: Optional[List[str]] = Field(default=None, description="知识点列表")
    template_id: Optional[str] = Field(default=None, description="PPT模板ID（不填则使用默认模板）")
    author: str = Field(default="AI智课", description="PPT作者名")
    search: bool = Field(default=False, description="是否联网搜索补充内容")
    auto_parse: bool = Field(default=True, description="生成后是否自动进入解析管线")


class GetThemesRequest(BaseModel):
    """获取模板列表请求"""
    pay_type: str = Field(default="free", description="模板类型: free/not_free")
    style: Optional[str] = Field(default=None, description="模板风格（如：简约、商务、科技）")
    industry: Optional[str] = Field(default=None, description="模板行业（如：教育培训、金融）")
    page_num: int = Field(default=1, description="页码")
    page_size: int = Field(default=20, description="每页数量")


# ---------- API接口 ----------

@router.get("/themes")
async def get_ppt_themes(
    pay_type: str = "free",
    style: Optional[str] = None,
    industry: Optional[str] = None,
    page_num: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """获取可用的PPT模板列表"""
    try:
        result = await ppt_generation_service.get_themes(
            pay_type=pay_type,
            style=style,
            industry=industry,
            page_num=page_num,
            page_size=page_size,
        )
        return unified_response(code=200, message="获取模板列表成功", data=result.get("data"))
    except Exception as e:
        logger.error(f"[PPT API] 获取模板列表失败: {e}")
        return unified_response(code=500, message=f"获取模板列表失败: {str(e)}", data=None)


@router.get("/task/{sid}")
async def get_ppt_task_status(
    sid: str,
    current_user: dict = Depends(get_current_user),
):
    """查询PPT生成任务进度"""
    try:
        result = await ppt_generation_service.get_task_status(sid)
        return unified_response(code=200, message="查询成功", data=result.get("data"))
    except Exception as e:
        logger.error(f"[PPT API] 查询任务进度失败: {e}")
        return unified_response(code=500, message=f"查询任务进度失败: {str(e)}", data=None)


@router.post("/generate")
async def generate_ppt(
    request: GeneratePPTRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    AI生成PPT课件（异步）
    
    流程：
    1. LLM扩展为结构化教学脚本
    2. 调用讯飞PPT API生成.pptx
    3. 下载PPT文件
    4. 自动进入解析管线（可选）
    
    返回任务ID，前端可轮询进度
    """
    user_id = int(current_user["user_id"])

    try:
        # 创建课程记录（状态为生成中）
        document_id = str(uuid.uuid4())
        course = Course(
            fanya_course_id=f"ai_ppt_{document_id[:8]}",
            fanya_course_name=f"AI生成: {request.topic}",
            title=request.topic,
            description=f"AI生成的PPT课件 - {request.topic}",
            teacher_id=user_id,
            status=CourseStatus.DRAFT,
            is_ai_generated=True,
            source_file_name=f"{request.topic}.pptx",
            total_pages=0,
        )
        session.add(course)
        session.commit()
        session.refresh(course)

        # 创建Docling文档记录
        docling_doc = DoclingDocument(
            course_id=course.id,
            schema_name="DoclingDocument",
            version="1.10.0",
            doc_name=f"{request.topic}.pptx",
            origin_filename=f"{request.topic}.pptx",
            origin_mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            origin_binary_hash=document_id,
            status=ParseStatus.PENDING,
        )
        session.add(docling_doc)
        session.commit()
        session.refresh(docling_doc)

        # 后台执行PPT生成
        background_tasks.add_task(
            _generate_ppt_background,
            course_id=course.id,
            doc_id=docling_doc.id,
            user_id=user_id,
            topic=request.topic,
            outline=request.outline,
            knowledge_points=request.knowledge_points,
            template_id=request.template_id,
            author=request.author,
            search=request.search,
            auto_parse=request.auto_parse,
        )

        return unified_response(
            code=200,
            message="PPT生成任务已创建，正在后台处理",
            data={
                "course_id": course.id,
                "doc_id": docling_doc.id,
                "status": "generating",
            },
        )

    except Exception as e:
        logger.error(f"[PPT API] 创建PPT生成任务失败: {e}")
        return unified_response(code=500, message=f"创建任务失败: {str(e)}", data=None)


@router.post("/generate-sync")
async def generate_ppt_sync(
    request: GeneratePPTRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(teacher_only),
):
    """
    AI生成PPT课件（同步，等待完成）
    
    适用于前端需要等待结果的场景
    可能耗时较长（1-5分钟）
    """
    user_id = int(current_user["user_id"])

    try:
        # 步骤1: 生成PPT
        result = await ppt_generation_service.generate_ppt(
            topic=request.topic,
            outline=request.outline,
            knowledge_points=request.knowledge_points,
            template_id=request.template_id,
            author=request.author,
            search=request.search,
        )

        if result.status != "done":
            return unified_response(
                code=500,
                message=f"PPT生成失败: {result.error}",
                data={"status": result.status, "error": result.error},
            )

        # 步骤2: 创建课程记录
        document_id = str(uuid.uuid4())
        course = Course(
            fanya_course_id=f"ai_ppt_{document_id[:8]}",
            fanya_course_name=f"AI生成: {request.topic}",
            title=request.topic,
            description=f"AI生成的PPT课件 - {request.topic}",
            teacher_id=user_id,
            status=CourseStatus.DRAFT,
            is_ai_generated=True,
            source_file_name=os.path.basename(result.ppt_file_path),
            source_file_path=result.ppt_file_path,
            source_mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            total_pages=0,
        )
        session.add(course)
        session.commit()
        session.refresh(course)

        try:
            from app.common.slide_converter import get_or_create_pdf
            pdf_path = get_or_create_pdf(result.ppt_file_path)
            if pdf_path:
                course.pdf_file_path = pdf_path
                session.add(course)
                session.commit()
        except Exception as e:
            logger.warning(f"PDF conversion failed for generated PPT: {e}")

        if request.auto_parse and result.ppt_file_path:
            # 步骤3: 自动进入解析管线
            parse_result_data = await _parse_generated_pptx(
                session=session,
                course=course,
                ppt_file_path=result.ppt_file_path,
                user_id=user_id,
            )
            return unified_response(
                code=200,
                message="PPT生成并解析完成",
                data={
                    "course_id": course.id,
                    "ppt_file_path": result.ppt_file_path,
                    "ppt_url": result.ppt_url,
                    **parse_result_data,
                },
            )

        return unified_response(
            code=200,
            message="PPT生成完成",
            data={
                "course_id": course.id,
                "ppt_file_path": result.ppt_file_path,
                "ppt_url": result.ppt_url,
            },
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(code=500, message=f"PPT生成失败: {str(e)}", data=None)


# ---------- 后台任务 ----------

async def _generate_ppt_background(
    course_id: int,
    doc_id: int,
    user_id: int,
    topic: str,
    outline: Optional[str],
    knowledge_points: Optional[List[str]],
    template_id: Optional[str],
    author: str,
    search: bool,
    auto_parse: bool,
):
    """后台执行PPT生成和解析"""
    from app.models.database import engine
    from sqlmodel import Session as SQLSession

    with SQLSession(engine) as session:
        try:
            course = session.get(Course, course_id)
            docling_doc = session.get(DoclingDocument, doc_id)
            if not course or not docling_doc:
                logger.error(f"[PPT Background] 课程或文档记录不存在: course_id={course_id}")
                return

            # 更新状态为处理中
            docling_doc.status = ParseStatus.PROCESSING
            session.commit()

            # 生成PPT
            result = await ppt_generation_service.generate_ppt(
                topic=topic,
                outline=outline,
                knowledge_points=knowledge_points,
                template_id=template_id,
                author=author,
                search=search,
            )

            if result.status != "done":
                docling_doc.status = ParseStatus.FAILED
                docling_doc.error_message = result.error
                session.commit()
                logger.error(f"[PPT Background] PPT生成失败: {result.error}")
                return

            # 更新文件路径
            course.source_file_path = result.ppt_file_path
            course.source_file_name = os.path.basename(result.ppt_file_path)
            session.commit()

            try:
                from app.common.slide_converter import get_or_create_pdf
                pdf_path = get_or_create_pdf(result.ppt_file_path)
                if pdf_path:
                    course.pdf_file_path = pdf_path
                    session.add(course)
                    session.commit()
            except Exception as e:
                logger.warning(f"PDF conversion failed in background task: {e}")

            if auto_parse and result.ppt_file_path:
                await _parse_generated_pptx(
                    session=session,
                    course=course,
                    ppt_file_path=result.ppt_file_path,
                    user_id=user_id,
                )

        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"[PPT Background] 后台任务失败: {e}")
            try:
                docling_doc = session.get(DoclingDocument, doc_id)
                if docling_doc:
                    docling_doc.status = ParseStatus.FAILED
                    docling_doc.error_message = str(e)
                    session.commit()
            except Exception:
                pass


async def _parse_generated_pptx(
    session: Session,
    course: Course,
    ppt_file_path: str,
    user_id: int,
) -> dict:
    """解析生成的PPTX文件，进入文档解析管线"""
    from app.models.course_model import DoclingGroup, DoclingText

    logger.info(f"[PPT Parse] 开始解析生成的PPTX: {ppt_file_path}")

    try:
        process_result = await document_service.process_document(
            file_path=Path(ppt_file_path),
            filename=os.path.basename(ppt_file_path),
            enable_rag=True,
            enable_script=True,
        )

        parse_result = process_result.parse_result
        structure_result = process_result.structure_result
        script_result = process_result.script_result
        rag_result = process_result.rag_result
        mind_map = process_result.mind_map

        # 更新Docling文档
        docling_doc = session.exec(
            select(DoclingDocument).where(DoclingDocument.course_id == course.id)
        ).first()

        if docling_doc:
            # 存储分组
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

            # 存储文本
            total_texts = 0
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

            docling_doc.status = ParseStatus.COMPLETED
            docling_doc.total_groups = total_groups
            docling_doc.total_texts = total_texts
            docling_doc.raw_json = {
                "groups": structure_result.groups,
                "texts": structure_result.texts,
                "tables": structure_result.tables,
                "pictures": structure_result.pictures,
                "raw_content": structure_result.raw_content,
            }
            docling_doc.source_file_path = ppt_file_path
            docling_doc.updated_at = datetime.utcnow()
            session.commit()

        # 创建课程脚本
        course_script = CourseScript(
            course_id=course.id,
            version=1,
            version_name="v1.0",
            script_content=script_result.script_content,
            summary_text=script_result.summary,
            keywords=json.dumps(script_result.keywords, ensure_ascii=False),
            is_active=True,
            created_by=user_id,
        )
        session.add(course_script)
        session.commit()
        session.refresh(course_script)

        # 创建脚本节点
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

        # 更新课程统计
        course.total_nodes = len(script_result.nodes)
        course.total_duration = script_result.total_duration
        course.updated_at = datetime.utcnow()
        session.commit()

        logger.info(f"[PPT Parse] 解析完成: {len(script_result.nodes)} 个节点")

        return {
            "script_id": course_script.id,
            "total_nodes": len(script_result.nodes),
            "total_duration": script_result.total_duration,
            "summary": script_result.summary,
            "rag_info": {
                "formula_count": rag_result.formula_count,
                "table_count": rag_result.table_count,
                "knowledge_point_count": len(rag_result.knowledge_points),
            } if not rag_result.error else None,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"[PPT Parse] 解析PPT失败: {e}")
        return {"parse_error": str(e)}
