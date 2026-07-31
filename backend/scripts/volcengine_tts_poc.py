"""Run one explicitly authorized, billable Doubao TTS v3 protocol probe.

This is a development-only diagnostic.  It does not write audio to disk and
will not contact Volcengine unless ``--allow-billable-call`` is provided.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import struct
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
DEFAULT_TEXT = "课程播放器时序验证。"
MAX_TEXT_BYTES = 60
PCM_SAMPLE_RATE = 24_000

# Values defined by Volcengine's public "TTS Websocket Bidirection protocols".
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
EVENT_NAMES = {
    EVENT_CONNECTION_STARTED: "ConnectionStarted",
    EVENT_CONNECTION_FAILED: "ConnectionFailed",
    EVENT_CONNECTION_FINISHED: "ConnectionFinished",
    EVENT_SESSION_STARTED: "SessionStarted",
    EVENT_SESSION_FINISHED: "SessionFinished",
    EVENT_SESSION_FAILED: "SessionFailed",
    EVENT_TTS_RESPONSE: "TTSResponse",
    EVENT_TTS_SUBTITLE: "TTSSubtitle",
    350: "TTSSentenceStart",
    351: "TTSSentenceEnd",
}


@dataclass(frozen=True)
class ParsedFrame:
    message_type: int
    flag: int
    event: int | None
    error_code: int | None
    payload: bytes


class ProviderRejectedError(RuntimeError):
    """The Provider sent an explicit error frame."""

    def __init__(self, frame: ParsedFrame, payload: dict[str, Any]):
        self.frame = frame
        self.payload = payload
        super().__init__("provider rejected request")


def _read_exact(buffer: memoryview, offset: int, length: int) -> tuple[bytes, int]:
    end = offset + length
    if length < 0 or end > len(buffer):
        raise ValueError("truncated Volcengine protocol frame")
    return bytes(buffer[offset:end]), end


def _read_u32(buffer: memoryview, offset: int) -> tuple[int, int]:
    raw, offset = _read_exact(buffer, offset, 4)
    return struct.unpack(">I", raw)[0], offset


def build_client_event_frame(event: int, payload: dict[str, Any], session_id: str = "") -> bytes:
    """Build a FullClientRequest event frame using the public v3 wire format."""
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
    """Parse the subset of the public v3 protocol used by this probe."""
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


def _payload_json(frame: ParsedFrame) -> dict[str, Any]:
    if not frame.payload:
        return {}
    try:
        parsed = json.loads(frame.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _safe_text(value: Any, secrets: tuple[str, ...]) -> str:
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:240]


def load_config(env_path: Path) -> dict[str, str]:
    values = dotenv_values(env_path)
    return {
        "api_key": (values.get("VOLCENGINE_DOUBAO_TTS_API_KEY") or "").strip(),
        "resource_id": (values.get("VOLCENGINE_DOUBAO_TTS_RESOURCE_ID") or "").strip(),
        "speaker": (values.get("VOLCENGINE_DOUBAO_TTS_SPEAKER") or "").strip(),
        "ws_url": (values.get("VOLCENGINE_DOUBAO_TTS_WS_URL") or DEFAULT_WS_URL).strip(),
    }


def config_summary(config: dict[str, str], text: str) -> dict[str, Any]:
    return {
        "configuration_complete": all(config[key] for key in ("api_key", "resource_id", "speaker")),
        "resource_id": config["resource_id"],
        "speaker_configured": bool(config["speaker"]),
        "api_key_configured": bool(config["api_key"]),
        "text_bytes": len(text.encode("utf-8")),
        "audio_format": "pcm_s16le",
        "sample_rate_hz": PCM_SAMPLE_RATE,
        "subtitle_requested": True,
    }


async def run_probe(config: dict[str, str], text: str) -> dict[str, Any]:
    """Perform exactly one session and return a safe diagnostic summary."""
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("websockets package is required for this development probe") from exc

    secrets = (config["api_key"], config["speaker"])
    events: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    audio = bytearray()
    words: list[dict[str, Any]] = []
    phonemes: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    session_id = str(uuid.uuid4())

    def record_event(frame: ParsedFrame) -> None:
        name = EVENT_NAMES.get(frame.event or -1, f"EventType({frame.event})")
        events[name] += 1

    async def receive_frame(websocket: Any, timeout_seconds: int = 45) -> ParsedFrame:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
        if isinstance(raw, str):
            raise RuntimeError("Provider returned an unexpected text WebSocket frame")
        frame = parse_server_frame(raw)
        record_event(frame)
        payload = _payload_json(frame)
        if frame.message_type == MSG_ERROR or frame.event in {
            EVENT_CONNECTION_FAILED,
            EVENT_SESSION_FAILED,
        }:
            failures.append({
                "event": EVENT_NAMES.get(frame.event or -1, f"EventType({frame.event})"),
                "frame_error_code": frame.error_code,
                "provider_code": payload.get("code"),
                "message": _safe_text(payload.get("message") or payload.get("error"), secrets),
            })
            raise ProviderRejectedError(frame, payload)
        return frame

    async def wait_for_event(websocket: Any, expected: int, timeout_seconds: int = 25) -> None:
        while True:
            frame = await receive_frame(websocket, timeout_seconds)
            if frame.event == expected:
                return

    headers = {
        "X-Api-Key": config["api_key"],
        "X-Api-Resource-Id": config["resource_id"],
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    base_request = {
        "req_params": {
            "speaker": config["speaker"],
            "audio_params": {
                "format": "pcm",
                "sample_rate": PCM_SAMPLE_RATE,
                "enable_subtitle": True,
            },
        },
    }

    try:
        async with websockets.connect(
            config["ws_url"],
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
            open_timeout=15,
            close_timeout=10,
        ) as websocket:
            await websocket.send(build_client_event_frame(EVENT_START_CONNECTION, {}))
            await wait_for_event(websocket, EVENT_CONNECTION_STARTED)

            start_payload = {**base_request, "event": EVENT_START_SESSION}
            await websocket.send(build_client_event_frame(EVENT_START_SESSION, start_payload, session_id))
            await wait_for_event(websocket, EVENT_SESSION_STARTED)

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
                    frame = await receive_frame(websocket, timeout_seconds=90)
                    if frame.message_type == MSG_AUDIO_ONLY_SERVER and frame.event == EVENT_TTS_RESPONSE:
                        audio.extend(frame.payload)
                    else:
                        payload = _payload_json(frame)
                        words.extend(_as_entries(payload.get("words")))
                        phonemes.extend(_as_entries(payload.get("phonemes")))
                        if frame.event == EVENT_SESSION_FINISHED:
                            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                            break
            finally:
                await sender

            await websocket.send(build_client_event_frame(EVENT_FINISH_CONNECTION, {}))
            await wait_for_event(websocket, EVENT_CONNECTION_FINISHED, timeout_seconds=15)
    except Exception as exc:
        duration_ms = round(len(audio) * 1000 / (PCM_SAMPLE_RATE * 2), 3)
        return {
            "status": "failed",
            "audio": {"bytes": len(audio), "duration_ms_pcm_s16le": duration_ms},
            "words": {"returned": False, "entries": 0},
            "phonemes": {"nonempty": False, "entries": 0},
            "timing_error_ms": None,
            "usage": usage,
            "events": dict(events),
            "provider_failures": failures,
            "error": {"type": type(exc).__name__, "message": _safe_text(exc, secrets)},
        }

    valid_words = [
        item for item in words
        if isinstance(item.get("startTime"), (int, float)) and isinstance(item.get("endTime"), (int, float))
    ]
    duration_ms = round(len(audio) * 1000 / (PCM_SAMPLE_RATE * 2), 3)
    last_word_end_ms = round(max((item["endTime"] for item in valid_words), default=0) * 1000, 3)
    return {
        "status": "ok",
        "audio": {
            "bytes": len(audio),
            "duration_ms_pcm_s16le": duration_ms,
            "sha256": hashlib.sha256(audio).hexdigest() if audio else "",
        },
        "words": {
            "returned": bool(valid_words),
            "entries": len(valid_words),
            "latest_end_ms": last_word_end_ms,
        },
        "phonemes": {"nonempty": bool(phonemes), "entries": len(phonemes)},
        "timing_error_ms": round(abs(duration_ms - last_word_end_ms), 3) if audio and valid_words else None,
        "usage": usage,
        "events": dict(events),
        "provider_failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-shot, development-only Doubao TTS v3 POC")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Short probe text; at most 60 UTF-8 bytes")
    parser.add_argument(
        "--allow-billable-call",
        action="store_true",
        help="Required before this command contacts Volcengine and may incur a charge",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = str(args.text).strip()
    if not text:
        print(json.dumps({"status": "invalid_input", "message": "probe text must not be empty"}, ensure_ascii=False))
        return 2
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        print(json.dumps({"status": "invalid_input", "message": "probe text exceeds 60 UTF-8 bytes"}, ensure_ascii=False))
        return 2

    config = load_config(args.env_file)
    summary = config_summary(config, text)
    if not summary["configuration_complete"]:
        print(json.dumps({"status": "configuration_missing", "config": summary}, ensure_ascii=False))
        return 2
    if not args.allow_billable_call:
        print(json.dumps({"status": "dry_run", "will_call_provider": False, "config": summary}, ensure_ascii=False))
        return 0

    result = asyncio.run(run_probe(config, text))
    result["request"] = {
        "text_bytes": len(text.encode("utf-8")),
        "format": "pcm_s16le",
        "sample_rate_hz": PCM_SAMPLE_RATE,
        "subtitle_requested": True,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
