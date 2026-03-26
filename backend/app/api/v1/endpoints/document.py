"""
文档处理API接口
流程：上传文件 -> 解析为Markdown -> AI分析 -> 返回结果
Updated: 2026-03-26 - 测试模式：直接使用豆包解析，跳过Docling
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

router = APIRouter(tags=["文档处理"])

UPLOAD_DIR = Path(tempfile.gettempdir()) / "ai_course_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

document_cache = {}


@router.post("/upload", response_model=UnifiedResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的文档文件 (PDF, DOCX, PPTX等)")
):
    """
    上传文档并解析（测试模式：直接使用豆包解析文件内容）
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

        print(f"【测试模式】文件已保存: {file_path}")

        # 测试模式：直接使用豆包解析文件内容，跳过Docling
        file_content = await _read_file_content(file_path)
        
        print(f"【测试模式】文件内容长度: {len(file_content)} 字符")
        print(f"【测试模式】开始调用豆包直接解析...")

        # 调用豆包直接解析文件内容
        ai_analysis = ""
        try:
            ai_analysis = await _analyze_with_doubao(file_content, file.filename)
            print("="*60)
            print(f"【豆包解析结果】:")
            print("-"*60)
            print(f"总长度: {len(ai_analysis)} 字符")
            # 将完整结果保存到文件以便查看
            result_file = UPLOAD_DIR / f"{document_id}_analysis.txt"
            with open(result_file, "w", encoding="utf-8") as f:
                f.write(ai_analysis)
            print(f"完整结果已保存到: {result_file}")
            # 打印前2000字符预览
            preview_len = min(2000, len(ai_analysis))
            print(ai_analysis[:preview_len])
            if len(ai_analysis) > preview_len:
                print(f"\n... (还有 {len(ai_analysis) - preview_len} 字符，请查看文件)")
            print("="*60)
        except Exception as e:
            print(f"【豆包解析失败】: {e}")
            ai_analysis = f"豆包解析失败: {str(e)}"

        # 缓存结果
        document_cache[document_id] = {
            "filename": file.filename,
            "content": file_content,
            "analysis": ai_analysis,
            "file_path": str(file_path)
        }

        return unified_response(
            code=200,
            message="上传并解析成功",
            data={
                "fullContent": file_content,
                "analysis": ai_analysis,
                "title": file.filename,
                "audioUrl": None,
                "ChatId": document_id
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
        content = doc_data["content"]
        
        analysis = await _analyze_with_doubao(content, doc_data["filename"], request.prompt)
        
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
        "content_preview": doc_data["content"][:500] + "..." if len(doc_data["content"]) > 500 else doc_data["content"],
        "analysis_preview": doc_data.get("analysis", "")[:500] + "..." if len(doc_data.get("analysis", "")) > 500 else doc_data.get("analysis", "")
    }


async def _read_file_content(file_path: Path) -> str:
    """
    读取文件内容（测试模式：简单文本提取）
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


async def _analyze_with_doubao(content: str, filename: str, prompt: Optional[str] = None) -> str:
    """
    使用豆包直接解析文档内容
    """
    try:
        # 如果内容太长，截取前8000字符
        max_length = 8000
        truncated_content = content[:max_length]
        if len(content) > max_length:
            truncated_content += f"\n\n[内容已截断，原长度: {len(content)} 字符]"
        
        system_prompt = """你是一位专业的文档解析助手。请解析用户上传的文件内容，完成以下任务：
1. 提取文档的主要内容和核心信息
2. 总结文档的结构和要点
3. 识别关键概念和重要信息
4. 以清晰的格式输出解析结果

请用中文回答，结构清晰，条理分明。"""

        user_prompt = prompt or f"请解析以下文件内容（文件名: {filename}）："
        user_prompt += f"\n\n{truncated_content}"
        
        print(f"【豆包调用】发送请求，内容长度: {len(user_prompt)} 字符")
        
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt)
        ]
        
        response = await llm_client.chat(messages)
        
        print(f"【豆包调用】返回成功，响应长度: {len(response.content)} 字符")
        return response.content
        
    except Exception as e:
        print(f"【豆包调用】错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"豆包解析失败: {str(e)}"
