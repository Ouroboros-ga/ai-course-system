from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Callable

import httpx

from app.common.digital_human_client import DigitalHumanResponse
from app.core.config import settings
from app.platform.adapters.base import (
    error_message_from_payload,
    is_failed_status,
    is_malformed_payload,
    is_success_code,
)


class DuixAvatarProvider:
    """Client-compatible provider for the local Duix.Avatar HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 600,
        health_timeout: float = 10,
        poll_interval: float = 2,
        max_polls: int = 300,
        client_factory: Callable[..., Any] = httpx.AsyncClient,
    ):
        self.base_url = (
            base_url
            or os.getenv("DUIX_BASE_URL")
            or getattr(settings, "DUIX_BASE_URL", None)
            or "http://127.0.0.1:8383"
        ).rstrip("/")
        self.api_url = self.base_url
        self.timeout = timeout
        self.health_timeout = health_timeout
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.client_factory = client_factory

    async def check_health(self) -> bool:
        async with self.client_factory(timeout=self.health_timeout) as client:
            response = await client.get(self.base_url)
            return getattr(response, "status_code", 500) < 500

    async def generate_video(self, audio_path: str, video_path: str, **kwargs) -> Any:
        task_code = str(kwargs.get("code") or uuid.uuid4().hex)
        payload = {
            "audio_url": str(audio_path),
            "video_url": str(video_path),
            "code": task_code,
            "chaofen": 0,
            "watermark_switch": 0,
            "pn": 1,
        }

        start_time = time.time()
        async with self.client_factory(timeout=self.timeout) as client:
            submit_response = await client.post(f"{self.base_url}/easy/submit", json=payload)
            submit_response.raise_for_status()
            submit_payload = self._json_payload(submit_response)
            if is_malformed_payload(submit_payload):
                return submit_payload
            if self._has_business_failure(submit_payload):
                return self._failed_response(submit_payload, start_time)

            task_code = self._task_code_from_submit(submit_payload, task_code)
            query_url = f"{self.base_url}/easy/query?code={task_code}"
            for poll_index in range(self.max_polls):
                query_response = await client.get(query_url)
                query_response.raise_for_status()
                query_payload = self._json_payload(query_response)
                if is_malformed_payload(query_payload):
                    return query_payload
                if self._has_business_failure(query_payload):
                    return self._failed_response(query_payload, start_time)

                output_path = self._extract_video_path(query_payload)
                status = self._extract_status(query_payload)
                if output_path:
                    return self._success_response(output_path, query_payload, start_time)
                if self._is_terminal_success(status):
                    return self._failed_response(
                        {
                            "status": status,
                            "message": "Duix query completed without video path",
                            "data": query_payload,
                        },
                        start_time,
                    )

                if poll_index < self.max_polls - 1 and self.poll_interval > 0:
                    await asyncio.sleep(self.poll_interval)

        raise TimeoutError(f"Duix avatar generation timed out after {self.max_polls} polls")

    def _json_payload(self, response: Any) -> Any:
        try:
            payload = response.json()
        except Exception:
            return {"malformed": True}
        if not isinstance(payload, dict):
            return {"malformed": True}
        return payload

    def _task_code_from_submit(self, payload: dict[str, Any], fallback: str) -> str:
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("taskCode", "task_code", "code"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        for key in ("taskCode", "task_code"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return fallback

    def _has_business_failure(self, payload: dict[str, Any]) -> bool:
        if payload.get("success") is False:
            return True
        if not is_success_code(payload.get("code")):
            return True
        if is_failed_status(payload.get("status")):
            return True
        data = payload.get("data")
        if isinstance(data, dict):
            if data.get("success") is False:
                return True
            if not is_success_code(data.get("code")):
                return True
            if is_failed_status(data.get("status")):
                return True
        return False

    def _extract_status(self, payload: dict[str, Any]) -> Any:
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("status", "taskStatus", "task_status", "state"):
                if data.get(key) is not None:
                    return data.get(key)
        for key in ("status", "taskStatus", "task_status", "state"):
            if payload.get(key) is not None:
                return payload.get(key)
        return None

    def _extract_video_path(self, payload: dict[str, Any]) -> str:
        data = payload.get("data")
        candidates = [payload]
        if isinstance(data, dict):
            candidates.insert(0, data)
            nested = data.get("result")
            if isinstance(nested, dict):
                candidates.insert(0, nested)
        for item in candidates:
            for key in (
                "video_url",
                "videoUrl",
                "video_path",
                "videoPath",
                "output_url",
                "outputUrl",
                "output_path",
                "path",
                "url",
            ):
                value = item.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    def _is_terminal_success(self, status: Any) -> bool:
        return str(status).lower() in {
            "success",
            "succeeded",
            "done",
            "completed",
            "finish",
            "finished",
        }

    def _success_response(
        self,
        output_path: str,
        payload: dict[str, Any],
        start_time: float,
    ) -> DigitalHumanResponse:
        response = DigitalHumanResponse(
            video_path=output_path,
            generation_time=self._generation_time(payload, start_time),
            download_path=output_path,
        )
        response.status = "success"
        response.raw = payload
        return response

    def _failed_response(self, payload: dict[str, Any], start_time: float) -> DigitalHumanResponse:
        response = DigitalHumanResponse(
            video_path="",
            generation_time=self._generation_time(payload, start_time),
            download_path="",
        )
        response.status = "failed"
        response.error = error_message_from_payload(payload, "Duix avatar generation failed")
        response.raw = payload
        return response

    def _generation_time(self, payload: dict[str, Any], start_time: float) -> str:
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("generation_time", "generationTime", "duration", "elapsed"):
                value = data.get(key)
                if value:
                    return str(value)
        for key in ("generation_time", "generationTime", "duration", "elapsed"):
            value = payload.get(key)
            if value:
                return str(value)
        return f"{time.time() - start_time:.1f}s"
