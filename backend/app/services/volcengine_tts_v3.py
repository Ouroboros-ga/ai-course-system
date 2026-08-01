"""Minimal client for the Doubao/Volcengine TTS v3 bidirectional protocol.

This module deliberately owns only the provider wire protocol.  It does not
know about courses, releases, object storage, or HTTP requests.  Keeping that
boundary separate lets the production provider use the same public framing
rules verified by the development POC without exposing credentials to a
browser.

The client is synchronous at its public boundary because the existing TTS
provider contract is synchronous.  Call it from a media worker thread, never
from a FastAPI request handler.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import struct
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


MSG_FULL_CLIENT_REQUEST = 0x1
MSG_FULL_SERVER_RESPONSE = 0x9
MSG_AUDIO_ONLY_SERVER = 0xB
MSG_ERROR = 0xF
FLAG_WITH_EVENT = 0x4
FLAG_WITH_SEQUENCE = {0x1, 0x3}
COMPRESSION_GZIP = 0x1

EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_CONNECTION_FINISHED = 52
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_SESSION_STARTED = 150
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_TASK_REQUEST = 200
EVENT_TTS_RESPONSE = 352
EVENT_TTS_SUBTITLE = 364

CONNECTION_EVENTS = {
    EVENT_START_CONNECTION,
    EVENT_FINISH_CONNECTION,
    EVENT_CONNECTION_STARTED,
    EVENT_CONNECTION_FAILED,
    EVENT_CONNECTION_FINISHED,
}


@dataclass(frozen=True)
class ParsedFrame:
    message_type: int
    flag: int
    event: int | None
    error_code: int | None
    payload: bytes


class VolcengineTtsV3Error(RuntimeError):
    """A safe, structured provider failure.

    ``safe_message`` intentionally never includes request text, the API key,
    or the configured speaker ID.  The execution service persists only this
    field in task attempts.
    """

    def __init__(self, error_code: str, safe_message: str, *, retryable: bool = True):
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message
        self.retryable = retryable


@dataclass(frozen=True)
class VolcengineTtsV3Config:
    ws_url: str
    api_key: str
    resource_id: str
    speaker: str
    audio_format: str = "mp3"
    sample_rate: int = 24_000
    enable_subtitle: bool = True
    connect_timeout_seconds: int = 15
    read_timeout_seconds: int = 90


@dataclass
class VolcengineTtsV3Result:
    audio_bytes: bytes
    words: list[dict[str, Any]] = field(default_factory=list)
    phoneme_count: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    duration_source: str = "provider_word_timing"
    timing_error_ms: float | None = None


def _read_exact(buffer: memoryview, offset: int, length: int) -> tuple[bytes, int]:
    end = offset + length
    if length < 0 or end > len(buffer):
        raise ValueError("truncated Volcengine protocol frame")
    return bytes(buffer[offset:end]), end


def _read_u32(buffer: memoryview, offset: int) -> tuple[int, int]:
    raw, offset = _read_exact(buffer, offset, 4)
    return struct.unpack(">I", raw)[0], offset


def build_client_event_frame(event: int, payload: dict[str, Any], session_id: str = "") -> bytes:
    """Build a FullClientRequest event frame in the public v3 wire format."""
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    frame = bytearray((0x11, (MSG_FULL_CLIENT_REQUEST << 4) | FLAG_WITH_EVENT, 0x10, 0x00))
    frame.extend(struct.pack(">i", event))
    if event not in CONNECTION_EVENTS:
        session_bytes = session_id.encode("utf-8")
        frame.extend(struct.pack(">I", len(session_bytes)))
        frame.extend(session_bytes)
    frame.extend(struct.pack(">I", len(payload_bytes)))
    frame.extend(payload_bytes)
    return bytes(frame)


def parse_server_frame(data: bytes) -> ParsedFrame:
    """Parse the protocol subset used by TTS v3 audio/subtitle responses."""
    if len(data) < 4:
        raise ValueError("Volcengine protocol frame is shorter than its header")

    buffer = memoryview(data)
    header_size = (buffer[0] & 0x0F) * 4
    if header_size < 4 or header_size > len(data):
        raise ValueError("invalid Volcengine protocol header size")

    message_type = buffer[1] >> 4
    flag = buffer[1] & 0x0F
    compression = buffer[2] & 0x0F
    offset = header_size
    error_code: int | None = None
    event: int | None = None

    if message_type == MSG_ERROR:
        error_code, offset = _read_u32(buffer, offset)
    elif flag in FLAG_WITH_SEQUENCE:
        _, offset = _read_exact(buffer, offset, 4)

    if flag == FLAG_WITH_EVENT:
        raw_event, offset = _read_exact(buffer, offset, 4)
        event = struct.unpack(">i", raw_event)[0]
        if event not in CONNECTION_EVENTS:
            session_size, offset = _read_u32(buffer, offset)
            _, offset = _read_exact(buffer, offset, session_size)
        if event in {
            EVENT_CONNECTION_STARTED,
            EVENT_CONNECTION_FAILED,
            EVENT_CONNECTION_FINISHED,
        }:
            connection_size, offset = _read_u32(buffer, offset)
            _, offset = _read_exact(buffer, offset, connection_size)

    payload_size, offset = _read_u32(buffer, offset)
    payload, offset = _read_exact(buffer, offset, payload_size)
    if offset != len(data):
        raise ValueError("unexpected trailing data in Volcengine protocol frame")
    if compression == COMPRESSION_GZIP and payload:
        payload = gzip.decompress(payload)
    elif compression not in (0, COMPRESSION_GZIP):
        raise ValueError(f"unsupported Volcengine compression value: {compression}")
    return ParsedFrame(message_type, flag, event, error_code, payload)


def payload_json(frame: ParsedFrame) -> dict[str, Any]:
    if not frame.payload:
        return {}
    try:
        parsed = json.loads(frame.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _safe_provider_message(payload: dict[str, Any]) -> str:
    code = payload.get("code") or payload.get("status_code")
    # Provider messages may echo request text or an audio/speaker identifier.
    # Persisting only the code preserves actionable diagnosis without leaking
    # course content or credential-like identifiers into task attempts.
    return f"Doubao TTS provider rejected the request (code={code or 'unknown'})"


class VolcengineTtsV3Client:
    """One-shot TTS v3 session client.

    Text is streamed character by character, matching the successful POC and
    avoiding the ambiguous one-shot request pattern seen in early probes.
    """

    def __init__(self, config: VolcengineTtsV3Config):
        self._config = config

    def synthesize(self, text: str) -> VolcengineTtsV3Result:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.synthesize_async(text))
        raise VolcengineTtsV3Error(
            "TTS_WORKER_REQUIRED",
            "Doubao TTS must run in the media worker, not an API event loop",
            retryable=False,
        )

    async def synthesize_async(self, text: str) -> VolcengineTtsV3Result:
        if not text:
            raise VolcengineTtsV3Error("TTS_EMPTY_SCRIPT", "TTS script must not be empty", retryable=False)
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - deployment guard
            raise VolcengineTtsV3Error(
                "TTS_DEPENDENCY_UNAVAILABLE",
                "The optional websockets dependency is unavailable for Doubao TTS",
                retryable=False,
            ) from exc

        cfg = self._config
        headers = {
            "X-Api-Key": cfg.api_key,
            "X-Api-Resource-Id": cfg.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        session_id = str(uuid.uuid4())
        base_request = {
            "req_params": {
                "speaker": cfg.speaker,
                "audio_params": {
                    "format": cfg.audio_format,
                    "sample_rate": cfg.sample_rate,
                    "enable_subtitle": cfg.enable_subtitle,
                },
            },
        }
        audio = bytearray()
        words: list[dict[str, Any]] = []
        phoneme_count = 0
        usage: dict[str, Any] = {}
        events: Counter[int] = Counter()

        async def receive_frame(websocket: Any, timeout_seconds: int) -> ParsedFrame:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise VolcengineTtsV3Error(
                    "TTS_PROVIDER_TIMEOUT",
                    "Doubao TTS timed out while waiting for a provider response",
                ) from exc
            if isinstance(raw, str):
                raise VolcengineTtsV3Error(
                    "TTS_PROTOCOL_ERROR",
                    "Doubao TTS returned an unexpected text WebSocket frame",
                )
            try:
                frame = parse_server_frame(raw)
            except (ValueError, OSError) as exc:
                raise VolcengineTtsV3Error(
                    "TTS_PROTOCOL_ERROR",
                    "Doubao TTS returned an invalid protocol frame",
                ) from exc
            if frame.event is not None:
                events[frame.event] += 1
            payload = payload_json(frame)
            if frame.message_type == MSG_ERROR or frame.event in {
                EVENT_CONNECTION_FAILED,
                EVENT_SESSION_FAILED,
            }:
                raise VolcengineTtsV3Error(
                    "TTS_PROVIDER_REJECTED",
                    _safe_provider_message(payload),
                    retryable=False,
                )
            return frame

        async def wait_for_event(websocket: Any, expected: int, timeout_seconds: int) -> None:
            while True:
                frame = await receive_frame(websocket, timeout_seconds)
                if frame.event == expected:
                    return

        try:
            async with websockets.connect(
                cfg.ws_url,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
                open_timeout=cfg.connect_timeout_seconds,
                close_timeout=10,
            ) as websocket:
                await websocket.send(build_client_event_frame(EVENT_START_CONNECTION, {}))
                await wait_for_event(websocket, EVENT_CONNECTION_STARTED, cfg.connect_timeout_seconds)

                start_payload = {**base_request, "event": EVENT_START_SESSION}
                await websocket.send(build_client_event_frame(EVENT_START_SESSION, start_payload, session_id))
                await wait_for_event(websocket, EVENT_SESSION_STARTED, cfg.connect_timeout_seconds)

                async def send_text_stream() -> None:
                    for character in text:
                        request = {
                            **base_request,
                            "event": EVENT_TASK_REQUEST,
                            "req_params": {**base_request["req_params"], "text": character},
                        }
                        await websocket.send(build_client_event_frame(EVENT_TASK_REQUEST, request, session_id))
                        await asyncio.sleep(0.005)
                    await websocket.send(build_client_event_frame(EVENT_FINISH_SESSION, {}, session_id))

                sender = asyncio.create_task(send_text_stream())
                try:
                    while True:
                        frame = await receive_frame(websocket, cfg.read_timeout_seconds)
                        if frame.message_type == MSG_AUDIO_ONLY_SERVER and frame.event == EVENT_TTS_RESPONSE:
                            audio.extend(frame.payload)
                            continue
                        payload = payload_json(frame)
                        words.extend(_entries(payload.get("words")))
                        phoneme_count += len(_entries(payload.get("phonemes")))
                        if frame.event == EVENT_SESSION_FINISHED:
                            raw_usage = payload.get("usage")
                            usage = raw_usage if isinstance(raw_usage, dict) else {}
                            break
                finally:
                    await sender

                await websocket.send(build_client_event_frame(EVENT_FINISH_CONNECTION, {}))
                await wait_for_event(websocket, EVENT_CONNECTION_FINISHED, cfg.connect_timeout_seconds)
        except VolcengineTtsV3Error:
            raise
        except Exception as exc:
            raise VolcengineTtsV3Error(
                "TTS_PROVIDER_UNAVAILABLE",
                f"Doubao TTS connection failed: {type(exc).__name__}",
            ) from exc

        if not audio:
            raise VolcengineTtsV3Error(
                "TTS_EMPTY_AUDIO",
                "Doubao TTS completed without audio data",
            )

        valid_words = [
            item for item in words
            if isinstance(item.get("startTime"), (int, float))
            and isinstance(item.get("endTime"), (int, float))
        ]
        word_duration_ms = int(round(max((item["endTime"] for item in valid_words), default=0) * 1000))
        if cfg.audio_format == "pcm":
            audio_duration_ms = int(round(len(audio) * 1000 / (cfg.sample_rate * 2)))
            return VolcengineTtsV3Result(
                audio_bytes=bytes(audio),
                words=valid_words,
                phoneme_count=phoneme_count,
                usage=usage,
                duration_ms=audio_duration_ms,
                duration_source="pcm_bytes",
                timing_error_ms=abs(audio_duration_ms - word_duration_ms) if valid_words else None,
            )
        return VolcengineTtsV3Result(
            audio_bytes=bytes(audio),
            words=valid_words,
            phoneme_count=phoneme_count,
            usage=usage,
            duration_ms=word_duration_ms,
            duration_source="provider_word_timing",
            timing_error_ms=None,
        )
