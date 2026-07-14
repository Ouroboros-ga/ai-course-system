"""
Mastery provider contract tests (cross-agent entry point).

Validates that any MasteryProvider implements the shared mastery/
cognition contract across all standard failure modes.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.tests.product1.contracts.contract_helpers import (
    ALL_CONTRACT_MODES,
    MODE_BUSINESS_FAILURE,
    MODE_MALFORMED,
    MODE_SUCCESS,
    MODE_TIMEOUT,
    MODE_UNAVAILABLE,
    ProviderContractTest,
    mode_id,
)


class FakeMasteryProvider:
    def __init__(self, mode: str = MODE_SUCCESS):
        self.mode = mode
        self.calls = []

    async def estimate(self, student_id: str, course_id: str, events: list | None = None, **kwargs):
        self.calls.append({
            "student_id": student_id,
            "course_id": course_id,
            "events": events,
            "kwargs": kwargs,
        })
        if self.mode == MODE_TIMEOUT:
            raise TimeoutError("fake mastery timeout")
        if self.mode == MODE_UNAVAILABLE:
            raise RuntimeError("fake mastery unavailable")
        if self.mode == MODE_MALFORMED:
            return {"status": "malformed", "mastery": {}}
        if self.mode == MODE_BUSINESS_FAILURE:
            return {"status": "business_failure", "reason": "fake mastery failure", "mastery": {}}
        return {
            "status": "success",
            "mastery": {"concept_1": 0.85, "concept_2": 0.60},
            "evidence_refs": ["evt-001", "evt-002"],
        }


class TestMasteryContract(ProviderContractTest[FakeMasteryProvider]):
    provider_type = "mastery"

    def make_provider(self, mode: str) -> FakeMasteryProvider:
        return FakeMasteryProvider(mode=mode)

    async def call_provider(self, provider: FakeMasteryProvider, **kw):
        return await provider.estimate("student-1", "course-1", **kw)

    @pytest.mark.parametrize("mode", ALL_CONTRACT_MODES, ids=mode_id)
    def test_mastery_mode(self, mode: str):
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
        assert "mastery" in result
        assert len(result["mastery"]) > 0
        assert "evidence_refs" in result

    def assert_malformed_semantics(self, result) -> None:
        assert result["status"] == "malformed"

    def assert_business_failure_semantics(self, result) -> None:
        assert result["status"] == "business_failure"
        assert "reason" in result
