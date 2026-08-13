"""豆包语音输入（ASR）端点：录音上传 → 转码 → 火山引擎录音文件识别标准版 → 转写文本。

挂载前缀：/api/v1/asr

流程：
1. POST /asr/transcribe  客户端 multipart 上传录音文件（webm/ogg/wav/mp3/mp4），
   服务端 ffmpeg 转码为 16kHz 单声道 wav，写入对象存储，签发带课程权限 scope 的
   签名 URL，再以 ASR_PUBLIC_BASE_URL 组装成火山引擎可访问的公网 URL 并提交
   submit，返回 task_id。
2. POST /asr/result      携带 task_id 轮询豆包 query；completed 后返回转写文本，
   并清理本次临时音频对象。

安全约束：
- 音频对象只通过 object_key 访问，不写入本地绝对路径；签名 URL scope 绑定
  course_id + purpose=asr_transcribe，豆包只能读取本次任务音频。
- API Key 只读自服务端配置，绝不进入响应、日志或前端。
- 未配置 ASR_PUBLIC_BASE_URL（本地 localhost 无法被火山引擎访问）时返回
  明确错误，不伪造转写成功。
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.common.media_tools import ffmpeg_binary
from app.core.config import settings
from app.core.security import get_current_user
from app.services.object_storage import get_object_storage
from app.services.volcengine_asr import (
    AsrQueryResult,
    VolcengineAsrError,
    asr_client,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# MediaRecorder 常见输出；mp4(aac) 仅 Safari，豆包不直接支持但可经 ffmpeg 转码。
_ALLOWED_MIMES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
}
_EXT_BY_MIME = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "mp4",
}


def _asr_object_key(user_id: int, task_id: str) -> str:
    return f"asr_audio/u{user_id}/{task_id}.wav"


def _public_audio_url(object_key: str, *, course_id: str) -> str:
    """把对象存储签名 URL 组装为火山引擎可访问的公网 URL。"""
    base = (settings.ASR_PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ASR_PUBLIC_BASE_URL_NOT_CONFIGURED",
                "message": "语音转写需要公网可访问的音频地址，请在后端配置 ASR_PUBLIC_BASE_URL（部署服务器的外部地址）后再试。",
            },
        )
    storage = get_object_storage()
    signed = storage.sign_read_url(
        object_key,
        expires_in=3600,
        scope={"course_id": str(course_id), "purpose": "asr_transcribe"},
    )
    return f"{base}{signed}"


def _resolve_ffmpeg() -> str:
    """解析 ffmpeg 路径：优先 settings.FFMPEG_PATH（本地覆盖），否则 PATH。"""
    configured = (settings.FFMPEG_PATH or "").strip()
    if configured and Path(configured).is_file():
        return configured
    return ffmpeg_binary()


def _transcode_to_wav(input_bytes: bytes, *, source_ext: str) -> bytes:
    """ffmpeg 转码为 16kHz 单声道 wav。ffmpeg 不可用时明确失败，不伪转码。"""
    ffmpeg = _resolve_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="asr_") as tmp:
        src = Path(tmp) / f"input.{source_ext}"
        dst = Path(tmp) / "output.wav"
        src.write_bytes(input_bytes)
        try:
            result = subprocess.run(
                [
                    ffmpeg, "-y", "-i", str(src),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(dst),
                ],
                capture_output=True,
                timeout=120,
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=503,
                detail={"code": "FFMPEG_UNAVAILABLE", "message": "服务器未安装 ffmpeg，无法转码录音，请先安装。"},
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(
                status_code=504,
                detail={"code": "ASR_TRANSCODE_TIMEOUT", "message": "音频转码超时，录音可能过长。"},
            )
        if result.returncode != 0 or not dst.exists():
            logger.warning("asr ffmpeg transcode failed: %s", result.stderr.decode("utf-8", "replace")[-500:])
            raise HTTPException(
                status_code=422,
                detail={"code": "ASR_TRANSCODE_FAILED", "message": "音频转码失败，请确认录音格式有效。"},
            )
        return dst.read_bytes()


class AsrResultRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=64)


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    course_id: str = Form(..., min_length=1, max_length=128),
    current_user: dict = Depends(get_current_user),
):
    """接收录音文件，提交豆包语音识别，返回 task_id。"""
    user_id = int(current_user["user_id"])

    mime = (file.content_type or "").lower()
    if mime not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=415,
            detail={"code": "ASR_UNSUPPORTED_FORMAT", "message": f"不支持的音频格式: {mime or 'unknown'}"},
        )

    raw = await file.read()
    max_bytes = settings.ASR_MAX_AUDIO_MB * 1024 * 1024
    if not raw:
        raise HTTPException(status_code=422, detail={"code": "ASR_EMPTY_AUDIO", "message": "录音内容为空"})
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={"code": "ASR_AUDIO_TOO_LARGE", "message": f"录音超过 {settings.ASR_MAX_AUDIO_MB}MB 上限"},
        )

    # 统一转码为 16kHz 单声道 wav（豆包标准版支持 wav）
    wav_bytes = _transcode_to_wav(raw, source_ext=_EXT_BY_MIME[mime])

    task_id = str(uuid.uuid4())
    object_key = _asr_object_key(user_id, task_id)
    storage = get_object_storage()
    try:
        storage.put(object_key, wav_bytes, mime_type="audio/wav")
        audio_url = _public_audio_url(object_key, course_id=course_id)
        result = asr_client.submit(audio_url, audio_format="wav", uid=f"u{user_id}", task_id=task_id)
    except VolcengineAsrError as exc:
        # 提交失败时清理已落盘的临时音频，避免残留
        _safe_delete(storage, object_key)
        raise HTTPException(
            status_code=503 if exc.retryable else 400,
            detail={"code": exc.error_code, "message": exc.safe_message},
        )
    except HTTPException:
        _safe_delete(storage, object_key)
        raise

    return {
        "code": 200,
        "message": "语音转写任务已提交",
        "data": {
            "task_id": result.task_id,
            "status": "submitted",
            "format": "wav",
        },
    }


@router.post("/result")
async def query_asr_result(
    payload: AsrResultRequest,
    current_user: dict = Depends(get_current_user),
):
    """轮询豆包转写结果。completed 返回文本并清理临时音频。"""
    user_id = int(current_user["user_id"])
    task_id = payload.task_id

    try:
        query_result: AsrQueryResult = asr_client.query(task_id)
    except VolcengineAsrError as exc:
        raise HTTPException(
            status_code=503 if exc.retryable else 400,
            detail={"code": exc.error_code, "message": exc.safe_message},
        )

    if query_result.status == "completed":
        # 转写完成，清理本次临时音频对象（失败不阻塞返回文本）
        _safe_delete(get_object_storage(), _asr_object_key(user_id, task_id))
        return {
            "code": 200,
            "message": "语音转写完成",
            "data": {"status": "completed", "text": query_result.text},
        }
    if query_result.status in {"processing", "queued"}:
        return {
            "code": 200,
            "message": "语音转写处理中",
            "data": {"status": query_result.status, "text": ""},
        }
    return {
        "code": 200,
        "message": query_result.error_message or "语音转写失败",
        "data": {
            "status": "failed",
            "error_code": query_result.error_code,
            "message": query_result.error_message,
        },
    }


def _safe_delete(storage, object_key: str) -> None:
    try:
        storage.delete(object_key)
    except Exception:
        logger.warning("asr temp object cleanup failed: %s", object_key, exc_info=True)
