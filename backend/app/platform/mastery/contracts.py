"""
MasteryProviderResult contract and error types.

Every mastery computation returns a MasteryProviderResult that includes
evidence references, source identification, and clear error semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class MasteryProviderError:
    """Structured error information from a mastery provider.

    Parameters
    ----------
    code : str
        Stable error code (e.g. ``TIMEOUT``, ``MALFORMED_INPUT``,
        ``BUSINESS_FAILURE``, ``INTERNAL_ERROR``).
    message : str
        Human-readable error message.
    details : dict
        Additional structured error context.
    """

    code: str
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class MasteryTimeoutError(Exception):
    """Raised when a mastery provider exceeds its time budget.

    This is distinct from a business failure: the provider did not
    return a result within the allowed time.
    """

    def __init__(
        self,
        message: str = "Mastery provider timed out",
        timeout_seconds: float = 30.0,
    ):
        self.timeout_seconds = timeout_seconds
        super().__init__(message)


class MasteryMalformedError(Exception):
    """Raised when a mastery provider receives malformed input.

    The provider cannot process the request due to invalid input
    format, not because the computation failed.
    """

    def __init__(
        self,
        message: str = "Malformed input to mastery provider",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.details = details or {}
        super().__init__(message)


class MasteryBusinessFailureError(Exception):
    """Raised when a mastery provider completes but produces a
    business-level failure (e.g. insufficient data, contradictory evidence).

    The provider ran successfully but could not produce a meaningful result.
    """

    def __init__(
        self,
        message: str = "Mastery provider business failure",
        code: str = "INSUFFICIENT_DATA",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class MasteryProviderResult:
    """The standard result contract for any mastery provider.

    Every mastery/recommendation result MUST list evidence references.
    No evidence => no strong conclusion.

    Parameters
    ----------
    provider_name : str
        Name of the provider that produced this result.
    provider_version : str
        Version of the provider.
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    node_id : int or None
        Optional node-level scope.
    mastery_score : float or None
        Numeric mastery score 0.0-1.0, or None if not computable.
    mastery_level : str or None
        Mastery level label (e.g. ``beginner``, ``proficient``).
    confidence : float
        Confidence in the result 0.0-1.0.
    evidence_refs : list of str
        LearningEvidence evidence_ids supporting this result.
        MUST be non-empty for non-null mastery_score.
    error : MasteryProviderError or None
        Error information if the provider failed. None for success.
    is_timeout : bool
        True if the provider timed out.
    is_malformed : bool
        True if the input was malformed.
    is_business_failure : bool
        True if the provider produced a business failure.
    metadata : dict
        Additional structured data.
    """

    provider_name: str = ""
    provider_version: str = "1.0"
    student_id: int = 0
    course_id: int = 0
    node_id: Optional[int] = None
    mastery_score: Optional[float] = None
    mastery_level: Optional[str] = None
    confidence: float = 0.0
    evidence_refs: List[str] = field(default_factory=list)
    error: Optional[MasteryProviderError] = None
    is_timeout: bool = False
    is_malformed: bool = False
    is_business_failure: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """True if the provider produced a successful result."""
        return (
            not self.is_timeout
            and not self.is_malformed
            and not self.is_business_failure
            and self.error is None
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "node_id": self.node_id,
            "mastery_score": self.mastery_score,
            "mastery_level": self.mastery_level,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "error": self.error.to_dict() if self.error else None,
            "is_timeout": self.is_timeout,
            "is_malformed": self.is_malformed,
            "is_business_failure": self.is_business_failure,
            "metadata": self.metadata,
        }

    @staticmethod
    def success_result(
        provider_name: str,
        provider_version: str,
        student_id: int,
        course_id: int,
        mastery_score: float,
        mastery_level: str,
        confidence: float,
        evidence_refs: List[str],
        node_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Create a successful mastery result.

        Requires at least one evidence_ref for non-zero mastery.
        """
        return MasteryProviderResult(
            provider_name=provider_name,
            provider_version=provider_version,
            student_id=student_id,
            course_id=course_id,
            node_id=node_id,
            mastery_score=mastery_score,
            mastery_level=mastery_level,
            confidence=confidence,
            evidence_refs=evidence_refs,
            metadata=metadata or {},
        )

    @staticmethod
    def timeout_result(
        provider_name: str,
        student_id: int,
        course_id: int,
        timeout_seconds: float = 30.0,
    ) -> MasteryProviderResult:
        """Create a timeout result (distinct from business failure)."""
        return MasteryProviderResult(
            provider_name=provider_name,
            provider_version="",
            student_id=student_id,
            course_id=course_id,
            is_timeout=True,
            error=MasteryProviderError(
                code="TIMEOUT",
                message=f"Provider timed out after {timeout_seconds}s",
            ),
        )

    @staticmethod
    def malformed_result(
        provider_name: str,
        student_id: int,
        course_id: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Create a malformed-input result."""
        return MasteryProviderResult(
            provider_name=provider_name,
            provider_version="",
            student_id=student_id,
            course_id=course_id,
            is_malformed=True,
            error=MasteryProviderError(
                code="MALFORMED_INPUT",
                message="Input was malformed and could not be processed",
                details=details or {},
            ),
        )

    @staticmethod
    def business_failure_result(
        provider_name: str,
        student_id: int,
        course_id: int,
        code: str = "INSUFFICIENT_DATA",
        message: str = "Provider could not produce a meaningful result",
        details: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Create a business failure result."""
        return MasteryProviderResult(
            provider_name=provider_name,
            provider_version="",
            student_id=student_id,
            course_id=course_id,
            is_business_failure=True,
            error=MasteryProviderError(
                code=code,
                message=message,
                details=details or {},
            ),
        )
