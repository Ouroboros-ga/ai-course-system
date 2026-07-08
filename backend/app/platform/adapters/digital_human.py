from __future__ import annotations

from typing import Any

from app.platform.adapters.base import (
    AdapterResult,
    error_message_from_payload,
    is_failed_status,
    is_malformed_payload,
    run_adapter_call,
)
from app.platform.adapters.errors import AdapterErrorCode


class DigitalHumanAdapter:
    def __init__(self, client: Any, provider: str = "digital_human"):
        self.client = client
        self.provider = provider

    async def check_health(self) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.check_health(),
            self._parse_health_response,
        )

    async def generate_video(self, **kwargs) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.generate_video(**kwargs),
            self._parse_generate_response,
        )

    def _parse_health_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if raw is True:
            return AdapterResult.ok(True, provider=self.provider, raw=raw, duration_ms=duration_ms)
        if raw is False:
            return AdapterResult.fail(
                AdapterErrorCode.SERVICE_UNAVAILABLE,
                "Digital human service is unavailable",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        if is_malformed_payload(raw):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "Digital human health response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.fail(
            AdapterErrorCode.MALFORMED_RESPONSE,
            "Digital human health response is not boolean",
            provider=self.provider,
            raw=raw,
            duration_ms=duration_ms,
        )

    def _parse_generate_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "Digital human response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        status = getattr(raw, "status", None)
        video_path = getattr(raw, "video_path", None)
        if is_failed_status(status) or not video_path:
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "Digital human generation failed"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)
