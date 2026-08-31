"""Compatibility shim: offline test fakes now live in providers/fakes."""

from __future__ import annotations

from ..providers.fakes import (
    FakeDisciplineKnowledge,
    FakeEvents,
    FakeGraph,
    FakeLLM,
    FakeRecommendation,
    FakeRetrieval,
    FakeSandbox,
    FakeScope,
    FakeStudentModeling,
)
