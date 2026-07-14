"""
IRT (Item Response Theory) capability INTERFACE only.

This module defines the interface contract for an IRT provider.
Do NOT implement or claim IRT model quality without data, gold labels,
baseline comparison, and approval.

IRT implementation requires:
1. Stable quiz/item data with difficulty discrimination parameters.
2. Gold labels for student ability at each assessment point.
3. Baseline comparison against RuleBasedMasteryProvider.
4. Explicit approval from P1-00 and P1-10.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import MasteryProviderResult
from .provider import AbstractMasteryProvider, ProviderCapability


class IRTProvider(AbstractMasteryProvider):
    """Capability interface for Item Response Theory.

    IRT models student ability as a latent continuous parameter (theta)
    estimated from item responses. Items are characterized by difficulty,
    discrimination, and (optionally) guessing parameters.

    NOTE: This is an INTERFACE ONLY. No implementation is provided.
    Do not claim IRT model quality without proper validation.
    """

    def __init__(
        self,
        name: str = "irt",
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
            max_input_events=500,
            timeout_seconds=60.0,
            metadata={
                "model_type": "irt",
                "models": {
                    "1PL": "One-parameter logistic (difficulty only)",
                    "2PL": "Two-parameter logistic (difficulty + discrimination)",
                    "3PL": "Three-parameter logistic (+ guessing)",
                },
                "default_model": "2PL",
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
        """Compute mastery using IRT.

        This is an INTERFACE-ONLY declaration: no IRT algorithm is
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
            Additional context including IRT model type and item parameters.

        Returns
        -------
        MasteryProviderResult
        """
        raise TypeError(
            "IRTProvider.compute is interface-only: no implementation. "
            "IRT requires stable item data, gold labels, baseline "
            "comparison, and P1-00/P1-10 approval before implementation."
        )
