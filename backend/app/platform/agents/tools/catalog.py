"""ToolCatalog: tool description and assembly metadata.

Per the adopted migration plan:
    ``ToolCatalog`` manages descriptions and assembly metadata, NOT all live
    tool instances. Live instances are owned by each agent's composition
    root (e.g. ``TeachingTools`` for Edu). The catalog is consulted at
    assembly time to know which tools exist, their risk level, and which
    permissions they require; it is NOT consulted at workflow execution time.

Design:
    - ``ToolDescriptor``: immutable metadata about one tool (name, risk,
      required permission, default enabled state).
    - ``ToolCatalog``: registry of descriptors, looked up by tool name.
    - The catalog does NOT instantiate ports; it only describes them.
    - Workflow nodes still receive live port instances via the agent's
      ``Tools`` dataclass (e.g. ``TeachingTools``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class ToolRisk(str, Enum):
    """Risk classification for tool governance.

    - ``LOW``: read-only tools that never modify state (graph, retrieval,
      cognition, question_bank, experiment, visualization, sandbox_read).
    - ``MEDIUM``: tools that record audit/context but do not modify learning
      state (learning_events, conversation_context).
    - ``HIGH``: tools that may trigger external side effects or modify
      recommendations (web_research, trigger_experiment, change_topic).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolDescriptor:
    """Immutable metadata describing one tool for assembly and governance."""

    name: str
    risk: ToolRisk
    required_permission: str = ""
    default_enabled: bool = True
    description: str = ""
    configurable: bool = True
    status: str = "active"

    @property
    def requires_teacher_confirmation(self) -> bool:
        """Whether the tool triggers the teacher safety valve by default."""
        return self.risk is ToolRisk.HIGH


class ToolCatalog:
    """Registry of ``ToolDescriptor`` entries, keyed by tool name.

    The catalog is populated at bootstrap time and is read-only afterwards.
    It is consulted by:
        - composition roots, to know which tools to wire
        - governance ports, to know default-enabled state and risk level
        - tracing/observability, to render human-readable tool names

    The catalog does NOT hold live port instances and does NOT participate
    in workflow execution.
    """

    def __init__(self) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._descriptors:
            raise ValueError(f"tool already registered: {descriptor.name}")
        self._descriptors[descriptor.name] = descriptor

    def get(self, name: str) -> ToolDescriptor | None:
        return self._descriptors.get(name)

    def is_enabled_by_default(self, name: str) -> bool:
        descriptor = self._descriptors.get(name)
        return descriptor.default_enabled if descriptor else True

    def risk_of(self, name: str) -> ToolRisk:
        descriptor = self._descriptors.get(name)
        return descriptor.risk if descriptor else ToolRisk.LOW

    def names(self) -> list[str]:
        return list(self._descriptors.keys())

    def all_descriptors(self) -> Mapping[str, ToolDescriptor]:
        return dict(self._descriptors)


def build_default_catalog() -> ToolCatalog:
    """Build the default catalog covering all currently-known tools.

    This is the single source of truth for tool risk classification. New
    agents (Prep, Coding) register additional descriptors here as they are
    onboarded; Commit 6 and Commit 7 will extend this list.
    """
    catalog = ToolCatalog()
    # Read-only context tools (LOW risk)
    for name in (
        "graph", "retrieval", "cognition", "question_bank",
        "experiment", "visualization", "sandbox", "coding_diagnosis",
        "student_history", "student_modeling", "recommendation",
    ):
        catalog.register(ToolDescriptor(
            name=name, risk=ToolRisk.LOW,
            description=f"read-only {name} context tool",
        ))
    # Audit/context recording tools (MEDIUM risk)
    catalog.register(ToolDescriptor(
        name="conversation_context",
        risk=ToolRisk.MEDIUM,
        description="conversation context recording tool",
    ))
    # Runtime audit is a platform invariant. Historical per-course rows remain
    # readable, but this old switch cannot disable platform audit collection.
    catalog.register(ToolDescriptor(
        name="learning_event",
        risk=ToolRisk.MEDIUM,
        description="legacy learning-event policy; runtime audit is platform-managed",
        configurable=False,
        status="deprecated_non_configurable",
    ))
    # 出题工具（MEDIUM risk）：写 question_generation_drafts 草稿，须经教师审核 approve
    catalog.register(ToolDescriptor(
        name="question_generation", risk=ToolRisk.MEDIUM,
        default_enabled=True,
        description="AI 出题工具：依据知识点/认知/提问信号生成草稿，教师审核后进题库",
    ))
    # High-risk tools that trigger the teacher safety valve
    for name in ("web_research", "trigger_experiment", "change_topic"):
        catalog.register(ToolDescriptor(
            name=name, risk=ToolRisk.HIGH,
            default_enabled=False,
            description=f"high-risk {name} tool; requires teacher confirmation",
        ))
    return catalog


# One immutable catalog instance is the public source for schemas, services
# and composition metadata. Runtime allow decisions still intersect Course
# Access, teacher policy and the per-request hardness envelope.
DEFAULT_TOOL_CATALOG = build_default_catalog()
BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(DEFAULT_TOOL_CATALOG.names())


__all__ = [
    "ToolRisk",
    "ToolDescriptor",
    "ToolCatalog",
    "build_default_catalog",
    "DEFAULT_TOOL_CATALOG",
    "BUILTIN_TOOL_NAMES",
]
