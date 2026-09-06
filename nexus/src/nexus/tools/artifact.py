"""M3 Artifact 工具：把真实文件写入对象存储（经 Backend 内部端点）。

设计文档 Phase 4 原则：不要模型输出"以下是 Word 文档内容"，要真实文件。
- 工具只接受 markdown / latex 文本对象（P0）；成功后返回 artifact_id 与
  下载路径（前端经 Backend JWT 路由下载）；
- 未配置内部端点 / 失败时 fail-closed 返回 ARTIFACT_UNAVAILABLE，
  绝不假造"文件已生成"（AGENTS.md §4.3 诚实性）。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from nexus.artifact_client import write_artifact_via_backend
from nexus.request_scope import current_user_id


@tool
async def write_artifact(artifact_type: str, title: str, content: str) -> dict[str, Any]:
    """把整理成果写成真实文件（Artifact），供用户下载。

    参数：
    - artifact_type：仅支持 "markdown"（研究报告、笔记、总结）或
      "latex"（论文/公式类内容）；
    - title：产物标题（将用作下载文件名，<=120 字符）；
    - content：完整正文（纯文本，<=512KB）。

    成功返回 artifact_id 与下载路径；失败如实返回错误（不得声称文件已生成）。
    输出长报告时优先调用本工具落成文件，再在对话中给出摘要。
    """
    result = await write_artifact_via_backend(
        artifact_type=artifact_type,
        title=title,
        content=content,
        user_id=current_user_id(),
    )
    if result.get("status") == "success":
        result["detail"] = "文件已真实写入存储，用户可在产物面板下载。"
    return result
