"""Minimal client for the Doubao/Volcengine ASR (speech-to-text) v3 HTTP protocol.

This module deliberately owns only the provider wire protocol (录音文件识别标准版
HTTP: submit + query 两段式).  It does not know about courses, object storage,
uploads or HTTP requests — the endpoint layer is responsible for producing a
publicly reachable audio URL and for cleaning up temporary objects.

流程:
1. submit(audio_url): POST /api/v3/auc/bigmodel/submit，返回任务 ID。
2. query(task_id): POST /api/v3/auc/bigmodel/query，轮询转写状态与文本。

状态码（响应头 X-Api-Status-Code）：
- 20000000 成功（body.result.text 为转写文本）
- 20000001 / 20000002 处理中 / 队列中
- 20000003 静音音频（未检测到人声）
- 4xxxxxxx / 5xxxxxxx 参数或服务错误

The client is synchronous; call it from a FastAPI request handler is fine
because each submit/query is a short independent HTTP request.  API Key never
enters logs; ``VolcengineAsrError.safe_message`` never includes the key, the
audio URL or the transcribed text.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 响应头状态码
ASR_STATUS_OK = "20000000"
ASR_STATUS_PROCESSING = "20000001"
ASR_STATUS_QUEUED = "20000002"
ASR_STATUS_SILENT_AUDIO = "20000003"

_DEFAULT_RESOURCE_ID = "volc.seedasr.auc"
_DEFAULT_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
_DEFAULT_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"


class VolcengineAsrError(RuntimeError):
    """A safe, structured provider failure.

    ``safe_message`` intentionally never includes the API key, the audio URL or
    the transcribed text, so it can be surfaced to the caller / logs directly.
    """

    def __init__(self, error_code: str, safe_message: str, *, retryable: bool = True):
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message
        self.retryable = retryable


@dataclass(frozen=True)
class AsrSubmitResult:
    task_id: str


@dataclass(frozen=True)
class AsrQueryResult:
    status: str  # completed | processing | queued | failed
    text: str = ""
    error_code: str = ""
    error_message: str = ""


def _is_retryable(status_code: str | None) -> bool:
    if not status_code:
        return True
    if status_code.isdigit() and int(status_code) >= 55000000:
        return True  # 服务端内部错误（含 55000031 服务器繁忙）
    return False


class VolcengineAsrClient:
    """豆包语音识别（录音文件识别标准版）HTTP 客户端。"""

    def __init__(self) -> None:
        self.api_key = (settings.VOLCENGINE_ASR_API_KEY or "").strip()
        self.resource_id = settings.VOLCENGINE_ASR_RESOURCE_ID or _DEFAULT_RESOURCE_ID
        self.submit_url = settings.VOLCENGINE_ASR_SUBMIT_URL or _DEFAULT_SUBMIT_URL
        self.query_url = settings.VOLCENGINE_ASR_QUERY_URL or _DEFAULT_QUERY_URL
        self.timeout = settings.ASR_HTTP_TIMEOUT_SECONDS or 60
        self._enabled = bool(self.api_key)

    def replace_from_config(self, *, api_key: str, resource_id: str = "", submit_url: str = "", query_url: str = "", timeout: int | None = None) -> None:
        """管理员刷新真实 ASR 配置（不触发任何网络调用）。"""
        self.api_key = (api_key or "").strip()
        self.resource_id = resource_id or _DEFAULT_RESOURCE_ID
        self.submit_url = submit_url or _DEFAULT_SUBMIT_URL
        self.query_url = query_url or _DEFAULT_QUERY_URL
        if timeout:
            self.timeout = int(timeout)

    def set_enabled(self, enabled: bool) -> None:
        """管理员开关：false 时 submit/query 一律 fail-closed，不静默降级。"""
        self._enabled = bool(enabled)

    # ------------------------------------------------------------------
    # 公共边界
    # ------------------------------------------------------------------

    def submit(self, audio_url: str, *, audio_format: str = "wav", uid: str = "ai-course-system", task_id: str | None = None) -> AsrSubmitResult:
        """提交音频转写任务。task_id 可复用调用方生成的 UUID（用于对象清理）。"""
        self._require_enabled()
        task_id = task_id or str(uuid.uuid4())
        payload = {
            "user": {"uid": uid},
            "audio": {
                "url": audio_url,
                "format": audio_format,
                # 语音输入场景开启标点与文本规范化，让转写结果可直接作为提问。
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
            },
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.submit_url,
                    json=payload,
                    headers=self._headers(task_id),
                )
        except httpx.TimeoutException:
            raise VolcengineAsrError("ASR_SUBMIT_TIMEOUT", "豆包语音识别提交超时", retryable=True)
        except httpx.HTTPError as exc:
            raise VolcengineAsrError("ASR_SUBMIT_NETWORK_ERROR", f"豆包语音识别提交网络错误: {type(exc).__name__}", retryable=True)

        status_code = response.headers.get("X-Api-Status-Code", "")
        message = response.headers.get("X-Api-Message", "") or ""
        if status_code != ASR_STATUS_OK:
            logger.warning("asr submit failed: status=%s message=%s", status_code, message)
            raise VolcengineAsrError(
                status_code or "ASR_SUBMIT_FAILED",
                f"豆包语音识别提交失败: {message or status_code}",
                retryable=_is_retryable(status_code),
            )
        return AsrSubmitResult(task_id=task_id)

    def query(self, task_id: str) -> AsrQueryResult:
        """查询任务状态。调用方负责轮询直至 completed / failed。"""
        self._require_enabled()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.query_url,
                    json={},
                    headers=self._headers(task_id),
                )
        except httpx.TimeoutException:
            raise VolcengineAsrError("ASR_QUERY_TIMEOUT", "豆包语音识别查询超时", retryable=True)
        except httpx.HTTPError as exc:
            raise VolcengineAsrError("ASR_QUERY_NETWORK_ERROR", f"豆包语音识别查询网络错误: {type(exc).__name__}", retryable=True)

        status_code = response.headers.get("X-Api-Status-Code", "")
        message = response.headers.get("X-Api-Message", "") or ""
        if status_code == ASR_STATUS_OK:
            text = ""
            try:
                data = response.json()
                text = ((data.get("result") or {}).get("text")) or ""
            except Exception:
                logger.exception("asr query ok but body unparsable")
            return AsrQueryResult(status="completed", text=text)
        if status_code == ASR_STATUS_PROCESSING:
            return AsrQueryResult(status="processing")
        if status_code == ASR_STATUS_QUEUED:
            return AsrQueryResult(status="queued")
        if status_code == ASR_STATUS_SILENT_AUDIO:
            return AsrQueryResult(status="failed", error_code=status_code, error_message="未检测到人声（静音音频）")
        logger.warning("asr query failed: status=%s message=%s", status_code, message)
        raise VolcengineAsrError(
            status_code or "ASR_QUERY_FAILED",
            f"豆包语音识别查询失败: {message or status_code}",
            retryable=_is_retryable(status_code),
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _require_enabled(self) -> None:
        """Fail closed when the administrator disabled the real ASR provider."""
        if not self._enabled:
            raise VolcengineAsrError(
                "ASR_DISABLED",
                "语音识别已被管理员关闭，请先在后端开启真实接入",
                retryable=False,
            )

    def _headers(self, task_id: str) -> dict[str, str]:
        if not self.api_key:
            raise VolcengineAsrError(
                "ASR_NOT_CONFIGURED",
                "豆包语音识别未配置 VOLCENGINE_ASR_API_KEY",
                retryable=False,
            )
        return {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": "-1",
        }


asr_client = VolcengineAsrClient()
