"""Composition root for the Coding Agent.

Provides ``build_coding_graph_factory`` which returns a ``RuntimeBuilder``
closure compatible with ``AgentPlatform.register_generic``. The closure
captures the sandbox port, optional coding diagnosis port, and optional LLM
port, compiles the Coding workflow, and returns a ``RunnableGraph``.

The Coding Agent operates per-(student, course): its ``scope`` is
``(student_id, course_id)``. The same compiled graph can serve all
(student, course) pairs because the identifiers are carried in the state.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..contracts.sandbox import CodeSubmissionPort, CodingDiagnosisPort, SandboxPort
from ..contracts.teaching import TeachingLLMPort
from ..runtime.base import RunnableGraph
from .profile import build_coding_profile
from .workflow import CodingTools, build_coding_workflow

logger = logging.getLogger(__name__)


def build_coding_graph_factory(
    *,
    sandbox: SandboxPort,
    coding_diagnosis: CodingDiagnosisPort | None = None,
    code_submission: CodeSubmissionPort | None = None,
    llm: TeachingLLMPort | None = None,
) -> Callable[[tuple[str, ...]], Optional[RunnableGraph]]:
    """Return a ``RuntimeBuilder`` closure for the Coding Agent.

    Args:
        sandbox: Required ``SandboxPort`` for reading execution results.
        coding_diagnosis: Optional ``CodingDiagnosisPort`` for server-side
            diagnosis. When ``None``, the workflow skips this node.
        code_submission: CodingAgent-only source reader for the exact scoped
            submission. The workflow never stores its return value.
        llm: Optional ``TeachingLLMPort`` for LLM-based diagnosis. When
            ``None``, the workflow uses a rule-based fallback.

    Returns:
        A closure ``builder(scope) -> RunnableGraph | None``. The builder
        always returns a compiled graph (the same graph serves all scopes
        because identifiers are in the state). It returns ``None`` only if
        the workflow fails to compile.
    """
    tools = CodingTools(
        sandbox=sandbox,
        coding_diagnosis=coding_diagnosis,
        code_submission=code_submission,
        llm=llm,
    )

    try:
        compiled = build_coding_workflow(tools)
    except Exception as error:  # noqa: BLE001 - fail-closed at registration
        logger.warning("CodingAgent: workflow compilation failed: %s: %s", type(error).__name__, error)
        return lambda scope: None

    def builder(scope: tuple[str, ...]) -> Optional[RunnableGraph]:
        # The Coding graph is scope-agnostic; identifiers are in the state.
        return compiled

    return builder


__all__ = ["build_coding_graph_factory", "build_coding_profile"]
