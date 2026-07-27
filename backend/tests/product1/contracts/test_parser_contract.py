"""
Parser provider contract tests (cross-agent entry point).

These tests validate that any ParserProvider implementation conforms to
the shared contract (success, timeout, unavailable, malformed,
business-failure, partial modes).  They exercise fakes only and do NOT
prove real parsing quality -- that is the domain of frozen gold benchmarks
in tests/benchmarks/product1/.
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


class FakeParserProvider:
    """Minimal parser fake for contract testing."""

    def __init__(self, mode: str = MODE_SUCCESS):
        self.mode = mode
        self.calls = []

    async def parse(self, source: bytes, **kwargs):
        self.calls.append({"source_len": len(source), "kwargs": kwargs})
        if self.mode == MODE_TIMEOUT:
            raise TimeoutError("fake parser timeout")
        if self.mode == MODE_UNAVAILABLE:
            raise RuntimeError("fake parser service unavailable")
        if self.mode == MODE_MALFORMED:
            return {"status": "malformed", "blocks": []}
        if self.mode == MODE_BUSINESS_FAILURE:
            return {"status": "business_failure", "reason": "fake business failure", "blocks": []}
        return {"status": "success", "blocks": [{"id": "b1", "text": "test block"}]}


class TestParserContract(ProviderContractTest[FakeParserProvider]):
    provider_type = "parser"

    def make_provider(self, mode: str) -> FakeParserProvider:
        return FakeParserProvider(mode=mode)

    async def call_provider(self, provider: FakeParserProvider, **kw):
        return await provider.parse(b"fake source bytes", **kw)

    @pytest.mark.parametrize("mode", ALL_CONTRACT_MODES, ids=mode_id)
    def test_parser_mode(self, mode: str):
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
        assert "blocks" in result
        assert len(result["blocks"]) > 0

    def assert_malformed_semantics(self, result) -> None:
        assert result["status"] == "malformed"

    def assert_business_failure_semantics(self, result) -> None:
        assert result["status"] == "business_failure"
        assert "reason" in result
