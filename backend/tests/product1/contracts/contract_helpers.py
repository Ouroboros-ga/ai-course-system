"""
Shared Product 1 contract-test framework.

Provides base classes, assertion helpers, and mode-parameterization
utilities for all P1 contract tests.  Every fake/contract test here
proves control flow, error semantics, and side-effect isolation --
NOT real model quality.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

import pytest

# ---------------------------------------------------------------------------
# Failure-mode parameterisation (shared pattern across all providers)
# ---------------------------------------------------------------------------

MODE_SUCCESS = "success"
MODE_TIMEOUT = "timeout"
MODE_UNAVAILABLE = "service_unavailable"
MODE_MALFORMED = "malformed"
MODE_BUSINESS_FAILURE = "business_failure"
MODE_PARTIAL = "partial"
MODE_CONFLICT = "conflict"

STANDARD_FAILURE_MODES = [
    MODE_TIMEOUT,
    MODE_UNAVAILABLE,
    MODE_MALFORMED,
    MODE_BUSINESS_FAILURE,
]

ALL_CONTRACT_MODES = [MODE_SUCCESS, *STANDARD_FAILURE_MODES, MODE_PARTIAL]


def mode_id(val: Any) -> str:
    """pytest parameter id helper for mode strings."""
    return str(val)


# ---------------------------------------------------------------------------
# Quality gate report schema  (machine-readable JSON)
# ---------------------------------------------------------------------------


class GateDecision(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    BLOCKED = "blocked"


@dataclass
class CheckResult:
    name: str
    status: GateDecision
    detail: str = ""
    passed: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class QualityGateReport:
    """Machine-readable G1/G2/... gate report."""

    gate: str  # e.g. "G1", "G2"
    agent: str = "P1-10"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    baseline_sha: str = ""
    branch: str = ""
    worktree_path: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    conclusion: GateDecision = GateDecision.SKIP
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "agent": self.agent,
            "timestamp": self.timestamp,
            "baseline_sha": self.baseline_sha,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "checks": [asdict(c) for c in self.checks],
            "conclusion": self.conclusion.value,
            "summary": self.summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def add_check(self, name: str, status: GateDecision, **kw: Any) -> None:
        self.checks.append(CheckResult(name=name, status=status, **kw))

    def finalize(self) -> GateDecision:
        if any(c.status == GateDecision.FAIL for c in self.checks):
            self.conclusion = GateDecision.FAIL
        elif any(c.status == GateDecision.BLOCKED for c in self.checks):
            self.conclusion = GateDecision.BLOCKED
        elif all(c.status == GateDecision.PASS for c in self.checks):
            self.conclusion = GateDecision.PASS
        else:
            self.conclusion = GateDecision.SKIP
        return self.conclusion


# ---------------------------------------------------------------------------
# Abstract contract-test base
# ---------------------------------------------------------------------------

T = TypeVar("T")


class ProviderContractTest(ABC, Generic[T]):
    """Base class for a provider-agnostic contract test.

    Subclasses override ``make_provider(mode)`` to return an instance of
    the provider under test in the given mode, and ``call_provider(p, **kw)``
    to exercise the contract method.
    """

    provider_type: ClassVar[str] = ""  # e.g. "parser", "retriever"

    @abstractmethod
    def make_provider(self, mode: str) -> T:
        """Return a provider instance configured with *mode*."""
        ...

    @abstractmethod
    def call_provider(self, provider: T, **kw: Any) -> Any:
        """Exercise the contract method on *provider*."""
        ...

    # -- contract-level invariants -------------------------------------------

    def assert_success_structure(self, result: Any) -> None:
        """Override to assert shape of a success result."""
        assert result is not None, f"{self.provider_type}: success result must not be None"

    def assert_timeout_semantics(self, result: Any, exc: Exception) -> None:
        """Override to assert timeout-specific semantics."""
        assert isinstance(exc, TimeoutError), f"{self.provider_type}: expected TimeoutError"

    def assert_unavailable_semantics(self, result: Any, exc: Exception) -> None:
        """Override to assert unavailable-specific semantics."""
        assert "unavailable" in str(exc).lower(), f"{self.provider_type}: expected unavailable"

    def assert_malformed_semantics(self, result: Any) -> None:
        """Override to assert malformed-specific semantics."""
        assert result is not None

    def assert_business_failure_semantics(self, result: Any) -> None:
        """Override to assert business-failure-specific semantics."""
        assert result is not None
