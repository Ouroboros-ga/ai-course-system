"""
DKT (Deep Knowledge Tracing) capability INTERFACE only.

This module defines the interface contract for a DKT provider.
Do NOT implement or claim DKT model quality without data, gold labels,
baseline comparison, and approval.

DKT implementation requires:
1. Large-scale LearningEvent data with sufficient coverage.
2. Gold labels for knowledge state across time steps.
3. Baseline comparison against RuleBasedMasteryProvider.
4. Offline evaluation with held-out test data.
5. Explicit approval from P1-00 and P1-10.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import MasteryProviderResult
from .provider import AbstractMasteryProvider, ProviderCapability


class DKTProvider(AbstractMasteryProvider):
    """Capability interface for Deep Knowledge Tracing.

    DKT uses recurrent neural networks (RNNs/LSTMs/Transformers) to model
    student knowledge from sequences of learning interactions.

    NOTE: This is an INTERFACE ONLY. No implementation is provided.
    Do not claim DKT (or LSTM/HMM/Transformer) model quality without
    proper validation, gold labels, baseline comparison, and approval.
    """

    def __init__(
        self,
        name: str = "dkt",
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
            max_input_events=10000,
            timeout_seconds=120.0,
            metadata={
                "model_type": "dkt",
                "architecture": "lstm",
                "alternatives": ["transformer", "hmm", "grn"],
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
        """Compute mastery using DKT.

        This is an INTERFACE-ONLY declaration: no DKT (or LSTM/HMM/
        Transformer) algorithm is implemented.  Calling ``compute``
        raises ``TypeError`` so the provider cannot be used for real
        assessment until a concrete, validated implementation is
        approved by P1-00 and P1-10.

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
            Additional context including model hyperparameters and
            sequence configuration.

        Returns
        -------
        MasteryProviderResult
        """
        raise TypeError(
            "DKTProvider.compute is interface-only: no implementation. "
            "DKT requires large-scale event data, gold labels, offline "
            "evaluation, and P1-00/P1-10 approval before implementation."
        )
