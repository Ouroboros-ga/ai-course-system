"""
Safety policy provider contract tests (cross-agent entry point).

Validates that any SafetyEvaluator implements the shared safety
contract across all standard failure modes.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.product1.contracts.contract_helpers import (
    ALL_CONTRACT_MODES,
    MODE_BUSINESS_FAILURE,
    MODE_MALFORMED,
    MODE_SUCCESS,
    MODE_TIMEOUT,
    MODE_UNAVAILABLE,
    ProviderContractTest,
    mode_id,
)


class FakeSafetyProvider:
    def __init__(self, mode: str = MODE_SUCCESS):
        self.mode = mode
        self.calls = []

    async def evaluate(self, query: str, context: dict | None = None, **kwargs):
        self.calls.append({"query": query, "context": context, "kwargs": kwargs})
        if self.mode == MODE_TIMEOUT:
            raise TimeoutError("fake safety timeout")
        if self.mode == MODE_UNAVAILABLE:
            raise RuntimeError("fake safety unavailable")
        if self.mode == MODE_MALFORMED:
            return {"status": "malformed", "decision": "deny"}
        if self.mode == MODE_BUSINESS_FAILURE:
            return {"status": "business_failure", "reason": "fake safety failure", "decision": "deny"}
        return {"status": "success", "decision": "allow", "reason_code": "ok"}


class TestSafetyContract(ProviderContractTest[FakeSafetyProvider]):
    provider_type = "safety"

    def make_provider(self, mode: str) -> FakeSafetyProvider:
        return FakeSafetyProvider(mode=mode)

    async def call_provider(self, provider: FakeSafetyProvider, **kw):
        return await provider.evaluate("test query", **kw)

    @pytest.mark.parametrize("mode", ALL_CONTRACT_MODES, ids=mode_id)
    def test_safety_mode(self, mode: str):
        provider = self.make_provider(mode)
        try:
            result = asyncio.run(self.call_provider(provider))
            if mode == MODE_SUCCESS:
                self.assert_success_structure(result)
            elif mode == MODE_MALFORMED:
                self.assert_malformed_semantics(result)
            elif mode == MODE_BUSINESS_FAILURE:
                self.assert_business_failure_semantics(result)
        except (TimeoutError, RuntimeError) as exc:
            if mode == MODE_TIMEOUT:
                self.assert_timeout_semantics(None, exc)
            elif mode == MODE_UNAVAILABLE:
                self.assert_unavailable_semantics(None, exc)
            else:
                raise

    def assert_success_structure(self, result) -> None:
        assert result["status"] == "success"
        assert "decision" in result
        assert result["decision"] == "allow"

    def assert_malformed_semantics(self, result) -> None:
        assert result["status"] == "malformed"

    def assert_business_failure_semantics(self, result) -> None:
        assert result["status"] == "business_failure"
        assert "reason" in result
