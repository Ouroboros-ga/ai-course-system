"""
BKT (Bayesian Knowledge Tracing) capability INTERFACE only.

This module defines the interface contract for a BKT provider.
Do NOT implement or claim BKT model quality without data, gold labels,
baseline comparison, and approval.

BKT implementation requires:
1. Stable LearningEvent data with sufficient coverage.
2. Gold labels for knowledge state at each step.
3. Baseline comparison against RuleBasedMasteryProvider.
4. Explicit approval from P1-00 and P1-10.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import MasteryProviderResult
from .provider import AbstractMasteryProvider, ProviderCapability


class BKTProvider(AbstractMasteryProvider):
    """Capability interface for Bayesian Knowledge Tracing.

    BKT models student knowledge as a latent binary state (known/not-known)
    that transitions based on learning opportunities and observations.

    NOTE: This is an INTERFACE ONLY. No implementation is provided.
    Do not claim BKT model quality without proper validation.
    """

    def __init__(
        self,
        name: str = "bkt",
        version: str = "1.0.0",
    ):
        super().__init__(name=name, version=version)

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self._name,
            version=self._version,
            supports_course_level=True,
            supports_node_level=True,
            requires_evidence=True,
            requires_historical_data=True,
            max_input_events=1000,
            timeout_seconds=60.0,
            metadata={
                "model_type": "bkt",
                "parameters": {
                    "p_learn": "Probability of transitioning from not-known to known",
                    "p_guess": "Probability of correct answer when not known",
                    "p_slip": "Probability of incorrect answer when known",
                    "p_init": "Initial probability of knowledge",
                },
                "status": "interface_only",
                "implementation": "not_implemented",
                "requires_approval": True,
            },
        )

    def compute(
        self,
        student_id: int,
        course_id: int,
        node_id: Optional[int] = None,
        evidence_refs: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MasteryProviderResult:
        """Compute mastery using BKT.

        This is an INTERFACE-ONLY declaration: no BKT algorithm is
        implemented.  Calling ``compute`` raises ``TypeError`` so the
        provider cannot be used for real assessment until a concrete,
        validated implementation is approved by P1-00 and P1-10.

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
            Additional context including BKT parameters.

        Returns
        -------
        MasteryProviderResult
        """
        raise TypeError(
            "BKTProvider.compute is interface-only: no implementation. "
            "BKT requires stable event data, gold labels, baseline "
            "comparison, and P1-00/P1-10 approval before implementation."
        )
