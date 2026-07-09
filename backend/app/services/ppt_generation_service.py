"""
科大讯飞智能PPT生成服务
F3 · AI生成PPT课件
流程：老师输入大纲/主题/知识点 → LLM扩展为结构化教学脚本 → 讯飞PPT API生成.pptx → 自动进入解析管线
"""

import hashlib
import hmac
import base64
import json
import time
import os
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings
from app.common.llm_client import llm_client, Message
from app.platform.adapters.ppt import PPTAdapter
from app.platform.tasks import TaskContext, TaskRunner, TaskType

logger = logging.getLogger(__name__)


@dataclass
class PPTTaskResult:
    """PPT生成任务结果"""
    sid: str = ""
    status: str = "pending"
    ppt_url: str = ""
    ppt_file_path: str = ""
    error: str = ""


class XfyunPPTClient:
    """科大讯飞PPT生成API客户端"""

    BASE_URL = "https://zwapi.xfyun.cn/api/ppt/v2"

    def __init__(self):
        self.app_id = settings.XFYUN_PPT_APP_ID
        self.api_secret = settings.XFYUN_PPT_API_SECRET

    def _get_signature(self, ts: int) -> str:
        """生成鉴权签名: MD5(appId + ts) -> HMAC-SHA1(md5_result, secret) -> Base64"""
        auth = hashlib.md5(f"{self.app_id}{ts}".encode()).hexdigest()
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode("utf-8"),
                auth.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")
        return signature

    def _get_headers(self, content_type: str = "application/json; charset=utf-8") -> Dict[str, str]:
        """获取带鉴权的请求头"""
        ts = int(time.time())
        signature = self._get_signature(ts)
        return {
            "appId": self.app_id,
            "timestamp": str(ts),
            "signature": signature,
            "Content-Type": content_type,
        }

    async def get_theme_list(
        self,
        pay_type: str = "free",
        style: Optional[str] = None,
        color: Optional[str] = None,
        industry: Optional[str] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取PPT模板列表"""
        url = f"{self.BASE_URL}/template/list"
        headers = self._get_headers()
        body = {
            "payType": pay_type,
            "pageNum": page_num,
            "pageSize": page_size,
        }
        if style:
            body["style"] = style
        if color:
            body["color"] = color
        if industry:
            body["industry"] = industry

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()

    async def create_outline(
        self,
        text: str,
        language: str = "cn",
        search: bool = False,
    ) -> Dict[str, Any]:
        """根据文本内容生成PPT大纲"""
        url = f"{self.BASE_URL}/outline/create"
        headers = self._get_headers()
        body = {
            "text": text,
            "language": language,
            "search": str(search).lower(),
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()

    async def create_ppt_task(
        self,
        query: str,
        template_id: str,
        author: str = "AI智课",
        is_card_note: bool = True,
        search: bool = False,
        is_figure: bool = True,
        ai_image: str = "normal",
    ) -> Dict[str, Any]:
        """创建PPT生成任务（通过文本描述）"""
        url = f"{self.BASE_URL}/create"
        ts = int(time.time())
        signature = self._get_signature(ts)

        # 使用 multipart/form-data
        form_fields = {
            "query": query,
            "templateId": template_id,
            "author": author,
            "isCardNote": str(is_card_note),
            "search": str(search).lower(),
            "isFigure": str(is_figure).lower(),
            "aiImage": ai_image,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                url,
                data=form_fields,
                headers={
                    "appId": self.app_id,
                    "timestamp": str(ts),
                    "signature": signature,
                },
            )
            response.raise_for_status()
            return response.json()

    async def create_ppt_by_outline(
        self,
        query: str,
        outline: str,
        template_id: str,
        author: str = "AI智课",
        is_card_note: bool = True,
        search: bool = False,
        is_figure: bool = True,
        ai_image: str = "normal",
    ) -> Dict[str, Any]:
        """根据大纲创建PPT生成任务"""
        url = f"{self.BASE_URL}/outline/create"
        ts = int(time.time())
        signature = self._get_signature(ts)

        form_fields = {
            "query": query,
            "outline": outline,
            "templateId": template_id,
            "author": author,
            "isCardNote": str(is_card_note),
            "search": str(search).lower(),
            "isFigure": str(is_figure).lower(),
            "aiImage": ai_image,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                url,
                data=form_fields,
                headers={
                    "appId": self.app_id,
                    "timestamp": str(ts),
                    "signature": signature,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_task_progress(self, sid: str) -> Dict[str, Any]:
        """查询PPT生成任务进度"""
        url = f"{self.BASE_URL}/progress?sid={sid}"
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def wait_for_completion(
        self, sid: str, max_wait: int = 300, poll_interval: int = 5
    ) -> PPTTaskResult:
        """轮询等待PPT生成完成"""
        start_time = time.time()
        headers = self._get_headers()

        while time.time() - start_time < max_wait:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(
                        f"{self.BASE_URL}/progress?sid={sid}",
                        headers=headers,
                    )
                    response.raise_for_status()
                    result = response.json()

                if result.get("code") != 0:
                    return PPTTaskResult(
                        sid=sid,
                        status="failed",
                        error=result.get("message", "查询进度失败"),
                    )

                data = result.get("data", {})
                ppt_status = data.get("pptStatus", "")
                ai_image_status = data.get("aiImageStatus", "")
                card_note_status = data.get("cardNoteStatus", "")

                if ppt_status == "done" and ai_image_status == "done" and card_note_status == "done":
                    ppt_url = data.get("pptUrl", "")
                    return PPTTaskResult(
                        sid=sid,
                        status="done",
                        ppt_url=ppt_url,
                    )

                if ppt_status == "failed":
                    return PPTTaskResult(
                        sid=sid,
                        status="failed",
                        error="PPT生成失败",
                    )

                logger.info(
                    f"[XfyunPPT] 任务 {sid} 进度: ppt={ppt_status}, image={ai_image_status}, note={card_note_status}"
                )

            except Exception as e:
                logger.warning(f"[XfyunPPT] 查询进度异常: {e}")

            await asyncio_sleep(poll_interval)

        return PPTTaskResult(sid=sid, status="timeout", error="PPT生成超时")

    async def download_ppt(self, ppt_url: str, save_path: str) -> str:
        """下载生成的PPT文件"""
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(ppt_url)
            response.raise_for_status()

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.content)

            return save_path


async def asyncio_sleep(seconds: float):
    """异步等待"""
    import asyncio
    await asyncio.sleep(seconds)


class PPTGenerationService:
    """F3 AI生成PPT课件服务"""

    def __init__(self):
        self.xfyun_client = XfyunPPTClient()
        self.ppt_storage_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "generated_pptx",
        )
        os.makedirs(self.ppt_storage_path, exist_ok=True)

    async def expand_to_teaching_script(
        self,
        topic: str,
        outline: Optional[str] = None,
        knowledge_points: Optional[List[str]] = None,
    ) -> str:
        """
        使用LLM将大纲/主题/知识点扩展为结构化教学脚本
        输出格式适合讯飞PPT API消费
        """
        system_prompt = """你是一个专业的教学课件设计专家。你需要根据老师提供的主题、大纲和知识点，
生成一份结构化的教学PPT内容描述，用于AI生成PPT课件。

要求：
1. 内容要详实、专业，适合大学教学
2. 每个知识点要有清晰的标题和要点说明
3. 适当包含教学互动环节（如思考题、小结）
4. 语言简洁精炼，适合PPT展示
5. 只输出PPT内容描述，不要其他解释

输出格式（Markdown）：
# 课件标题

## 第一部分：章节标题
- 要点1
- 要点2
- 关键概念说明

## 第二部分：章节标题
- 要点1
- 要点2

### 重点知识点
- 详细说明

## 小结
- 核心要点回顾"""

        user_parts = [f"课程主题：{topic}"]
        if outline:
            user_parts.append(f"\n课程大纲：\n{outline}")
        if knowledge_points:
            user_parts.append(f"\n知识点列表：\n" + "\n".join(f"- {kp}" for kp in knowledge_points))

        user_prompt = "\n".join(user_parts)

        try:
            response = await llm_client.chat(
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            return response.content.strip()
        except Exception as e:
            logger.error(f"[PPTGeneration] LLM扩展教学脚本失败: {e}")
            # fallback: 直接使用原始输入
            parts = [f"# {topic}"]
            if outline:
                parts.append(outline)
            if knowledge_points:
                for kp in knowledge_points:
                    parts.append(f"- {kp}")
            return "\n".join(parts)

    async def generate_ppt(
        self,
        topic: str,
        outline: Optional[str] = None,
        knowledge_points: Optional[List[str]] = None,
        template_id: Optional[str] = None,
        author: str = "AI智课",
        search: bool = False,
    ) -> PPTTaskResult:
        """
        完整的PPT生成流程：
        1. LLM扩展教学脚本
        2. 调用讯飞PPT API创建任务
        3. 轮询等待完成
        4. 下载PPT文件
        """
        # 步骤1: LLM扩展
        logger.info(f"[PPTGeneration] 步骤1: LLM扩展教学脚本, 主题={topic}")
        teaching_script = await self.expand_to_teaching_script(topic, outline, knowledge_points)

        # 步骤2: 创建PPT生成任务
        template_id = template_id or settings.XFYUN_PPT_DEFAULT_TEMPLATE_ID
        if not template_id:
            # 尝试获取免费模板
            try:
                theme_result = await TaskRunner().run(
                    TaskContext(
                        task_type=TaskType.PPT_GENERATION,
                        provider="xfyun_ppt",
                        input_summary="fetch free ppt theme",
                        metadata={"stage": "theme_list"},
                    ),
                    lambda: PPTAdapter(self.xfyun_client).get_theme_list(pay_type="free", page_size=1),
                )
                if not theme_result.success:
                    return PPTTaskResult(status="failed", error=theme_result.error_message or "Failed to fetch PPT themes")
                themes = theme_result.data
                if themes.get("data", {}).get("templateList"):
                    template_id = themes["data"]["templateList"][0]["id"]
                    logger.info(f"[PPTGeneration] 自动选择模板: {template_id}")
                else:
                    return PPTTaskResult(status="failed", error="未找到可用的PPT模板，请配置默认模板ID")
            except Exception as e:
                logger.warning(f"[PPTGeneration] 获取模板列表失败: {e}")
                return PPTTaskResult(status="failed", error=f"获取模板列表失败: {e}")

        logger.info(f"[PPTGeneration] 步骤2: 创建PPT生成任务, 模板={template_id}")
        try:
            create_adapter_result = await TaskRunner().run(
                TaskContext(
                    task_type=TaskType.PPT_GENERATION,
                    provider="xfyun_ppt",
                    input_summary=topic[:120],
                    metadata={"stage": "create_task", "template_id": template_id},
                ),
                lambda: PPTAdapter(self.xfyun_client).create_ppt_task(
                    query=teaching_script,
                    template_id=template_id,
                    author=author,
                    search=search,
                ),
            )
            if not create_adapter_result.success:
                return PPTTaskResult(status="failed", error=create_adapter_result.error_message or "Failed to create PPT task")
            create_result = create_adapter_result.data
        except Exception as e:
            logger.error(f"[PPTGeneration] 创建PPT任务失败: {e}")
            return PPTTaskResult(status="failed", error=f"创建PPT任务失败: {e}")

        if create_result.get("code") != 0:
            error_msg = create_result.get("message", "未知错误")
            logger.error(f"[PPTGeneration] 创建PPT任务返回错误: {error_msg}")
            return PPTTaskResult(status="failed", error=error_msg)

        sid = create_result.get("data", {}).get("sid", "")
        if not sid:
            return PPTTaskResult(status="failed", error="未获取到任务ID")

        logger.info(f"[PPTGeneration] 步骤3: 等待PPT生成完成, sid={sid}")

        # 步骤3: 轮询等待
        wait_adapter_result = await TaskRunner().run(
            TaskContext(
                task_id=sid,
                task_type=TaskType.PPT_GENERATION,
                provider="xfyun_ppt",
                input_summary=topic[:120],
                metadata={"stage": "wait_for_completion"},
            ),
            lambda: PPTAdapter(self.xfyun_client).wait_for_completion(sid),
        )
        if not wait_adapter_result.success:
            raw_task_result = wait_adapter_result.raw
            if isinstance(raw_task_result, PPTTaskResult):
                return raw_task_result
            return PPTTaskResult(sid=sid, status="failed", error=wait_adapter_result.error_message or "PPT generation failed")
        task_result = wait_adapter_result.data

        if task_result.status != "done":
            return task_result

        # 步骤4: 下载PPT
        if task_result.ppt_url:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_topic = "".join(c for c in topic if c.isalnum() or c in "._- ")[:30]
            filename = f"{safe_topic}_{timestamp}.pptx"
            save_path = os.path.join(self.ppt_storage_path, filename)

            logger.info(f"[PPTGeneration] 步骤4: 下载PPT文件 -> {save_path}")
            try:
                download_adapter_result = await TaskRunner().run(
                    TaskContext(
                        task_id=sid,
                        task_type=TaskType.PPT_GENERATION,
                        provider="xfyun_ppt",
                        input_summary=topic[:120],
                        metadata={"stage": "download", "save_path": save_path},
                    ),
                    lambda: PPTAdapter(self.xfyun_client).download_ppt(task_result.ppt_url, save_path),
                )
                if not download_adapter_result.success:
                    raise RuntimeError(download_adapter_result.error_message or "PPT download failed")
                task_result.ppt_file_path = download_adapter_result.data
            except Exception as e:
                logger.error(f"[PPTGeneration] 下载PPT失败: {e}")
                task_result.error = f"下载PPT失败: {e}"
                task_result.status = "failed"

        return task_result

    async def get_themes(
        self,
        pay_type: str = "free",
        style: Optional[str] = None,
        industry: Optional[str] = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取PPT模板列表"""
        return await self.xfyun_client.get_theme_list(
            pay_type=pay_type,
            style=style,
            industry=industry,
            page_num=page_num,
            page_size=page_size,
        )

    async def get_task_status(self, sid: str) -> Dict[str, Any]:
        """查询PPT生成任务进度"""
        return await self.xfyun_client.get_task_progress(sid)


ppt_generation_service = PPTGenerationService()
