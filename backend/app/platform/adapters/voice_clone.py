from __future__ import annotations

from pathlib import Path
from typing import Any

from app.platform.adapters.base import (
    AdapterResult,
    error_message_from_payload,
    is_failed_status,
    is_malformed_payload,
    run_adapter_call,
)
from app.platform.adapters.errors import AdapterErrorCode


class VoiceCloneAdapter:
    def __init__(self, client: Any, provider: str = "voice_clone"):
        self.client = client
        self.provider = provider

    async def create_voice_clone(self, audio_path: str, speaker_name: str = "test", **kwargs) -> AdapterResult:
        async def operation():
            if hasattr(self.client, "create_voice_clone"):
                return await self.client.create_voice_clone(audio_path, speaker_name=speaker_name, **kwargs)
            audio_bytes = Path(audio_path).read_bytes()
            return await self.client.upload_and_train(
                audio_bytes=audio_bytes,
                speaker_id=speaker_name,
                **kwargs,
            )

        return await run_adapter_call(self.provider, operation, self._parse_response)

    async def query_status(self, speaker_id: str) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.query_status(speaker_id),
            self._parse_response,
        )

    def _parse_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw) or not isinstance(raw, dict):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "Voice clone response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        if is_failed_status(raw.get("status")) or is_failed_status(raw.get("clone_status")):
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "Voice clone failed"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)
