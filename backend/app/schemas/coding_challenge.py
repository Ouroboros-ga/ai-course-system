"""Strict structured-output contracts for conversational coding challenges."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CodingChallengeTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    stdin: str = Field(max_length=10_000)
    expected_stdout: str = Field(max_length=10_000)


class CodingChallengeDraft(BaseModel):
    """AI draft kept in memory until all Judge0 quality gates pass."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=4, max_length=200)
    statement: str = Field(min_length=20, max_length=5_000)
    language: Literal["python3", "javascript", "cpp", "c", "java"]
    starter_code: str = Field(min_length=1, max_length=20_000)
    public_samples: list[CodingChallengeTestCase] = Field(min_length=1, max_length=4)
    hidden_tests: list[CodingChallengeTestCase] = Field(min_length=1, max_length=12)
    reference_solution: str = Field(min_length=1, max_length=50_000)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    estimated_minutes: int = Field(default=10, ge=3, le=45)

    @model_validator(mode="after")
    def validate_test_identity(self) -> CodingChallengeDraft:
        cases = [*self.public_samples, *self.hidden_tests]
        identities = [(case.stdin, case.expected_stdout) for case in cases]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate_test_case")
        if self.starter_code.strip() == self.reference_solution.strip():
            raise ValueError("starter_matches_reference")
        return self


class CodingChallengeDecision(BaseModel):
    """LLM recommendation only; the server applies every authorization gate."""

    model_config = ConfigDict(extra="forbid")

    code_practice_fit: bool
    pedagogical_timing: Literal["now", "later", "not_applicable"]
    target_concept_id: str | None = Field(default=None, max_length=128)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    reason_codes: list[str] = Field(default_factory=list, max_length=5)


__all__ = [
    "CodingChallengeDecision",
    "CodingChallengeDraft",
    "CodingChallengeTestCase",
]
