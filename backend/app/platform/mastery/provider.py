"""
MasteryProvider protocol and capability declarations.

Defines the Provider INTERFACE only. Concrete implementations (BKT, IRT, DKT)
are capability-only interfaces defined in their respective modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .contracts import MasteryProviderResult


@dataclass(frozen=True)
class ProviderCapability:
    """Declares what a provider can do and its constraints.

    Parameters
    ----------
    name : str
        Human-readable capability name.
    version : str
        Provider version.
    supports_course_level : bool
        True if the provider can assess course-level mastery.
    supports_node_level : bool
        True if the provider can assess node-level mastery.
    requires_evidence : bool
        True if the provider requires evidence input.
    requires_historical_data : bool
        True if the provider needs historical event data.
    max_input_events : int or None
        Maximum number of events the provider can accept.
    timeout_seconds : float
        Default timeout for this provider.
    metadata : dict
        Additional capability information.
    """

    name: str = ""
    version: str = "1.0"
    supports_course_level: bool = True
    supports_node_level: bool = True
    requires_evidence: bool = True
    requires_historical_data: bool = False
    max_input_events: Optional[int] = None
    timeout_seconds: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderVersion:
    """Version information for a mastery provider."""

    major: int = 1
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@runtime_checkable
class MasteryProvider(Protocol):
    """Protocol for mastery assessment providers.

    Every provider must implement ``compute`` returning a
    ``MasteryProviderResult``, and ``get_capability`` returning a
    ``ProviderCapability``.

    This is a structural typing Protocol -- implementations do not
    need to inherit from it, they just need to provide the methods.
    """

    def compute(
        self,
        student_id: int,
        course_id: int,
        node_id: Optional[int] = None,
        evidence_refs: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Compute mastery for a student on a given scope.

        Parameters
        ----------
        student_id : int
            The student user ID.
        course_id : int
            The course ID.
        node_id : int or None
            Optional node-level scope.
        evidence_refs : list of str or None
            LearningEvidence evidence_ids to use.
        metadata : dict or None
            Additional context for the computation.

        Returns
        -------
        MasteryProviderResult
            The result with evidence references, error semantics, and
            confidence.
        """
        ...

    def get_capability(self) -> ProviderCapability:
        """Return the provider's capability declaration.

        Returns
        -------
        ProviderCapability
        """
        ...


class AbstractMasteryProvider(ABC):
    """Abstract base class for mastery providers.

    Provides a default ``get_capability`` implementation and enforces
    the ``compute`` method signature. Use either this ABC or the
    ``MasteryProvider`` Protocol; this ABC is recommended for providers
    that need shared infrastructure.
    """

    def __init__(
        self,
        name: str = "abstract_provider",
        version: str = "1.0.0",
    ):
        self._name = name
        self._version = version

    @abstractmethod
    def compute(
        self,
        student_id: int,
        course_id: int,
        node_id: Optional[int] = None,
        evidence_refs: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Compute mastery for a student on a given scope."""
        ...

    def get_capability(self) -> ProviderCapability:
        """Return the provider's capability declaration."""
        return ProviderCapability(
            name=self._name,
            version=self._version,
        )
