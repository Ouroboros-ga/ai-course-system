"""
P1-07 Mastery Platform Layer.

Provides the MasteryProvider protocol, MasteryProviderResult contract,
RuleBased mastery baseline, and capability-only interfaces for BKT, IRT, and DKT.

Ownership: P1-07 only.
"""

from .contracts import (
    MasteryProviderResult,
    MasteryProviderError,
    MasteryTimeoutError,
    MasteryMalformedError,
    MasteryBusinessFailureError,
)
from .provider import (
    MasteryProvider,
    ProviderCapability,
    ProviderVersion,
)
from .rule_baseline import (
    RuleBasedMasteryProvider,
    MasteryRule,
    MasteryRuleSet,
    MasteryRuleResult,
)
from .bkt_interface import BKTProvider
from .irt_interface import IRTProvider
from .dkt_interface import DKTProvider

__all__ = [
    # contracts
    "MasteryProviderResult", "MasteryProviderError",
    "MasteryTimeoutError", "MasteryMalformedError",
    "MasteryBusinessFailureError",
    # provider
    "MasteryProvider", "ProviderCapability", "ProviderVersion",
    # rule baseline
    "RuleBasedMasteryProvider", "MasteryRule", "MasteryRuleSet",
    "MasteryRuleResult",
    # interfaces
    "BKTProvider", "IRTProvider", "DKTProvider",
]
