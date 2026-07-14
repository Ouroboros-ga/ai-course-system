from dataclasses import dataclass
from pathlib import Path

from app.common.digital_human_client import DigitalHumanResponse
from app.common.llm_client import LLMResponse
from app.common.tts_client import TTSResponse
from app.services.ppt_generation_service import PPTTaskResult


class FakeServiceError(RuntimeError):
    pass


class FakeTimeoutError(TimeoutError):
    pass


BUSINESS_FAILURE_MESSAGE = "fake upstream business failure"


def _handle_mode(mode: str):
    if mode == "timeout":
        raise FakeTimeoutError("fake service timeout")
    if mode == "service_unavailable":
        raise FakeServiceError("fake service unavailable")
    if mode in {"malformed", "malformed_response"}:
        return {"malformed": True}
    return None


def _is_business_failure(mode: str) -> bool:
    return mode == "business_failure"


class FakeLLMClient:
    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "kwargs": kwargs,
        })
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return LLMResponse(
                content="",
                usage={"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
                model="fake-llm",
                finish_reason="business_failure",
                latency_ms=1.0,
            )
        return LLMResponse(
            content="fake llm response",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            model="fake-llm",
            finish_reason="stop",
            latency_ms=1.0,
        )

    async def simple_chat(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return '{"status":"failed","error":"fake llm refused to generate","content":""}'
        return "fake llm response"


class FakeTTSClient:
    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def synthesize(self, text: str, voice=None, sample_rate=None, output_format=None, **kwargs):
        self.calls.append({
            "text": text,
            "voice": voice,
            "sample_rate": sample_rate,
            "output_format": output_format,
            "kwargs": kwargs,
        })
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {
                "code": "TTS_SYNTHESIS_FAILED",
                "status": "failed",
                "message": BUSINESS_FAILURE_MESSAGE,
                "audio_data": b"",
                "audio_format": output_format or "mp3",
                "sample_rate": sample_rate or 16000,
            }
        return TTSResponse(
            audio_data=b"FAKE_AUDIO",
            audio_format=output_format or "mp3",
            sample_rate=sample_rate or 16000,
            duration_ms=100.0,
            latency_ms=1.0,
        )


class FakeVoiceCloneClient:
    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def create_voice_clone(self, audio_path: str, speaker_name: str = "test"):
        self.calls.append({"audio_path": audio_path, "speaker_name": speaker_name})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {
                "speaker_id": "fake-speaker",
                "status": "success",
                "clone_status": "failed",
                "message": BUSINESS_FAILURE_MESSAGE,
            }
        return {"speaker_id": "fake-speaker", "status": "success"}

    async def query_status(self, speaker_id: str):
        self.calls.append({"speaker_id": speaker_id})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {
                "speaker_id": speaker_id,
                "status": "success",
                "clone_status": "failed",
                "message": BUSINESS_FAILURE_MESSAGE,
            }
        return {"speaker_id": speaker_id, "status": "success"}


class FakePPTClient:
    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def get_theme_list(self, **kwargs):
        self.calls.append({"method": "get_theme_list", "kwargs": kwargs})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {"code": 0, "data": {"records": [{"templateIndexId": "fake-template"}]}}
        return {"data": {"records": [{"templateIndexId": "fake-template"}]}}

    async def create_ppt_task(self, query: str, template_id: str, author: str = "AI Course", **kwargs):
        self.calls.append({
            "method": "create_ppt_task",
            "query": query,
            "template_id": template_id,
            "author": author,
            "kwargs": kwargs,
        })
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        return {"code": 0, "data": {"sid": "fake-sid"}}

    async def wait_for_completion(self, sid: str, max_wait_seconds: int = 300, poll_interval: int = 5):
        self.calls.append({"method": "wait_for_completion", "sid": sid})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return PPTTaskResult(sid=sid, status="failed", ppt_url="", error=BUSINESS_FAILURE_MESSAGE)
        return PPTTaskResult(sid=sid, status="done", ppt_url="https://fake.invalid/fake.pptx")

    async def download_ppt(self, ppt_url: str, save_path: str):
        self.calls.append({"method": "download_ppt", "ppt_url": ppt_url, "save_path": save_path})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {"code": "PPT_DOWNLOAD_BLOCKED", "status": "failed", "message": BUSINESS_FAILURE_MESSAGE}
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_bytes(b"FAKE_PPTX")
        return save_path

    async def get_task_progress(self, sid: str):
        self.calls.append({"method": "get_task_progress", "sid": sid})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {
                "code": 0,
                "data": {
                    "pptStatus": "failed",
                    "sid": sid,
                    "error": BUSINESS_FAILURE_MESSAGE,
                },
            }
        return {"code": 0, "data": {"pptStatus": "done", "sid": sid}}


class FakeDigitalHumanClient:
    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []
        self.api_url = "http://fake-digital-human.local"

    async def check_health(self):
        self.calls.append({"method": "check_health"})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        return True

    async def generate_video(self, audio_path: str, video_path: str, **kwargs):
        self.calls.append({"method": "generate_video", "audio_path": audio_path, "video_path": video_path, "kwargs": kwargs})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            response = DigitalHumanResponse(
                video_path="",
                generation_time="0.1s",
                download_path="",
            )
            response.status = "failed"
            response.error = BUSINESS_FAILURE_MESSAGE
            return response
        return DigitalHumanResponse(
            video_path="/tmp/fake-digital-human.mp4",
            generation_time="0.1s",
            download_path="/tmp/fake-digital-human.mp4",
        )


@dataclass
class FakeHTTPXResponse:
    status_code: int = 200
    payload: dict | None = None
    text: str = ""
    content: bytes = b""

    def json(self):
        return self.payload if self.payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeServiceError(f"fake http error: {self.status_code}")


class FakeHTTPXClient:
    def __init__(self, mode: str = "success", **kwargs):
        self.mode = mode
        self.kwargs = kwargs
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, **kwargs):
        self.calls.append({"method": "get", "url": url, "kwargs": kwargs})
        return self._response()

    async def post(self, url: str, **kwargs):
        self.calls.append({"method": "post", "url": url, "kwargs": kwargs})
        return self._response()

    def _response(self):
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return FakeHTTPXResponse(status_code=200, payload=malformed, text="malformed")
        if _is_business_failure(self.mode):
            return FakeHTTPXResponse(
                status_code=200,
                payload={"code": 40001, "status": "failed", "message": BUSINESS_FAILURE_MESSAGE, "data": None},
                text=BUSINESS_FAILURE_MESSAGE,
                content=BUSINESS_FAILURE_MESSAGE.encode("utf-8"),
            )
        return FakeHTTPXResponse(
            status_code=200,
            payload={"code": 0, "status": "success", "data": {"ok": True}},
            text="fake httpx success",
            content=b"FAKE_HTTPX_CONTENT",
        )

# ===========================================================================
# P1-10 NEW fake capabilities for Product 1 contract tests
# ===========================================================================
# These fakes follow the same 5+2 mode pattern (success / timeout / service
# unavailable / malformed / business_failure / partial / conflict) used by
# the existing fakes above.  They extend the shared test infrastructure so
# other agents' contract tests can reference them.
#
# STRICT SEPARATION: These fakes prove control flow and failure semantics
# ONLY.  They must NOT be presented as evidence of real model quality.
# ===========================================================================


class FakeParserProvider:
    """Fake parser provider for DocumentIR contract tests.

    Modes: success, timeout, service_unavailable, malformed,
           business_failure, partial, conflict.
    """

    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def parse(self, source: bytes, **kwargs):
        self.calls.append({"source_len": len(source), "kwargs": kwargs})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {"status": "business_failure", "reason": BUSINESS_FAILURE_MESSAGE, "blocks": []}
        if self.mode == "partial":
            return {
                "status": "partial",
                "blocks": [{"id": "b1", "text": "parsed block"}],
                "errors": ["page 2: unsupported format"],
            }
        if self.mode == "conflict":
            return {"status": "conflict", "reason": "concurrent modification detected", "blocks": []}
        return {
            "status": "success",
            "document_id": "doc-fake-001",
            "blocks": [
                {"id": "b1", "type": "text", "text": "Hello world", "page": 1},
                {"id": "b2", "type": "heading", "text": "Section 1", "page": 1, "level": 1},
            ],
            "metadata": {"page_count": 1, "provenance": {"parser": "fake-parser", "version": "1.0"}},
        }


class FakeRetrieverProvider:
    """Fake retriever provider for Evidence/retrieval contract tests.

    Modes: success, timeout, service_unavailable, malformed,
           business_failure, partial.
    """

    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def retrieve(self, query: str, scope: dict | None = None, **kwargs):
        self.calls.append({"query": query, "scope": scope, "kwargs": kwargs})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {"status": "business_failure", "reason": BUSINESS_FAILURE_MESSAGE, "chunks": []}
        if self.mode == "partial":
            return {
                "status": "partial",
                "chunks": [{"id": "c1", "text": "relevant chunk", "score": 0.85}],
                "errors": ["index shard 2 unavailable"],
            }
        return {
            "status": "success",
            "chunks": [
                {"id": "c1", "text": "retrieved chunk 1", "score": 0.95, "source": "doc-001"},
                {"id": "c2", "text": "retrieved chunk 2", "score": 0.82, "source": "doc-001"},
            ],
            "total_hits": 2,
        }


class FakeMasteryProvider:
    """Fake mastery/cognition provider for LearningEvent contract tests.

    Modes: success, timeout, service_unavailable, malformed,
           business_failure.
    """

    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def estimate(self, student_id: str, course_id: str, events: list | None = None, **kwargs):
        self.calls.append({
            "student_id": student_id,
            "course_id": course_id,
            "events": events,
            "kwargs": kwargs,
        })
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {"status": "business_failure", "reason": BUSINESS_FAILURE_MESSAGE, "mastery": {}}
        return {
            "status": "success",
            "mastery": {"concept_1": 0.85, "concept_2": 0.60, "concept_3": 0.45},
            "evidence_refs": ["evt-001", "evt-002", "evt-003"],
            "provider": "fake-mastery",
            "version": "1.0",
        }


class FakeSafetyProvider:
    """Fake safety evaluator for SafetyPolicy contract tests.

    Modes: success, timeout, service_unavailable, malformed,
           business_failure.
    """

    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    async def evaluate(self, query: str, context: dict | None = None, **kwargs):
        self.calls.append({"query": query, "context": context, "kwargs": kwargs})
        malformed = _handle_mode(self.mode)
        if malformed is not None:
            return malformed
        if _is_business_failure(self.mode):
            return {"status": "business_failure", "reason": BUSINESS_FAILURE_MESSAGE, "decision": "deny"}
        return {
            "status": "success",
            "decision": "allow" if "forbidden" not in query.lower() else "deny",
            "reason_code": "ok",
            "matched_rules": [],
        }


class FakeMemoryStore:
    """Fake memory store for StudentMemory contract tests.

    Supports create, read, update, delete, and scope isolation.
    Not a real database -- in-memory dict only.
    """

    def __init__(self):
        self._store: dict[str, dict] = {}
        self.calls = []

    def _key(self, student_id: str, course_id: str, memory_id: str) -> str:
        return f"{student_id}:{course_id}:{memory_id}"

    def add(self, student_id: str, course_id: str, memory_id: str, data: dict) -> dict:
        self.calls.append({"action": "add", "student_id": student_id, "course_id": course_id, "memory_id": memory_id})
        k = self._key(student_id, course_id, memory_id)
        if k in self._store:
            raise ValueError(f"Memory already exists: {memory_id}")
        entry = {"student_id": student_id, "course_id": course_id, "memory_id": memory_id, **data}
        self._store[k] = entry
        return entry

    def get(self, student_id: str, course_id: str, memory_id: str) -> dict | None:
        self.calls.append({"action": "get", "student_id": student_id, "course_id": course_id, "memory_id": memory_id})
        k = self._key(student_id, course_id, memory_id)
        entry = self._store.get(k)
        if entry is None:
            return None
        if entry["student_id"] != student_id or entry["course_id"] != course_id:
            return None
        return dict(entry)

    def delete(self, student_id: str, course_id: str, memory_id: str) -> bool:
        self.calls.append({"action": "delete", "student_id": student_id, "course_id": course_id, "memory_id": memory_id})
        k = self._key(student_id, course_id, memory_id)
        if k not in self._store:
            return False
        del self._store[k]
        return True

    def list_for_student(self, student_id: str, course_id: str) -> list[dict]:
        self.calls.append({"action": "list", "student_id": student_id, "course_id": course_id})
        return [
            dict(v) for v in self._store.values()
            if v["student_id"] == student_id and v["course_id"] == course_id
        ]

    def clear_all(self) -> None:
        self._store.clear()
        self.calls.clear()


class FakeLearningEventStore:
    """Fake append-only event store for LearningEvent contract tests."""

    def __init__(self):
        self._events: list[dict] = []
        self.calls = []

    def append(self, event: dict) -> dict:
        self.calls.append({"action": "append", "event": event})
        event = dict(event)
        event["_index"] = len(self._events)
        self._events.append(event)
        return event

    def get_events(self, student_id: str, course_id: str) -> list[dict]:
        self.calls.append({"action": "get_events", "student_id": student_id, "course_id": course_id})
        return [
            dict(e) for e in self._events
            if e.get("student_id") == student_id and e.get("course_id") == course_id
        ]

    def get_by_idempotency_key(self, key: str) -> dict | None:
        for e in self._events:
            if e.get("idempotency_key") == key:
                return dict(e)
        return None


class FakeCitationValidator:
    """Fake citation validator for Citation contract tests."""

    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls = []

    def validate(self, citation_key: str, evidence_ids: list[str]) -> dict:
        self.calls.append({"citation_key": citation_key, "evidence_ids": evidence_ids})
        if self.mode == "business_failure":
            return {"valid": False, "reason": BUSINESS_FAILURE_MESSAGE}
        missing = [eid for eid in evidence_ids if not eid.startswith("evt-")]
        return {
            "valid": len(missing) == 0,
            "citation_key": citation_key,
            "evidence_ids": evidence_ids,
            "missing_ids": missing,
        }
