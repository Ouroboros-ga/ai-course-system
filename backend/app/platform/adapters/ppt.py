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


class PPTAdapter:
    def __init__(self, client: Any, provider: str = "xfyun_ppt"):
        self.client = client
        self.provider = provider

    async def get_theme_list(self, **kwargs) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.get_theme_list(**kwargs),
            self._parse_dict_response,
        )

    async def create_ppt_task(self, **kwargs) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.create_ppt_task(**kwargs),
            self._parse_create_response,
        )

    async def wait_for_completion(self, sid: str, **kwargs) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.wait_for_completion(sid, **kwargs),
            self._parse_task_result,
        )

    async def download_ppt(self, ppt_url: str, save_path: str) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.download_ppt(ppt_url, save_path),
            self._parse_download_response,
        )

    async def get_task_progress(self, sid: str) -> AdapterResult:
        return await run_adapter_call(
            self.provider,
            lambda: self.client.get_task_progress(sid),
            self._parse_dict_response,
        )

    def _parse_dict_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw) or not isinstance(raw, dict):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "PPT response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        if not is_success_code(raw.get("code")) or is_failed_status(raw.get("status")):
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "PPT request failed"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        data = raw.get("data")
        if isinstance(data, dict) and is_failed_status(data.get("pptStatus")):
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(data, "PPT task failed"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)

    def _parse_create_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        result = self._parse_dict_response(raw, duration_ms)
        if not result.success:
            return result
        sid = raw.get("data", {}).get("sid")
        if not sid:
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "PPT create response is missing sid",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return result

    def _parse_task_result(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw) or not hasattr(raw, "status"):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "PPT task result is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        status = getattr(raw, "status", "")
        if status == "done":
            return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)
        if status == "timeout":
            return AdapterResult.fail(
                AdapterErrorCode.TIMEOUT,
                error_message_from_payload(raw, "PPT generation timed out"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        if is_failed_status(status):
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "PPT generation failed"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.fail(
            AdapterErrorCode.MALFORMED_RESPONSE,
            f"Unexpected PPT task status: {status}",
            provider=self.provider,
            raw=raw,
            duration_ms=duration_ms,
        )

    def _parse_download_response(self, raw: Any, duration_ms: float) -> AdapterResult:
        if is_malformed_payload(raw):
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "PPT download response is malformed",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        if isinstance(raw, dict):
            return AdapterResult.fail(
                AdapterErrorCode.BUSINESS_FAILURE,
                error_message_from_payload(raw, "PPT download failed"),
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        if not raw:
            return AdapterResult.fail(
                AdapterErrorCode.MALFORMED_RESPONSE,
                "PPT download returned empty path",
                provider=self.provider,
                raw=raw,
                duration_ms=duration_ms,
            )
        return AdapterResult.ok(raw, provider=self.provider, raw=raw, duration_ms=duration_ms)
