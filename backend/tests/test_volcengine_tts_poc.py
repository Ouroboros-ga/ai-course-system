"""Regression checks for the local-only parts of the billable TTS POC command."""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "volcengine_tts_poc.py"
SPEC = importlib.util.spec_from_file_location("volcengine_tts_poc", SCRIPT_PATH)
POC = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = POC
SPEC.loader.exec_module(POC)


def _server_event_frame(event: int, payload: dict, *, connection_id: str = "", session_id: str = "") -> bytes:
    payload_bytes = json.dumps(payload).encode("utf-8")
    frame = bytearray((0x11, (POC.MSG_FULL_SERVER_RESPONSE << 4) | POC.FLAG_WITH_EVENT, 0x10, 0))
    frame.extend(struct.pack(">i", event))
    if event not in POC.CONNECTION_EVENTS:
        session_bytes = session_id.encode("utf-8")
        frame.extend(struct.pack(">I", len(session_bytes)))
        frame.extend(session_bytes)
    if event in {POC.EVENT_CONNECTION_STARTED, POC.EVENT_CONNECTION_FAILED, POC.EVENT_CONNECTION_FINISHED}:
        connection_bytes = connection_id.encode("utf-8")
        frame.extend(struct.pack(">I", len(connection_bytes)))
        frame.extend(connection_bytes)
    frame.extend(struct.pack(">I", len(payload_bytes)))
    frame.extend(payload_bytes)
    return bytes(frame)


def test_client_session_frame_contains_event_and_session_id():
    frame = POC.build_client_event_frame(POC.EVENT_START_SESSION, {"event": POC.EVENT_START_SESSION}, "session-1")
    assert frame[1] >> 4 == POC.MSG_FULL_CLIENT_REQUEST
    assert struct.unpack(">i", frame[4:8])[0] == POC.EVENT_START_SESSION
    assert b"session-1" in frame


def test_parse_connection_started_frame():
    frame = _server_event_frame(POC.EVENT_CONNECTION_STARTED, {}, connection_id="connect-1")
    parsed = POC.parse_server_frame(frame)
    assert parsed.message_type == POC.MSG_FULL_SERVER_RESPONSE
    assert parsed.event == POC.EVENT_CONNECTION_STARTED
    assert POC._payload_json(parsed) == {}


def test_parse_subtitle_frame_preserves_word_timing():
    payload = {"words": [{"word": "课", "startTime": 0.1, "endTime": 0.2}], "phonemes": []}
    frame = _server_event_frame(POC.EVENT_TTS_SUBTITLE, payload, session_id="session-1")
    parsed = POC.parse_server_frame(frame)
    assert parsed.event == POC.EVENT_TTS_SUBTITLE
    assert POC._payload_json(parsed)["words"][0]["endTime"] == 0.2
