"""
文档处理API接口
流程：上传文件 -> 解析为Markdown -> AI分析 -> 返回结果
Updated: 2026-03-25
"""

import os
import uuid
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from app.schemas.document_schema import (
    DocumentUploadResponse,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
)
from app.schemas.common_schema import UnifiedResponse
from app.common.llm_client import llm_client, Message
from app.core.exceptions import unified_response

# 尝试导入文档解析模块
try:
    from app.common.test.wm.doc_processor import UniversalDocProcessor, Markdown
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    print("警告: Docling文档解析模块未安装，将使用模拟模式")

router = APIRouter(tags=["文档处理"])

# 临时存储上传文件（生产环境应使用云存储或数据库）
UPLOAD_DIR = Path(tempfile.gettempdir()) / "ai_course_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 存储文档解析结果（生产环境应使用Redis或数据库）
document_cache = {}


@router.post("/upload", response_model=UnifiedResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的文档文件 (PDF, DOCX, PPTX等)")
):
    """
    上传文档并解析

    流程：
    1. 保存上传的文件
    2. 使用Docling解析为Markdown
    3. 调用豆包AI进行内容分析
    4. 返回解析结果
    """
    try:
        # 生成文档ID
        document_id = str(uuid.uuid4())

        # 保存文件
        file_ext = Path(file.filename).suffix.lower()
        safe_filename = f"{document_id}{file_ext}"
        file_path = UPLOAD_DIR / safe_filename

        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 检查文件大小
        file_size = file_path.stat().st_size
        if file_size > 50 * 1024 * 1024:  # 50MB限制
            file_path.unlink()
            raise HTTPException(status_code=413, detail="文件大小超过50MB限制")

        # 解析文档为Markdown
        if DOCLING_AVAILABLE:
            try:
                processor = UniversalDocProcessor()
                markdown_content = processor.convert(file_path, save_file=False)
            except Exception as e:
                # 如果Docling解析失败，尝试使用备用方法
                print(f"Docling解析失败: {e}")
                markdown_content = await _fallback_parse(file_path)
        else:
            markdown_content = await _fallback_parse(file_path)

        # 调用AI分析文档内容
        ai_analysis = await _analyze_document(str(markdown_content))

        # 缓存结果
        document_cache[document_id] = {
            "filename": file.filename,
            "markdown": str(markdown_content),
            "analysis": ai_analysis,
            "file_path": str(file_path)
        }

        return unified_response(
            code=200,
            message="文档上传并解析成功",
            data={
                "document_id": document_id,
                "filename": file.filename,
                "markdown_content": str(markdown_content)[:2000] + "..." if len(str(markdown_content)) > 2000 else str(markdown_content),
                "ai_analysis": ai_analysis
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        return unified_response(
            code=500,
            message="文档处理失败",
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
        markdown_content = doc_data["markdown"]
        
        # 调用AI分析
        analysis = await _analyze_document(markdown_content, request.prompt)
        
        # 更新缓存
        document_cache[request.document_id]["analysis"] = analysis
        
        return DocumentAnalyzeResponse(
            success=True,
            message="分析完成",
            analysis=analysis
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
async def get_document(document_id: str):
    """
    获取文档信息
    """
    if document_id not in document_cache:
        raise HTTPException(status_code=404, detail="文档不存在或已过期")
    
    doc_data = document_cache[document_id]
    return {
        "document_id": document_id,
        "filename": doc_data["filename"],
        "markdown_preview": doc_data["markdown"][:500] + "..." if len(doc_data["markdown"]) > 500 else doc_data["markdown"],
        "analysis_preview": doc_data.get("analysis", "")[:500] + "..." if len(doc_data.get("analysis", "")) > 500 else doc_data.get("analysis", "")
    }


async def _fallback_parse(file_path: Path) -> str:
    """
    备用文档解析方法（当Docling不可用时）
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
            return f"[PDF文件: {file_path.name}]\n\n请安装 pdfplumber 以解析PDF内容: pip install pdfplumber"
    
    elif suffix in [".docx", ".doc"]:
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except ImportError:
            return f"[Word文件: {file_path.name}]\n\n请安装 python-docx 以解析Word内容: pip install python-docx"
    
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
            return f"[PPT文件: {file_path.name}]\n\n请安装 python-pptx 以解析PPT内容: pip install python-pptx"
    
    elif suffix in [".txt", ".md", ".json", ".py", ".js", ".html", ".css"]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    
    else:
        return f"[文件: {file_path.name}]\n\n不支持的文件格式: {suffix}"


async def _analyze_document(markdown_content: str, prompt: Optional[str] = None) -> str:
    """
    调用豆包AI分析文档内容
    """
    try:
        # 如果内容太长，截取前8000字符
        max_length = 8000
        truncated_content = markdown_content[:max_length]
        if len(markdown_content) > max_length:
            truncated_content += f"\n\n[内容已截断，原长度: {len(markdown_content)} 字符]"
        
        system_prompt = """你是一位专业的教育内容分析助手。请分析提供的文档内容，完成以下任务：
1. 提取文档的主要主题和核心知识点
2. 总结文档的结构和逻辑框架
3. 识别关键概念和术语
4. 给出适合教学使用的建议

请用中文回答，结构清晰，条理分明。"""

        user_prompt = prompt or "请分析以下文档内容："
        user_prompt += f"\n\n{truncated_content}"
        
        # 调用豆包AI
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt)
        ]
        
        response = await llm_client.chat(messages)
        return response.content
        
    except Exception as e:
        return f"AI分析失败: {str(e)}"
