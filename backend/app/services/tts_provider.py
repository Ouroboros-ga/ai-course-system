"""阶段8 TTS Provider 抽象与实现

实现 `TTSProvider` 抽象，首版提供 `FakeTtsProvider`（用于自动化测试与离线演示）
和 `XfyunTtsProvider` 占位（M2 接入真实讯飞）。课程核心数据不绑死任何 Provider。

设计要点：
- 输入：script_text、voice_id、speed/pitch/volume、output_format、idempotency_key、
  course_id、resource_version
- 输出：audio_object_key、duration_ms、subtitle_segments、audio_sha256、
  provider_version、warnings
- 讲稿按句和 UTF-8 字节限制切分；幂等键去重；外部失败必须返回可解释失败，禁止伪造
- 讯飞密钥只留在服务端；自动化测试只调用 Fake Provider
- 单例 `tts_provider_registry` 通过配置 `TTS_PROVIDER` 选择实现
"""
from __future__ import annotations

import hashlib
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.exceptions import reject_dependency_unavailable
from app.services.object_storage import get_object_storage


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

    def input_hash(self) -> str:
        """生成输入指纹，用于缓存命中判断"""
        payload = "|".join([
            self.script_text,
            self.voice_id,
            f"{self.speed:.2f}",
            f"{self.pitch:.2f}",
            f"{self.volume:.2f}",
            self.output_format,
            self.resource_version,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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

    @abstractmethod
    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        """合成音频与字幕分段；外部失败必须抛 reject_dependency_unavailable"""

    def health_check(self) -> bool:
        """健康检查；默认实现返回 True，子类可重写"""
        return True


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
# 讯飞 TTS 占位（M2 接入真实 API）
# ---------------------------------------------------------------------------


class XfyunTtsProvider(TTSProvider):
    """讯飞在线 TTS Provider（M2 实现）

    首版仅为占位：调用时直接返回 DEPENDENCY_UNAVAILABLE，
    避免在 M1 阶段误用真实讯飞凭据。
    """

    provider_key = "xfyun_tts"
    provider_version = "xfyun-tts-v1.0"

    def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResult:
        # M2 将实现真实讯飞调用
        reject_dependency_unavailable(
            "讯飞 TTS 尚未接入（M2 任务），请使用 FakeTtsProvider 完成端到端测试"
        )

    def health_check(self) -> bool:
        # M2 接入后返回真实健康状态
        return False


# ---------------------------------------------------------------------------
# Provider 注册表
# ---------------------------------------------------------------------------


_PROVIDER_REGISTRY: dict[str, TTSProvider] = {
    "fake": FakeTtsProvider(),
    "fake_tts": FakeTtsProvider(),
    "xfyun": XfyunTtsProvider(),
    "xfyun_tts": XfyunTtsProvider(),
}


def get_tts_provider(provider_key: Optional[str] = None) -> TTSProvider:
    """获取 TTS Provider

    首版默认返回 FakeTtsProvider，确保自动化测试与离线演示不依赖外部服务。
    M2 接入讯飞后，可通过 settings.TTS_PROVIDER 切换。
    """
    if provider_key is None:
        from app.core.config import settings
        provider_key = getattr(settings, "STAGE8_TTS_PROVIDER", "fake") or "fake"
    provider = _PROVIDER_REGISTRY.get(provider_key.lower())
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
    })
