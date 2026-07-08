from __future__ import annotations

from typing import Any

from app.platform.adapters.base import (
    AdapterResult,
    error_message_from_payload,
    is_failed_status,
    is_malformed_payload,
    is_success_code,
    run_adapter_call,
)
from app.platform.adapters.errors import AdapterErrorCode


class TTSAdapter:
    def __init__(self, client: Any, provider: str = "tts"):
        self.client = client
        self.provider = provider

    async def synthesize(self, **kwargs) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.synthesize(**kwargs),
            self._parse_synthesize_response,
        )

    def _parse_synthesize_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "TTS response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )

        if isinstance(raw, dict):
            if is_failed_status(raw.get("status")) or not is_success_code(raw.get("code")):
                return AdapterResult.fail(
                    AdapterErrorCode.BUSINESS_FAILURE,
                    error_message_from_payload(raw, "TTS synthesis failed"),
                    provider=self.provider,
                    raw=raw,
                    duration_ms=duration_ms,
                )
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "TTS response is missing audio data",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )

        audio_data = getattr(raw, "audio_data", None)
        if not audio_data:
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "TTS returned empty audio"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)
