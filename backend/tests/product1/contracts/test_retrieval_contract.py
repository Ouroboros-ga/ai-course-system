"""
Retrieval provider contract tests (cross-agent entry point).

Validates that any RetrieverProvider implements the shared retrieval
contract across all standard failure modes.  Fakes only -- real
retrieval quality is measured by gold benchmarks.
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


class FakeRetrieverProvider:
    def __init__(self, mode: str = MODE_SUCCESS):
        self.mode = mode
        self.calls = []

    async def retrieve(self, query: str, scope: dict | None = None, **kwargs):
        self.calls.append({"query": query, "scope": scope, "kwargs": kwargs})
        if self.mode == MODE_TIMEOUT:
            raise TimeoutError("fake retriever timeout")
        if self.mode == MODE_UNAVAILABLE:
            raise RuntimeError("fake retriever unavailable")
        if self.mode == MODE_MALFORMED:
            return {"status": "malformed", "chunks": []}
        if self.mode == MODE_BUSINESS_FAILURE:
            return {"status": "business_failure", "reason": "fake retrieval failure", "chunks": []}
        return {
            "status": "success",
            "chunks": [{"id": "c1", "text": "retrieved chunk", "score": 0.95}],
        }


class TestRetrievalContract(ProviderContractTest[FakeRetrieverProvider]):
    provider_type = "retriever"

    def make_provider(self, mode: str) -> FakeRetrieverProvider:
        return FakeRetrieverProvider(mode=mode)

    async def call_provider(self, provider: FakeRetrieverProvider, **kw):
        return await provider.retrieve("test query", **kw)

    @pytest.mark.parametrize("mode", ALL_CONTRACT_MODES, ids=mode_id)
    def test_retrieval_mode(self, mode: str):
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
        assert "chunks" in result
        assert len(result["chunks"]) > 0

    def assert_malformed_semantics(self, result) -> None:
        assert result["status"] == "malformed"

    def assert_business_failure_semantics(self, result) -> None:
        assert result["status"] == "business_failure"
        assert "reason" in result
