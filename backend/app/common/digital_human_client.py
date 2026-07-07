"""
数字人视频生成客户端
调用本地Gradio数字人服务，将音频+人脸视频合成为数字人讲课视频

API文档: backend/docs/数字人合成api.md
核心端点: /process_video
  - 输入: audio_file(音频路径str), video_file(视频路径str), min_resolution, if_res, steps
  - 输出: (视频dict, 生成时间str, 下载文件dict)
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class DigitalHumanError(Exception):
    """数字人生成错误"""
    pass


@dataclass
class DigitalHumanResponse:
    """数字人生成响应"""
    video_path: str  # 生成的视频文件路径
    generation_time: str  # 生成耗时
    download_path: Optional[str] = None  # 下载文件路径


class DigitalHumanClient:
    """
    数字人视频生成客户端

    调用Gradio服务的 /process_video 端点，
    将TTS合成的音频 + 老师人脸视频 → 数字人讲课视频
    """

    def __init__(self):
        self.api_url = settings.DIGITAL_HUMAN_API_URL.rstrip("/")
        self.min_resolution = settings.DIGITAL_HUMAN_MIN_RESOLUTION
        self.if_res = settings.DIGITAL_HUMAN_IF_RES
        self.steps = settings.DIGITAL_HUMAN_STEPS
        self.timeout = 600  # 数字人生成可能较慢，10分钟超时

    async def generate_video(
        self,
        audio_path: str,
        video_path: str,
        min_resolution: Optional[int] = None,
        if_res: Optional[bool] = None,
        steps: Optional[int] = None,
    ) -> DigitalHumanResponse:
        """
        调用数字人API生成视频

        Args:
            audio_path: 音频文件路径（TTS合成输出）
            video_path: 人脸视频文件路径（老师素材）
            min_resolution: 原比例缩小倍数（默认使用配置值）
            if_res: 是否强制缩小分辨率（默认使用配置值）
            steps: 处理批次（默认使用配置值）

        Returns:
            DigitalHumanResponse 包含生成的视频路径

        Raises:
            DigitalHumanError: 生成失败时抛出
        """
        min_resolution = min_resolution or self.min_resolution
        if_res = if_res if if_res is not None else self.if_res
        steps = steps or self.steps

        # 校验输入文件存在
        if not os.path.isfile(audio_path):
            raise DigitalHumanError(f"音频文件不存在: {audio_path}")
        if not os.path.isfile(video_path):
            raise DigitalHumanError(f"人脸视频文件不存在: {video_path}")

        logger.info(f"[数字人] 开始生成: audio={audio_path}, video={video_path}")

        # 调用Gradio /process_video 端点
        # Gradio Client API: 通过HTTP POST调用
        url = f"{self.api_url}/call/process_video"

        payload = {
            "data": [
                audio_path,       # audio_file: str
                video_path,       # video_file: str
                min_resolution,   # min_resolution: float
                if_res,           # if_res: bool
                steps,            # steps: float
            ]
        }

        start_time = time.time()

        try:
            # Step 1: 提交任务，获取event_id
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                submit_response = await client.post(url, json=payload)
                submit_response.raise_for_status()
                submit_data = submit_response.json()
                event_id = submit_data.get("event_id")

                if not event_id:
                    raise DigitalHumanError(f"未获取到event_id，响应: {submit_data}")

                logger.info(f"[数字人] 任务已提交, event_id={event_id}")

                # Step 2: 轮询结果
                result_url = f"{self.api_url}/call/process_video/{event_id}"
                max_polls = 120  # 最多轮询120次，每次5秒，共10分钟
                poll_interval = 5

                for poll_idx in range(max_polls):
                    await asyncio_sleep(poll_interval)

                    result_response = await client.get(result_url)
                    result_response.raise_for_status()

                    # 解析SSE格式的响应
                    result_text = result_response.text
                    for line in result_text.split("\n"):
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            # 检查是否是最终结果
                            if isinstance(data, list) and len(data) >= 2:
                                # data[0] = 视频dict, data[1] = 生成时间str, data[2] = 下载文件dict
                                video_data = data[0] if len(data) > 0 else None
                                gen_time = data[1] if len(data) > 1 else ""
                                download_data = data[2] if len(data) > 2 else None

                                video_file_path = None
                                download_file_path = None

                                if isinstance(video_data, dict) and "video" in video_data:
                                    video_file_path = video_data["video"].get("path", "")
                                elif isinstance(video_data, dict):
                                    video_file_path = video_data.get("path", "")

                                if isinstance(download_data, dict):
                                    download_file_path = download_data.get("path", "")

                                if video_file_path:
                                    elapsed = time.time() - start_time
                                    logger.info(
                                        f"[数字人] 生成完成: {video_file_path}, "
                                        f"耗时={elapsed:.1f}s, 生成时间={gen_time}"
                                    )
                                    return DigitalHumanResponse(
                                        video_path=video_file_path,
                                        generation_time=gen_time,
                                        download_path=download_file_path,
                                    )

                            # 检查错误
                            if isinstance(data, dict) and "error" in data:
                                raise DigitalHumanError(f"数字人生成错误: {data['error']}")

                    logger.debug(f"[数字人] 轮询中... ({poll_idx + 1}/{max_polls})")

                raise DigitalHumanError(f"数字人生成超时（{max_polls * poll_interval}秒）")

        except httpx.TimeoutException:
            raise DigitalHumanError(f"数字人API请求超时 ({self.timeout}秒)")
        except httpx.HTTPStatusError as e:
            raise DigitalHumanError(f"数字人API请求失败: {e.response.status_code} - {e.response.text}")
        except DigitalHumanError:
            raise
        except Exception as e:
            raise DigitalHumanError(f"数字人API请求异常: {str(e)}")

    async def check_health(self) -> bool:
        """检查数字人服务是否可用"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.api_url}/info")
                return response.status_code == 200
        except Exception:
            return False


# 辅助函数
async def asyncio_sleep(seconds: float):
    """异步等待"""
    import asyncio
    await asyncio.sleep(seconds)


import json

# 单例
digital_human_client = DigitalHumanClient()
