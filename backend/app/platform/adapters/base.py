from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.platform.adapters.errors import AdapterErrorCode


@dataclass
class AdapterResult:
    success: bool
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    provider: str = ""
    raw: Any = None
    duration_ms: float = 0.0

    @classmethod
    def ok(
        cls,
        data: Any = None,
        *,
        provider: str = "",
        raw: Any = None,
        duration_ms: float = 0.0,
    ) -> "AdapterResult":
        return cls(
            success=True,
            data=data,
            provider=provider,
            raw=raw if raw is not None else data,
            duration_ms=duration_ms,
        )

    @classmethod
    def fail(
        cls,
        error_code: AdapterErrorCode | str,
        error_message: str,
        *,
        provider: str = "",
        raw: Any = None,
        duration_ms: float = 0.0,
    ) -> "AdapterResult":
        code = error_code.value if isinstance(error_code, AdapterErrorCode) else error_code
        return cls(
            success=False,
            error_code=code,
            error_message=error_message,
            provider=provider,
            raw=raw,
            duration_ms=duration_ms,
        )

    def raise_for_failure(self) -> None:
        if not self.success:
            raise RuntimeError(self.error_message or self.error_code or "adapter call failed")


def error_message_from_payload(payload: Any, default: str = "business failure") -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "errmsg", "detail"):
            value = payload.get(key)
            if value:
                return str(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("message", "error", "errmsg", "detail"):
                value = data.get(key)
                if value:
                    return str(value)
    for attr in ("message", "error", "detail"):
        value = getattr(payload, attr, None)
        if value:
            return str(value)
    return default


def is_malformed_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("malformed") is True


def is_failed_status(status: Any) -> bool:
    if status is None:
        return False
    return str(status).lower() in {
        "failed",
        "fail",
        "error",
        "rejected",
        "blocked",
        "business_failure",
    }


def is_success_code(code: Any) -> bool:
    return code in (None, 0, "0", 200, "200", "success", "SUCCESS")


def classify_exception(exc: Exception) -> AdapterErrorCode:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in name or "timeout" in message:
        return AdapterErrorCode.TIMEOUT
    if any(token in name for token in ("connection", "network", "httpstatus", "request")):
        return AdapterErrorCode.SERVICE_UNAVAILABLE
    if any(token in message for token in ("unavailable", "connection", "network", "http error")):
        return AdapterErrorCode.SERVICE_UNAVAILABLE
    return AdapterErrorCode.UNKNOWN_ERROR


async def run_adapter_call(
    provider: str,
    operation: Callable[[], Awaitable[Any]],
    parser: Callable[[Any, float], AdapterResult],
) -> AdapterResult:
    start = time.perf_counter()
    try:
        raw = await operation()
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        return AdapterResult.fail(
            classify_exception(exc),
            str(exc),
            provider=provider,
            duration_ms=duration_ms,
        )
    duration_ms = (time.perf_counter() - start) * 1000
    return parser(raw, duration_ms)
