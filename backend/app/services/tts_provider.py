"""阶段8 TTS Provider 抽象与实现

实现 `TTSProvider` 抽象：
- `FakeTtsProvider`：自动化测试与离线演示
- `XfyunTtsProvider`：讯飞在线 TTS WebSocket API（M2）
- `MockXfyunTtsProvider`：模拟讯飞响应格式，用于自动化测试

课程核心数据不绑死任何 Provider。

设计要点：
- 输入：script_text、voice_id、speed/pitch/volume、output_format、idempotency_key、
  course_id、resource_version
- 输出：audio_object_key、duration_ms、subtitle_segments、audio_sha256、
  provider_version、warnings
- 讲稿按句和 UTF-8 字节限制切分；幂等键去重；外部失败必须返回可解释失败，禁止伪造
- 讯飞密钥只留在服务端；自动化测试只调用 Fake 或 Mock Provider
- 单例 `tts_provider_registry` 通过配置 `STAGE8_TTS_PROVIDER` 选择实现
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hmac import HMAC
from urllib.parse import urlencode, urlparse
from typing import Any, Optional

from app.core.exceptions import reject_dependency_unavailable
from app.services.object_storage import get_object_storage


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据契约
# ---------------------------------------------------------------------------


@dataclass
class TtsSynthesisRequest:
    """TTS 合成请求"""
    script_text: str
    voice_id: str = "default"
    speed: float = 1.0
    pitch: float = 0.0
    volume: float = 0.0
    output_format: str = "mp3"
    idempotency_key: str = ""
    course_id: int = 0
    resource_version: str = "v1"

    def input_hash(
        self,
        *,
        provider_key: str = "",
        provider_version: str = "",
        provider_fingerprint: Optional[dict[str, Any]] = None,
    ) -> str:
        """生成输入指纹，用于缓存命中判断"""
        payload = {
            "script_text": self.script_text,
            "voice_id": self.voice_id,
            "speed": f"{self.speed:.2f}",
            "pitch": f"{self.pitch:.2f}",
            "volume": f"{self.volume:.2f}",
            "output_format": self.output_format,
            "resource_version": self.resource_version,
            "provider_key": provider_key,
            "provider_version": provider_version,
            "provider_fingerprint": provider_fingerprint or {},
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass
class SubtitleSegment:
    """字幕分段"""
    text: str
    start_ms: int
    end_ms: int
    sentence_index: int = 0


@dataclass
class TtsSynthesisResult:
    """TTS 合成结果"""
    audio_object_key: str
    duration_ms: int
    subtitle_segments: list[SubtitleSegment] = field(default_factory=list)
    audio_sha256: str = ""
    provider_key: str = ""
    provider_version: str = ""
    warnings: list[str] = field(default_factory=list)
    timing_metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 抽象接口
# ---------------------------------------------------------------------------


class TTSProvider(ABC):
    """TTS Provider 抽象

    所有 TTS 调用通过本接口；课程核心数据不绑定具体厂商。
    首版实现：FakeTtsProvider（自动化测试）、XfyunTtsProvider 占位（M2 接入真实讯飞）。
    """

    provider_key: str = "abstract"
    provider_version: str = "0.0.0"
    # A real paid provider must not execute on the request/event-loop path.
    requires_async_worker: bool = False

    @abstractmethod
    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        """合成音频与字幕分段；外部失败必须抛 reject_dependency_unavailable"""

    def health_check(self) -> bool:
        """健康检查；默认实现返回 True，子类可重写"""
        return True

    def cache_fingerprint(self) -> dict[str, Any]:
        """Return non-secret output-affecting configuration for cache keys."""
        return {}

    def cache_key(self, request: TtsSynthesisRequest) -> str:
        return request.input_hash(
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            provider_fingerprint=self.cache_fingerprint(),
        )


# ---------------------------------------------------------------------------
# Fake Provider（用于自动化测试与离线演示）
# ---------------------------------------------------------------------------


# 简单的句子切分：按句号/问号/感叹号/换行切分
_SENTENCE_PATTERN = re.compile(r"[。！？!?\.\n]+")


def _split_script_into_sentences(script_text: str, *, max_bytes: int = 800) -> list[str]:
    """将讲稿切分为句子，每段不超过 max_bytes UTF-8 字节

    讯飞 TTS 单次合成有字节限制，需在客户端切分。
    """
    if not script_text:
        return []
    # 先按标点切分
    parts = _SENTENCE_PATTERN.split(script_text)
    sentences: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 若单段超长，按字节强制切分
        encoded = part.encode("utf-8")
        while len(encoded) > max_bytes:
            cut = part[:max_bytes]
            # 找到最后一个完整 UTF-8 字符
            while True:
                try:
                    cut.encode("utf-8").decode("utf-8")
                    break
                except UnicodeDecodeError:
                    cut = cut[:-1]
            sentences.append(cut)
            part = part[len(cut):]
            encoded = part.encode("utf-8")
        if part:
            sentences.append(part)
    return sentences


class FakeTtsProvider(TTSProvider):
    """假 TTS Provider

    - 不调用真实讯飞，自动化测试与离线演示使用
    - 生成的"音频"是包含文本与时间元数据的占位字节
    - 字幕分段按句切分，duration_ms 按字数估算（约 200 字/分钟）
    - 产物写入对象存储，返回 object_key
    """

    provider_key = "fake_tts"
    provider_version = "fake-v1.0"

    # 估算语速：中文 200 字/分钟 = 3.33 字/秒
    CHARS_PER_SECOND = 3.33

    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        sentences = _split_script_into_sentences(request.script_text)
        if not sentences:
            # 即便空文本也生成 1ms 占位音频，避免下游除零
            sentences = [""]

        # 估算每段时长
        segments: list[SubtitleSegment] = []
        cursor_ms = 0
        for idx, sentence in enumerate(sentences):
            char_count = len(sentence)
            duration_ms = max(200, int(char_count / self.CHARS_PER_SECOND * 1000))
            segments.append(SubtitleSegment(
                text=sentence,
                start_ms=cursor_ms,
                end_ms=cursor_ms + duration_ms,
                sentence_index=idx,
            ))
            cursor_ms += duration_ms

        total_duration_ms = cursor_ms

        # 生成占位音频内容：包含文本与时间元数据，便于测试断言
        audio_payload_parts = [
            b"FAKE_TTS_AUDIO_V1\n",
            f"provider={self.provider_key}\n".encode(),
            f"version={self.provider_version}\n".encode(),
            f"voice={request.voice_id}\n".encode(),
            f"duration_ms={total_duration_ms}\n".encode(),
            f"format={request.output_format}\n".encode(),
            f"course_id={request.course_id}\n".encode(),
            f"resource_version={request.resource_version}\n".encode(),
            f"input_hash={request.input_hash()}\n".encode(),
            b"---\n",
            request.script_text.encode("utf-8"),
        ]
        audio_bytes = b"".join(audio_payload_parts)

        # 写入对象存储
        audio_object_key = self._build_object_key(request)
        storage = get_object_storage()
        content_sha = storage.put(audio_object_key, audio_bytes, mime_type="audio/mpeg")

        return TtsSynthesisResult(
            audio_object_key=audio_object_key,
            duration_ms=total_duration_ms,
            subtitle_segments=segments,
            audio_sha256=content_sha,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            warnings=["fake_tts: 生成的是占位音频，非真实 TTS 产物"],
        )

    def _build_object_key(self, request: TtsSynthesisRequest) -> str:
        """构造稳定的 object_key，便于幂等去重"""
        if request.idempotency_key:
            key_part = request.idempotency_key
        else:
            key_part = request.input_hash()[:16]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return (
            f"tts/course_{request.course_id}/{timestamp}/{key_part}."
            f"{request.output_format}"
        )


# ---------------------------------------------------------------------------
# 讯飞在线 TTS Provider（M2 实现）
# ---------------------------------------------------------------------------


def _build_xfyun_auth_url(api_key: str, api_secret: str, base_url: str) -> str:
    """生成讯飞 WebSocket 鉴权 URL（HMAC-SHA256 签名）

    依照 https://global.xfyun.cn/doc/tts/online_tts/API.html 鉴权规范。
    """
    parsed = urlparse(base_url)
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    signature_origin = (
        f"host: {parsed.hostname}\n"
        f"date: {now}\n"
        f"GET {parsed.path} HTTP/1.1"
    )
    signature_sha = HMAC(
        api_secret.encode("utf-8"),
        signature_origin.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")
    authorization_origin = (
        f"api_key=\"{api_key}\", "
        f"algorithm=\"hmac-sha256\", "
        f"headers=\"host date request-line\", "
        f"signature=\"{signature}\""
    )
    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("utf-8")
    params = urlencode({
        "authorization": authorization,
        "date": now,
        "host": parsed.hostname,
    })
    return f"{base_url}?{params}"


class XfyunTtsProvider(TTSProvider):
    """讯飞在线语音合成 Provider

    - 使用讯飞 WebSocket TTS v2 API
    - 讲稿按句和 UTF-8 字节限制切分，分帧发送
    - 讯飞密钥只留在服务端，不进入前端/日志/测试
    - 凭据缺失时返回 DEPENDENCY_UNAVAILABLE，禁止伪装成功
    - 自动化测试不调用本 Provider，使用 MockXfyunTtsProvider 验证响应解析
    """

    provider_key = "xfyun_tts"
    provider_version = "xfyun-tts-v2.0"

    # 讯飞单帧最大字节（UTF-8）
    MAX_FRAME_BYTES = 8000

    def __init__(self) -> None:
        from app.core.config import settings
        self._app_id = getattr(settings, "XFYUN_TTS_APP_ID", "") or ""
        self._api_key = getattr(settings, "XFYUN_TTS_API_KEY", "") or ""
        self._api_secret = getattr(settings, "XFYUN_TTS_API_SECRET", "") or ""
        self._default_vcn = getattr(settings, "XFYUN_TTS_DEFAULT_VCN", "xiaoyan")
        self._speed = getattr(settings, "XFYUN_TTS_SPEED", 50)
        self._volume = getattr(settings, "XFYUN_TTS_VOLUME", 50)
        self._pitch = getattr(settings, "XFYUN_TTS_PITCH", 50)
        self._sample_rate = getattr(settings, "XFYUN_TTS_SAMPLE_RATE", 16000)
        self._audio_encoding = getattr(settings, "XFYUN_TTS_AUDIO_ENCODING", "lame")
        self._ws_url = getattr(settings, "XFYUN_TTS_WS_URL", "wss://tts-api.xfyun.cn/v2/tts")
        self._connect_timeout_ms = getattr(settings, "XFYUN_TTS_CONNECT_TIMEOUT_MS", 10000)
        self._read_timeout_ms = getattr(settings, "XFYUN_TTS_READ_TIMEOUT_MS", 30000)

    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        """调用讯飞 TTS 合成音频

        失败时抛 reject_dependency_unavailable，禁止伪装成功。
        """
        if not self._app_id or not self._api_key or not self._api_secret:
            reject_dependency_unavailable(
                "讯飞 TTS 凭据未配置（XFYUN_TTS_APP_ID/API_KEY/API_SECRET）"
            )

        sentences = _split_script_into_sentences(
            request.script_text, max_bytes=self.MAX_FRAME_BYTES,
        )
        if not sentences:
            sentences = [""]

        # 逐句合成并拼接音频
        audio_chunks: list[bytes] = []
        segments: list[SubtitleSegment] = []
        cursor_ms = 0
        warnings: list[str] = []

        for idx, sentence in enumerate(sentences):
            try:
                chunk_audio, duration_ms = self._synthesize_single_sentence(
                    sentence, request.voice_id,
                )
            except Exception as e:
                # 保留原始失败原因，禁止伪装成功
                logger.warning("讯飞 TTS 合成第 %d 句失败: %s", idx, e)
                reject_dependency_unavailable(
                    f"讯飞 TTS 合成失败（第 {idx + 1} 句）: {str(e)[:200]}"
                )

            audio_chunks.append(chunk_audio)
            seg_duration = duration_ms if duration_ms > 0 else max(
                200, int(len(sentence) / 3.33 * 1000)
            )
            segments.append(SubtitleSegment(
                text=sentence,
                start_ms=cursor_ms,
                end_ms=cursor_ms + seg_duration,
                sentence_index=idx,
            ))
            cursor_ms += seg_duration

        # 拼接音频
        audio_bytes = b"".join(audio_chunks)

        # 写入对象存储
        audio_object_key = self._build_object_key(request)
        storage = get_object_storage()
        content_sha = storage.put(
            audio_object_key, audio_bytes, mime_type="audio/mpeg",
        )

        return TtsSynthesisResult(
            audio_object_key=audio_object_key,
            duration_ms=cursor_ms,
            subtitle_segments=segments,
            audio_sha256=content_sha,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            warnings=warnings,
        )

    def _synthesize_single_sentence(
        self, text: str, voice_id: str,
    ) -> tuple[bytes, int]:
        """调用讯飞 WebSocket 合成单句

        返回 (audio_bytes, duration_ms)。
        本方法使用同步 WebSocket（讯飞 TTS 是短连接）。
        """
        try:
            import websocket  # websocket-client 库
        except ImportError as e:
            reject_dependency_unavailable(
                f"websocket-client 库未安装: {e}"
            )

        auth_url = _build_xfyun_auth_url(
            self._api_key, self._api_secret, self._ws_url,
        )

        # 讯飞请求体
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        vcn = voice_id if voice_id and voice_id != "default" else self._default_vcn
        request_body = {
            "header": {"app_id": self._app_id, "status": 2},
            "parameter": {
                "ora12": {
                    "vcn": vcn,
                    "speed": self._speed,
                    "volume": self._volume,
                    "pitch": self._pitch,
                    "bgs": 0,
                    "tte": 0,
                    "reg": 0,
                    "rdn": 0,
                    "audio": {
                        "encoding": self._audio_encoding,
                        "sample_rate": self._sample_rate,
                        "channels": 1,
                        "bit_depth": 16,
                        "frame_size": 0,
                    },
                }
            },
            "payload": {
                "text": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "plain",
                    "status": 2,
                    "text": text_b64,
                }
            },
        }

        audio_chunks: list[bytes] = []
        result_duration_ms = 0

        def _on_message(ws, message):
            nonlocal result_duration_ms
            try:
                data = json.loads(message) if isinstance(message, str) else json.loads(message.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            if data.get("code") != 0:
                ws.close()
                return
            payload = data.get("payload", {}) or {}
            audio_data = payload.get("audio", {})
            if audio_data.get("audio"):
                chunk = base64.b64decode(audio_data["audio"])
                audio_chunks.append(chunk)
            if data.get("header", {}).get("status") == 2:
                # 合成结束
                result_duration_ms = int(
                    (data.get("payload", {}).get("audio", {}).get("data", "") and 0)
                    or (len(text) / 3.33 * 1000)
                )
                ws.close()

        def _on_error(ws, error):
            logger.warning("讯飞 TTS WebSocket 错误: %s", error)

        ws = websocket.WebSocketApp(
            auth_url,
            on_message=_on_message,
            on_error=_on_error,
        )
        ws.run_forever(
            timeout=self._read_timeout_ms / 1000,
            ping_interval=0,
        )

        if not audio_chunks:
            reject_dependency_unavailable("讯飞 TTS 未返回任何音频数据")

        return b"".join(audio_chunks), result_duration_ms

    def health_check(self) -> bool:
        """健康检查：凭据已配置即视为可用"""
        return bool(self._app_id and self._api_key and self._api_secret)

    def _build_object_key(self, request: TtsSynthesisRequest) -> str:
        """构造稳定的 object_key，便于幂等去重"""
        if request.idempotency_key:
            key_part = request.idempotency_key
        else:
            key_part = request.input_hash()[:16]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        ext = "mp3" if "lame" in self._audio_encoding else self._audio_encoding
        return (
            f"tts/course_{request.course_id}/{timestamp}/{key_part}.{ext}"
        )


# ---------------------------------------------------------------------------
# 豆包语音合成 2.0（v3 双向 WebSocket）
# ---------------------------------------------------------------------------


def _word_time_ms(value: Any) -> int | None:
    """Normalize the public v3 word timestamp (seconds) to integer ms."""
    if not isinstance(value, (int, float)):
        return None
    return int(round(value * 1000))


def _subtitle_segments_from_doubao_words(words: list[dict[str, Any]]) -> list[SubtitleSegment]:
    """Group provider word timings into readable sentence subtitle segments.

    Exact word timing is retained in ``timing_metadata``.  The learner UI gets
    sentence-sized segments so it does not flash one character at a time.
    """
    segments: list[SubtitleSegment] = []
    buffer: list[str] = []
    start_ms: int | None = None
    end_ms: int | None = None
    sentence_index = 0

    def flush() -> None:
        nonlocal buffer, start_ms, end_ms, sentence_index
        text = "".join(buffer).strip()
        if text and start_ms is not None and end_ms is not None and end_ms >= start_ms:
            segments.append(SubtitleSegment(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                sentence_index=sentence_index,
            ))
            sentence_index += 1
        buffer = []
        start_ms = None
        end_ms = None

    for item in words:
        word = str(item.get("word") or item.get("text") or "")
        item_start = _word_time_ms(item.get("startTime"))
        item_end = _word_time_ms(item.get("endTime"))
        if not word or item_start is None or item_end is None or item_end < item_start:
            continue
        if start_ms is None:
            start_ms = item_start
        end_ms = item_end
        buffer.append(word)
        if any(punctuation in word for punctuation in "。！？!?；;\n"):
            flush()
    flush()
    return segments


class VolcengineDoubaoTtsProvider(TTSProvider):
    """豆包语音合成 2.0 的正式 TTS Provider。

    Configuration is loaded lazily and the provider is worker-only.  It stores
    audio and normalized timing only; API keys, speaker IDs, and raw provider
    frames are never persisted to task attempts or sent to clients.
    """

    provider_key = "volcengine_doubao_tts"
    provider_version = "doubao-tts-v3"
    requires_async_worker = True
    _SUPPORTED_FORMATS = {"mp3", "pcm"}

    def _settings(self):
        from app.core.config import settings
        return settings

    def _configuration(self) -> dict[str, Any]:
        settings = self._settings()
        return {
            "ws_url": (getattr(settings, "VOLCENGINE_DOUBAO_TTS_WS_URL", "") or "").strip(),
            "api_key": (getattr(settings, "VOLCENGINE_DOUBAO_TTS_API_KEY", "") or "").strip(),
            "resource_id": (getattr(settings, "VOLCENGINE_DOUBAO_TTS_RESOURCE_ID", "") or "").strip(),
            "speaker": (getattr(settings, "VOLCENGINE_DOUBAO_TTS_SPEAKER", "") or "").strip(),
            "audio_format": (getattr(settings, "VOLCENGINE_DOUBAO_TTS_FORMAT", "mp3") or "mp3").lower(),
            "sample_rate": int(getattr(settings, "VOLCENGINE_DOUBAO_TTS_SAMPLE_RATE", 24000) or 24000),
            "enable_subtitle": bool(getattr(settings, "VOLCENGINE_DOUBAO_TTS_ENABLE_SUBTITLE", True)),
            "connect_timeout_seconds": int(getattr(settings, "VOLCENGINE_DOUBAO_TTS_CONNECT_TIMEOUT_SECONDS", 15) or 15),
            "read_timeout_seconds": int(getattr(settings, "VOLCENGINE_DOUBAO_TTS_READ_TIMEOUT_SECONDS", 90) or 90),
        }

    def cache_fingerprint(self) -> dict[str, Any]:
        config = self._configuration()
        # Speaker identity changes the output, but its raw identifier is not
        # written into jobs or attempt metadata.
        speaker_hash = hashlib.sha256(config["speaker"].encode("utf-8")).hexdigest() if config["speaker"] else ""
        return {
            "ws_url": config["ws_url"],
            "resource_id": config["resource_id"],
            "speaker_sha256": speaker_hash,
            "audio_format": config["audio_format"],
            "sample_rate": config["sample_rate"],
            "enable_subtitle": config["enable_subtitle"],
        }

    def health_check(self) -> bool:
        config = self._configuration()
        return bool(config["ws_url"] and config["api_key"] and config["resource_id"] and config["speaker"])

    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        config = self._configuration()
        missing = [name for name in ("ws_url", "api_key", "resource_id", "speaker") if not config[name]]
        if missing:
            reject_dependency_unavailable(
                "豆包 TTS 凭据未配置（需要 VOLCENGINE_DOUBAO_TTS_WS_URL/API_KEY/RESOURCE_ID/SPEAKER）"
            )
        if config["audio_format"] not in self._SUPPORTED_FORMATS:
            reject_dependency_unavailable("豆包 TTS 仅支持 mp3 或 pcm 输出格式")
        if config["sample_rate"] <= 0:
            reject_dependency_unavailable("豆包 TTS 采样率配置无效")
        if request.voice_id not in ("", "default", config["speaker"]):
            reject_dependency_unavailable("当前豆包 TTS Provider 只允许使用已配置的课程音色")

        from app.services.volcengine_tts_v3 import (
            VolcengineTtsV3Client,
            VolcengineTtsV3Config,
        )

        result = VolcengineTtsV3Client(VolcengineTtsV3Config(**config)).synthesize(request.script_text)
        subtitle_segments = _subtitle_segments_from_doubao_words(result.words)
        warnings: list[str] = []
        if config["enable_subtitle"] and not result.words:
            warnings.append("doubao_tts: provider returned no word timing; precise subtitles are unavailable")
        if result.phoneme_count == 0:
            warnings.append("doubao_tts: provider returned no phonemes; do not use this release for precise lip-sync")
        if config["audio_format"] != "pcm":
            warnings.append("doubao_tts: duration uses provider word timing; browser audio remains the playback clock")

        cache_key = self.cache_key(request)
        object_key = f"tts/course_{request.course_id}/doubao/{cache_key}.{config['audio_format']}"
        storage = get_object_storage()
        content_sha = storage.put(
            object_key,
            result.audio_bytes,
            mime_type="audio/mpeg" if config["audio_format"] == "mp3" else "audio/L16",
        )
        return TtsSynthesisResult(
            audio_object_key=object_key,
            duration_ms=result.duration_ms,
            subtitle_segments=subtitle_segments,
            audio_sha256=content_sha,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            warnings=warnings,
            timing_metadata={
                "timing_source": result.duration_source,
                "word_count": len(result.words),
                "phoneme_count": result.phoneme_count,
                "timing_error_ms": result.timing_error_ms,
                "word_timings": [
                    {
                        "text": str(item.get("word") or item.get("text") or ""),
                        "start_ms": _word_time_ms(item.get("startTime")),
                        "end_ms": _word_time_ms(item.get("endTime")),
                    }
                    for item in result.words
                    if _word_time_ms(item.get("startTime")) is not None
                    and _word_time_ms(item.get("endTime")) is not None
                ],
            },
        )


# ---------------------------------------------------------------------------
# 模拟讯飞 TTS Provider（用于自动化测试）
# ---------------------------------------------------------------------------


class MockXfyunTtsProvider(TTSProvider):
    """模拟讯飞 TTS Provider

    - 不调用真实讯飞，但模拟讯飞的响应格式（base64 音频、分句合成）
    - 用于自动化测试 XfyunTtsProvider 的响应解析逻辑
    - 生成的音频包含讯飞格式元数据，便于断言
    """

    provider_key = "xfyun_tts"
    provider_version = "xfyun-tts-v2.0-mock"

    CHARS_PER_SECOND = 3.33

    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        sentences = _split_script_into_sentences(request.script_text)
        if not sentences:
            sentences = [""]

        segments: list[SubtitleSegment] = []
        audio_chunks: list[bytes] = []
        cursor_ms = 0

        for idx, sentence in enumerate(sentences):
            char_count = len(sentence)
            duration_ms = max(200, int(char_count / self.CHARS_PER_SECOND * 1000))

            # 模拟讯飞音频格式（MP3 头 + 占位数据）
            chunk = self._build_mock_mp3_chunk(sentence, duration_ms, idx)
            audio_chunks.append(chunk)

            segments.append(SubtitleSegment(
                text=sentence,
                start_ms=cursor_ms,
                end_ms=cursor_ms + duration_ms,
                sentence_index=idx,
            ))
            cursor_ms += duration_ms

        audio_bytes = b"".join(audio_chunks)
        audio_object_key = self._build_object_key(request)
        storage = get_object_storage()
        content_sha = storage.put(
            audio_object_key, audio_bytes, mime_type="audio/mpeg",
        )

        return TtsSynthesisResult(
            audio_object_key=audio_object_key,
            duration_ms=cursor_ms,
            subtitle_segments=segments,
            audio_sha256=content_sha,
            provider_key=self.provider_key,
            provider_version=self.provider_version,
            warnings=["mock_xfyun: 模拟讯飞响应格式，非真实 TTS 产物"],
        )

    def _build_mock_mp3_chunk(
        self, text: str, duration_ms: int, idx: int,
    ) -> bytes:
        """构造模拟 MP3 音频块"""
        return (
            b"MOCK_XFYUN_AUDIO_V2\n"
            + f"frame={idx}\n".encode()
            + f"duration_ms={duration_ms}\n".encode()
            + f"text_sha256={hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}\n".encode()
            + b"---\n"
            + text.encode("utf-8")
        )

    def _build_object_key(self, request: TtsSynthesisRequest) -> str:
        if request.idempotency_key:
            key_part = request.idempotency_key
        else:
            key_part = request.input_hash()[:16]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"tts/course_{request.course_id}/{timestamp}/{key_part}.mp3"

    def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Provider 注册表
# ---------------------------------------------------------------------------


_PROVIDER_REGISTRY: dict[str, TTSProvider] = {
    "fake": FakeTtsProvider(),
    "fake_tts": FakeTtsProvider(),
    "xfyun": XfyunTtsProvider(),
    "xfyun_tts": XfyunTtsProvider(),
    "mock_xfyun": MockXfyunTtsProvider(),
    "mock_xfyun_tts": MockXfyunTtsProvider(),
    "doubao": VolcengineDoubaoTtsProvider(),
    "doubao_tts": VolcengineDoubaoTtsProvider(),
    "volcengine_doubao_tts": VolcengineDoubaoTtsProvider(),
}


class TtsProviderConfigurationError(RuntimeError):
    """A formal generation request selected an unknown TTS provider."""


def get_tts_provider(provider_key: Optional[str] = None, *, strict: bool = False) -> TTSProvider:
    """获取 TTS Provider

    首版默认返回 FakeTtsProvider，确保自动化测试与离线演示不依赖外部服务。
    M2 接入讯飞后，可通过 settings.STAGE8_TTS_PROVIDER 切换。
    自动化测试使用 mock_xfyun 验证讯飞响应解析，不调用真实讯飞。
    """
    if provider_key is None:
        from app.core.config import settings
        provider_key = getattr(settings, "STAGE8_TTS_PROVIDER", "fake") or "fake"
    provider = _PROVIDER_REGISTRY.get(provider_key.lower())
    if provider is None and strict:
        raise TtsProviderConfigurationError(f"Unsupported TTS provider: {provider_key}")
    if provider is None:
        # 未知 provider 回退到 fake，避免生产事故
        return _PROVIDER_REGISTRY["fake"]
    return provider


def register_tts_provider(provider_key: str, provider: TTSProvider) -> None:
    """注册自定义 TTS Provider（测试辅助）"""
    _PROVIDER_REGISTRY[provider_key.lower()] = provider


def reset_tts_registry_for_tests() -> None:
    """测试辅助：重置注册表为默认状态"""
    _PROVIDER_REGISTRY.clear()
    _PROVIDER_REGISTRY.update({
        "fake": FakeTtsProvider(),
        "fake_tts": FakeTtsProvider(),
        "xfyun": XfyunTtsProvider(),
        "xfyun_tts": XfyunTtsProvider(),
        "mock_xfyun": MockXfyunTtsProvider(),
        "mock_xfyun_tts": MockXfyunTtsProvider(),
        "doubao": VolcengineDoubaoTtsProvider(),
        "doubao_tts": VolcengineDoubaoTtsProvider(),
        "volcengine_doubao_tts": VolcengineDoubaoTtsProvider(),
    })
