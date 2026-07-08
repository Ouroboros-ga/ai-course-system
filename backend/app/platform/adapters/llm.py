from __future__ import annotations

import json
from typing import Any

from app.platform.adapters.base import (
    AdapterResult,
    error_message_from_payload,
    is_failed_status,
    is_malformed_payload,
    run_adapter_call,
)
from app.platform.adapters.errors import AdapterErrorCode


class LLMAdapter:
    def __init__(self, client: Any, provider: str = "llm"):
        self.client = client
        self.provider = provider

    async def chat(self, messages, **kwargs) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.chat(messages, **kwargs),
            self._parse_chat_response,
        )

    def _parse_chat_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw) or not hasattr(raw, "content"):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "LLM response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )

        content = getattr(raw, "content", None)
        finish_reason = getattr(raw, "finish_reason", None)
        if is_failed_status(finish_reason) or content in (None, ""):
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "LLM returned empty or failed content"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )

        if isinstance(content, str):
            stripped = content.strip()
            if stripped.startswith("{"):
                try:
                    payload = json.loads(stripped)
                    if is_failed_status(payload.get("status")):
                        return AdapterResult.fail(
                            AdapterErrorCode.BUSINESS_FAILURE,
                            error_message_from_payload(payload, "LLM returned failed status"),
                            provider=self.provider,
                            raw=raw,
                            duration_ms=duration_ms,
                        )
                except json.JSONDecodeError:
                    pass

        return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)
