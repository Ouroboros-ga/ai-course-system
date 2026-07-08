from __future__ import annotations

from typing import Any, Callable

import httpx

from app.platform.adapters.base import (
    AdapterResult,
    error_message_from_payload,
    is_failed_status,
    is_malformed_payload,
    is_success_code,
    run_adapter_call,
)
from app.platform.adapters.errors import AdapterErrorCode


class ExternalHTTPAdapter:
    def __init__(
        self,
        client_factory: Callable[..., Any] = httpx.AsyncClient,
        provider: str = "external_http",
        **client_kwargs,
    ):
        self.client_factory = client_factory
        self.provider = provider
        self.client_kwargs = client_kwargs

    async def get(self, url: str, **kwargs) -> AdapterResult:
        async def operation():
            async with self.client_factory(**self.client_kwargs) as client:
                response = await client.get(url, **kwargs)
                response.raise_for_status()
                return response

        return await run_adapter_call(self.provider, operation, self._parse_response)

    async def post(self, url: str, **kwargs) -> AdapterResult:
        async def operation():
            async with self.client_factory(**self.client_kwargs) as client:
                response = await client.post(url, **kwargs)
                response.raise_for_status()
                return response

        return await run_adapter_call(self.provider, operation, self._parse_response)

    def _parse_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        try:
            payload = raw.json()
        except Exception:
            payload = None

        if is_malformed_payload(payload):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "HTTP response payload is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )

        if isinstance(payload, dict):
            code = payload.get("code")
            status = payload.get("status")
            if not is_success_code(code) or is_failed_status(status):
                return AdapterResult.fail(
                    AdapterErrorCode.BUSINESS_FAILURE,
                    error_message_from_payload(payload, "HTTP business response failed"),
                    provider=self.provider,
                    raw=raw,
                    duration_ms=duration_ms,
                )
            return AdapterResult.ok(payload, provider=self.provider, raw=raw, duration_ms=duration_ms)

        content = getattr(raw, "content", None)
        if content is None:
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "HTTP response has no content",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.ok(content, provider=self.provider, raw=raw, duration_ms=duration_ms)
