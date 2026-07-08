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