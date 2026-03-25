"""
文档处理相关的请求/响应数据模型
"""

from typing import Optional
from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """文档上传响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="处理结果消息")
    document_id: Optional[str] = Field(None, description="文档ID")
    filename: Optional[str] = Field(None, description="原始文件名")
    markdown_content: Optional[str] = Field(None, description="文档解析后的Markdown内容")
    ai_analysis: Optional[str] = Field(None, description="AI分析结果")
    error: Optional[str] = Field(None, description="错误信息")


class DocumentAnalyzeRequest(BaseModel):
    """文档分析请求"""
    document_id: str = Field(..., description="文档ID")
    prompt: Optional[str] = Field(
        default="请分析这份文档的主要内容，提取关键知识点，并给出结构化的总结。",
        description="AI分析提示词"
    )


class DocumentAnalyzeResponse(BaseModel):
    """文档分析响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="处理结果消息")
    analysis: Optional[str] = Field(None, description="AI分析结果")
    error: Optional[str] = Field(None, description="错误信息")
