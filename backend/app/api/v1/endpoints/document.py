"""
文档处理API接口
流程：上传文件 -> 解析文件 -> 存储到数据库 -> AI生成脚本 -> 存储脚本节点 -> 返回结果
Updated: 2026-03-28 - 按照数据库接口与文件解析交互流程文档修改，使用模拟数据测试AI生成步骤
"""

import os
import uuid
import tempfile
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.schemas.document_schema import (
    DocumentUploadResponse,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
)
from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
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

router = APIRouter(tags=["文档处理"])

UPLOAD_DIR = Path(tempfile.gettempdir()) / "ai_course_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

document_cache = {}

DEFAULT_TEACHER_ID = 1


@router.post("/upload", response_model=UnifiedResponse)
async def upload_document(
    file: UploadFile = File(..., description="上传的文档文件 (PDF, DOCX, PPTX等)"),
    session: Session = Depends(get_session),
):
    """
    上传文档并解析，存储到数据库，生成智课脚本
    
    流程（按照数据库接口与文件解析交互流程文档）：
    1. 存储文件信息到 courses 表
    2. 创建 docling_documents 记录 (status = PENDING)
    3. 调用解析API，更新 status = PROCESSING
    4. 存储解析结果到相关表，更新 status = COMPLETED
    5. 调用AI API生成智课脚本 -> 创建 course_scripts 记录
    6. 拆分脚本节点 -> 创建 script_nodes 记录
    7. 返回结果
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
            raise HTTPException(status_code=413, detail="文件大小超过50MB限制")

        print(f"[步骤1] 存储文件信息到 courses 表")
        print(f"  文件已保存: {file_path}")

        course = Course(
            fanya_course_id=f"local_{document_id[:8]}",
            fanya_course_name=file.filename,
            title=Path(file.filename).stem,
            description=f"从文件 {file.filename} 导入的课程",
            teacher_id=DEFAULT_TEACHER_ID,
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

        print(f"[步骤3] 调用解析API，更新 status = PROCESSING")
        docling_doc.status = ParseStatus.PROCESSING
        session.commit()
        print(f"  更新状态: PROCESSING")

        file_content = await _read_file_content(file_path)
        print(f"  解析文件内容: {len(file_content)} 字符")

        parse_result = _parse_content_to_structure(file_content, file.filename)

        print(f"[步骤4] 存储解析结果到相关表")
        total_texts = 0
        total_tables = 0
        total_pictures = 0
        total_groups = 0

        for group_data in parse_result.get("groups", []):
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

        for idx, text_data in enumerate(parse_result.get("texts", [])):
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

        for idx, table_data in enumerate(parse_result.get("tables", [])):
            table_record = DoclingTable(
                doc_id=docling_doc.id,
                group_id=None,
                self_ref=f"#/tables/{idx}",
                label="table",
                page_no=table_data.get("page_no", 1),
                num_rows=table_data.get("num_rows", 0),
                num_cols=table_data.get("num_cols", 0),
                table_data=table_data.get("data"),
                sort_order=idx,
            )
            session.add(table_record)
            session.commit()
            session.refresh(table_record)

            for cell_data in table_data.get("cells", []):
                cell = DoclingTableCell(
                    table_id=table_record.id,
                    row_idx=cell_data.get("row_idx", 0),
                    col_idx=cell_data.get("col_idx", 0),
                    text=cell_data.get("text", ""),
                    row_span=cell_data.get("row_span", 1),
                    col_span=cell_data.get("col_span", 1),
                )
                session.add(cell)
            total_tables += 1
        session.commit()
        print(f"  存储 {total_tables} 个表格记录")

        for idx, pic_data in enumerate(parse_result.get("pictures", [])):
            picture = DoclingPicture(
                doc_id=docling_doc.id,
                group_id=None,
                self_ref=f"#/pictures/{idx}",
                label="picture",
                image_url=pic_data.get("image_url"),
                page_no=pic_data.get("page_no", 1),
                sort_order=idx,
            )
            session.add(picture)
            total_pictures += 1
        session.commit()
        print(f"  存储 {total_pictures} 个图片记录")

        docling_doc.status = ParseStatus.COMPLETED
        docling_doc.total_groups = total_groups
        docling_doc.total_texts = total_texts
        docling_doc.total_tables = total_tables
        docling_doc.total_pictures = total_pictures
        docling_doc.raw_json = parse_result
        docling_doc.updated_at = datetime.utcnow()
        session.commit()
        print(f"  更新状态: COMPLETED")

        print(f"[步骤5] 调用AI API生成智课脚本")
        print(f"  读取 docling_documents 中的解析数据...")
        print(f"  调用AI API生成脚本（使用模拟数据测试）...")
        
        ai_script_result = await _call_ai_api_generate_script(parse_result, file.filename)
        
        course_script = CourseScript(
            course_id=course.id,
            version=1,
            version_name="v1.0",
            script_content=ai_script_result["script_content"],
            summary_text=ai_script_result["summary_text"],
            keywords=json.dumps(ai_script_result["keywords"], ensure_ascii=False),
            is_active=True,
            audio_url=None,
            audio_duration=0,
            created_by=DEFAULT_TEACHER_ID,
        )
        session.add(course_script)
        session.commit()
        session.refresh(course_script)
        print(f"  创建课程脚本记录: ID={course_script.id}")
        print(f"  存储 script_content (JSON)")
        print(f"  存储 summary_text, keywords")

        print(f"[步骤6] 拆分脚本节点")
        nodes_data = ai_script_result["script_content"].get("nodes", [])
        for idx, node_data in enumerate(nodes_data):
            node = ScriptNode(
                script_id=course_script.id,
                chapter_id=node_data.get("chapter_id", f"chap_{idx:03d}"),
                node_index=idx,
                node_type=ScriptNodeType(node_data.get("node_type", "lecture")),
                title=node_data.get("title", f"节点 {idx + 1}"),
                content=node_data.get("content", ""),
                page_start=node_data.get("page_start", 1),
                page_end=node_data.get("page_end", 1),
                duration=node_data.get("duration", 60),
                is_key_point=node_data.get("is_key_point", False),
            )
            session.add(node)
        session.commit()
        print(f"  创建 {len(nodes_data)} 个 script_nodes 记录")
        print(f"  存储每个节点的 content, page_start, page_end")

        course.total_nodes = len(nodes_data)
        course.total_duration = sum(n.get("duration", 60) for n in nodes_data)
        course.is_ai_generated = True
        course.updated_at = datetime.utcnow()
        session.commit()
        print(f"  更新课程统计: total_nodes={course.total_nodes}, total_duration={course.total_duration}")

        document_cache[document_id] = {
            "course_id": course.id,
            "script_id": course_script.id,
            "doc_id": docling_doc.id,
            "filename": file.filename,
            "content": file_content,
            "script_content": ai_script_result["script_content"],
            "file_path": str(file_path),
        }

        print(f"[步骤7] 返回结果给前端")
        return unified_response(
            code=200,
            message="上传并解析成功，智课脚本已生成",
            data={
                "courseId": course.id,
                "scriptId": course_script.id,
                "docId": docling_doc.id,
                "title": course.title,
                "fullContent": file_content,
                "scriptContent": ai_script_result["script_content"],
                "summaryText": ai_script_result["summary_text"],
                "keywords": ai_script_result["keywords"],
                "audioUrl": None,
                "chatId": document_id,
                "totalNodes": course.total_nodes,
                "totalDuration": course.total_duration,
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


async def _read_file_content(file_path: Path) -> str:
    """
    读取文件内容
    """
    suffix = file_path.suffix.lower()
    
    if suffix == ".pdf":
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            return "\n\n".join(text_parts)
        except ImportError:
            return f"[PDF文件: {file_path.name}]"
    
    elif suffix in [".docx", ".doc"]:
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except ImportError:
            return f"[Word文件: {file_path.name}]"
    
    elif suffix in [".pptx", ".ppt"]:
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            text_parts = []
            for slide_num, slide in enumerate(prs.slides, 1):
                slide_text = [f"## 第{slide_num}页"]
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text.strip())
                text_parts.append("\n".join(slide_text))
            return "\n\n".join(text_parts)
        except ImportError:
            return f"[PPT文件: {file_path.name}]"
    
    elif suffix in [".txt", ".md", ".json", ".py", ".js", ".html", ".css"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    
    else:
        return f"[文件: {file_path.name}]"


def _parse_content_to_structure(content: str, filename: str) -> dict:
    """
    将文件内容解析为结构化数据
    返回格式符合 Docling 解析结果的结构
    """
    lines = content.split("\n")
    texts = []
    groups = []
    
    current_group_idx = 0
    text_idx = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if line.startswith("##"):
            groups.append({
                "self_ref": f"#/groups/{current_group_idx}",
                "name": line[2:].strip(),
                "label": "section",
                "content_layer": "body",
            })
            current_group_idx += 1
        else:
            texts.append({
                "self_ref": f"#/texts/{text_idx}",
                "label": "paragraph",
                "text": line,
                "page_no": 1,
            })
            text_idx += 1
    
    if not groups:
        groups.append({
            "self_ref": "#/groups/0",
            "name": filename,
            "label": "section",
            "content_layer": "body",
        })
    
    return {
        "groups": groups,
        "texts": texts,
        "tables": [],
        "pictures": [],
        "raw_content": content,
    }


async def _call_ai_api_generate_script(parse_result: dict, filename: str) -> dict:
    """
    调用AI API生成智课脚本
    
    按照流程文档：
    - 读取 docling_documents 中的解析数据
    - 调用AI API生成脚本
    - 返回结构化脚本内容
    
    当前使用模拟数据测试代码可行性，后续替换为真实AI调用
    """
    print(f"  [AI API调用] 开始生成脚本...")
    print(f"  [AI API调用] 输入: 解析数据包含 {len(parse_result.get('texts', []))} 条文本")
    
    raw_content = parse_result.get("raw_content", "")
    lines = [l.strip() for l in raw_content.split("\n") if l.strip()]
    
    nodes = []
    chapter_counter = 0
    
    for idx, line in enumerate(lines[:20]):
        if len(line) > 10:
            node_type = "lecture"
            if "总结" in line or idx == len(lines[:20]) - 1:
                node_type = "summary"
            elif "?" in line or "？" in line:
                node_type = "question"
            
            nodes.append({
                "chapter_id": f"chap_{chapter_counter:03d}",
                "node_type": node_type,
                "title": line[:50] + ("..." if len(line) > 50 else ""),
                "content": line,
                "page_start": 1,
                "page_end": 1,
                "duration": 60,
                "is_key_point": chapter_counter % 3 == 0,
            })
            chapter_counter += 1
    
    if not nodes:
        nodes = [
            {
                "chapter_id": "chap_000",
                "node_type": "lecture",
                "title": "课程导入",
                "content": f"欢迎学习本课程，本课程来源于文件 {filename}",
                "page_start": 1,
                "page_end": 1,
                "duration": 60,
                "is_key_point": True,
            }
        ]
    
    if not any(n["node_type"] == "summary" for n in nodes):
        nodes.append({
            "chapter_id": f"chap_{len(nodes):03d}",
            "node_type": "summary",
            "title": "课程总结",
            "content": "本节课程内容已结束，请回顾重点知识点，巩固学习成果。",
            "page_start": 1,
            "page_end": 1,
            "duration": 30,
            "is_key_point": False,
        })
    
    summary_text = f"本课程《{Path(filename).stem}》共包含 {len(nodes)} 个知识点，" \
                   f"总时长约 {sum(n['duration'] for n in nodes) // 60} 分钟。" \
                   f"课程内容涵盖文档中的核心概念和重要知识点。"
    
    keywords = ["知识点", "课程", Path(filename).stem, "学习", "核心概念"]
    
    script_content = {
        "title": Path(filename).stem,
        "summary": summary_text,
        "keywords": keywords,
        "total_duration": sum(n["duration"] for n in nodes),
        "nodes": nodes,
    }
    
    print(f"  [AI API调用] 生成完成: {len(nodes)} 个节点, 总时长 {script_content['total_duration']} 秒")
    
    return {
        "script_content": script_content,
        "summary_text": summary_text,
        "keywords": keywords,
    }
