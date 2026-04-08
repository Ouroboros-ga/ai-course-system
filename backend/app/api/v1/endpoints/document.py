"""
文档处理API接口
流程：上传文件 -> Docling解析为Markdown -> 豆包AI生成智课脚本 -> 存储到数据库 -> 返回结果
Updated: 2026-03-28 - 集成Docling解析和豆包AI，添加用户认证
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
    4. 调用Docling解析，输出Markdown，更新 status = PROCESSING -> COMPLETED
    5. 将Markdown传递给豆包AI生成智课脚本 -> 创建 course_scripts 记录
    6. 拆分脚本节点 -> 创建 script_nodes 记录
    7. 创建聊天记录归档
    8. 返回结果
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

        print(f"[步骤3] 调用Docling解析，更新 status = PROCESSING")
        docling_doc.status = ParseStatus.PROCESSING
        session.commit()
        print(f"  更新状态: PROCESSING")

        markdown_content = await _parse_with_docling(file_path, file.filename)
        print(f"  Docling解析完成: {len(markdown_content)} 字符")

        parse_result = _parse_markdown_to_structure(markdown_content, file.filename)

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

        docling_doc.status = ParseStatus.COMPLETED
        docling_doc.total_groups = total_groups
        docling_doc.total_texts = total_texts
        docling_doc.total_tables = total_tables
        docling_doc.total_pictures = total_pictures
        docling_doc.raw_json = parse_result
        docling_doc.updated_at = datetime.utcnow()
        session.commit()
        print(f"  更新状态: COMPLETED")

        print(f"[步骤5] 调用豆包AI生成智课脚本")
        print(f"  将Markdown传递给豆包AI...")
        
        ai_script_result = await smart_course_service.generate_structured_script(
            markdown_content, file.filename
        )
        
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
            created_by=user_id,
        )
        session.add(course_script)
        session.commit()
        session.refresh(course_script)
        print(f"  创建课程脚本记录: ID={course_script.id}")

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

        course.total_nodes = len(nodes_data)
        course.total_duration = sum(n.get("duration", 60) for n in nodes_data)
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
            "markdown_content": markdown_content,
            "script_content": ai_script_result["script_content"],
            "file_path": str(file_path),
        }

        mind_map_json = _generate_mind_map(ai_script_result["script_content"])
        
        beautiful_markdown = ai_script_result.get("beautiful_markdown", markdown_content)
        
        print(f"[步骤8] 返回结果给前端")
        print(f"  精美Markdown长度: {len(beautiful_markdown)}")
        print(f"  原始Markdown长度: {len(markdown_content)}")
        
        return unified_response(
            code=200,
            message="上传并解析成功",
            data={
                "fullContent": beautiful_markdown,
                "rawContent": markdown_content,
                "title": course.title,
                "audioUrl": None,
                "mindMapJson": mind_map_json,
                "chatId": chat_id,
                "courseId": course.id,
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


async def _parse_with_docling(file_path: Path, filename: str) -> str:
    """
    使用Docling解析文件，返回Markdown内容
    """
    try:
        from docling.document_converter import DocumentConverter
        
        print(f"  [Docling] 开始解析: {filename}")
        converter = DocumentConverter()
        result = converter.convert(str(file_path))
        markdown_content = result.document.export_to_markdown()
        print(f"  [Docling] 解析完成，生成 {len(markdown_content)} 字符Markdown")
        return markdown_content
        
    except ImportError:
        print(f"  [Docling] 未安装，使用备用解析方法")
        return await _fallback_parse(file_path, filename)
    except Exception as e:
        print(f"  [Docling] 解析失败: {e}，使用备用方法")
        return await _fallback_parse(file_path, filename)


async def _fallback_parse(file_path: Path, filename: str) -> str:
    """
    备用解析方法（当Docling不可用时）
    生成结构化的Markdown格式
    """
    suffix = file_path.suffix.lower()
    
    if suffix == ".pdf":
        try:
            import pdfplumber
            text_parts = [f"# {Path(filename).stem}\n"]
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        text_parts.append(f"\n## 第{page_num}页\n")
                        text_parts.append(f"{text}\n")
            return "\n".join(text_parts)
        except ImportError:
            return f"# {filename}\n\n[PDF文件需要安装pdfplumber库才能解析]"
    
    elif suffix in [".docx", ".doc"]:
        try:
            from docx import Document
            doc = Document(file_path)
            text_parts = [f"# {Path(filename).stem}\n"]
            
            for para in doc.paragraphs:
                if para.text.strip():
                    if para.style.name.startswith('Heading'):
                        level = int(para.style.name.replace('Heading ', '')) if para.style.name != 'Heading' else 1
                        text_parts.append(f"\n{'#' * level} {para.text.strip()}\n")
                    else:
                        text_parts.append(f"{para.text.strip()}\n")
            
            return "\n".join(text_parts)
        except ImportError:
            return f"# {filename}\n\n[Word文件需要安装python-docx库才能解析]"
    
    elif suffix in [".pptx", ".ppt"]:
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            text_parts = [f"# {Path(filename).stem}\n"]
            text_parts.append("\n> 本文档由PPT自动解析生成\n")
            
            for slide_num, slide in enumerate(prs.slides, 1):
                title = ""
                if slide.shapes.title and slide.shapes.title.text:
                    title = slide.shapes.title.text.strip()
                
                text_parts.append(f"\n## 第{slide_num}页{': ' + title if title else ''}\n")
                
                content_items = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        text = shape.text.strip()
                        if text != title:
                            content_items.append(text)
                
                for item in content_items:
                    if len(item) < 50 and not item.endswith(('。', '，', '：', '.', ',', ':')):
                        if item.endswith('?') or item.endswith('？'):
                            text_parts.append(f"\n### ❓ {item}\n")
                        else:
                            text_parts.append(f"\n### {item}\n")
                    else:
                        text_parts.append(f"\n{item}\n")
            
            return "\n".join(text_parts)
        except ImportError:
            return f"# {filename}\n\n[PPT文件需要安装python-pptx库才能解析]"
    
    elif suffix in [".txt", ".md", ".json", ".py", ".js", ".html", ".css"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if suffix == ".md":
            return content
        else:
            return f"# {filename}\n\n```\n{content}\n```"
    
    else:
        return f"# {filename}\n\n[不支持的文件格式: {suffix}]"


def _parse_markdown_to_structure(markdown_content: str, filename: str) -> dict:
    """
    将Markdown内容解析为结构化数据
    """
    lines = markdown_content.split("\n")
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
                "name": line.lstrip("#").strip(),
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
        "raw_content": markdown_content,
    }


async def _generate_script_with_doubao(markdown_content: str, filename: str) -> dict:
    """
    调用豆包AI生成智课脚本
    
    将Docling输出的Markdown传递给豆包AI，生成结构化的智课脚本
    """
    print(f"  [豆包AI] 开始生成脚本...")
    
    max_content_length = 6000
    if len(markdown_content) > max_content_length:
        truncated_content = markdown_content[:max_content_length]
        truncated_content += f"\n\n[内容已截断，原长度: {len(markdown_content)} 字符]"
    else:
        truncated_content = markdown_content
    
    system_prompt = """你是一位专业的课程设计师。请根据用户提供的文档内容，生成一份结构化的智课脚本。

你需要完成以下任务：
1. 分析文档内容，提取核心知识点
2. 将内容拆分为多个教学节点（每个节点60-120秒）
3. 为每个节点生成标题、内容摘要和时长
4. 识别重点知识点
5. 生成课程总结

请以JSON格式返回结果，格式如下：
{
    "title": "课程标题",
    "summary": "课程摘要",
    "keywords": ["关键词1", "关键词2", ...],
    "total_duration": 总时长(秒),
    "nodes": [
        {
            "chapter_id": "chap_001",
            "node_type": "lecture",
            "title": "节点标题",
            "content": "节点内容/讲解文本",
            "page_start": 1,
            "page_end": 1,
            "duration": 60,
            "is_key_point": false
        },
        ...
    ]
}

节点类型(node_type)可选值：
- lecture: 讲解
- question: 问题
- summary: 总结
- interactive: 交互

请确保返回的是有效的JSON格式。"""

    user_prompt = f"""请根据以下文档内容生成智课脚本：

文件名: {filename}

文档内容：
{truncated_content}

请生成结构化的智课脚本JSON。"""

    try:
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt)
        ]
        
        print(f"  [豆包AI] 发送请求，内容长度: {len(user_prompt)} 字符")
        response = await llm_client.chat(messages)
        print(f"  [豆包AI] 收到响应，长度: {len(response.content)} 字符")
        
        import re
        json_match = re.search(r'\{[\s\S]*\}', response.content)
        if json_match:
            script_content = json.loads(json_match.group())
        else:
            script_content = _create_default_script(filename, markdown_content)
        
    except Exception as e:
        print(f"  [豆包AI] 调用失败: {e}，使用默认脚本")
        script_content = _create_default_script(filename, markdown_content)
    
    summary_text = script_content.get("summary", f"本课程《{Path(filename).stem}》包含 {len(script_content.get('nodes', []))} 个知识点。")
    keywords = script_content.get("keywords", ["知识点", "课程", Path(filename).stem])
    
    print(f"  [豆包AI] 生成完成: {len(script_content.get('nodes', []))} 个节点")
    
    return {
        "script_content": script_content,
        "summary_text": summary_text,
        "keywords": keywords,
    }


def _create_default_script(filename: str, content: str) -> dict:
    """
    创建默认脚本（当AI调用失败时）
    """
    lines = [l.strip() for l in content.split("\n") if l.strip() and len(l.strip()) > 10]
    
    nodes = []
    for idx, line in enumerate(lines[:15]):
        node_type = "lecture"
        if idx == len(lines[:15]) - 1:
            node_type = "summary"
        
        nodes.append({
            "chapter_id": f"chap_{idx:03d}",
            "node_type": node_type,
            "title": line[:50] + ("..." if len(line) > 50 else ""),
            "content": line,
            "page_start": 1,
            "page_end": 1,
            "duration": 60,
            "is_key_point": idx % 3 == 0,
        })
    
    if not nodes:
        nodes = [{
            "chapter_id": "chap_000",
            "node_type": "lecture",
            "title": "课程导入",
            "content": f"欢迎学习本课程，本课程来源于文件 {filename}",
            "page_start": 1,
            "page_end": 1,
            "duration": 60,
            "is_key_point": True,
        }]
    
    return {
        "title": Path(filename).stem,
        "summary": f"本课程《{Path(filename).stem}》共包含 {len(nodes)} 个知识点。",
        "keywords": ["知识点", "课程", Path(filename).stem],
        "total_duration": sum(n["duration"] for n in nodes),
        "nodes": nodes,
    }


def _generate_mind_map(script_content: dict) -> dict:
    """
    根据脚本内容生成思维导图JSON结构
    """
    nodes = script_content.get("nodes", [])
    title = script_content.get("title", "课程内容")
    keywords = script_content.get("keywords", [])
    
    children = []
    
    for node in nodes:
        child = {
            "text": node.get("title", "未命名节点"),
        }
        if node.get("is_key_point"):
            child["highlight"] = True
        children.append(child)
    
    if not children:
        for kw in keywords[:5]:
            children.append({"text": kw})
    
    if not children:
        children = [
            {"text": "知识点1"},
            {"text": "知识点2"},
            {"text": "知识点3"},
        ]
    
    return {
        "text": title,
        "children": children
    }
