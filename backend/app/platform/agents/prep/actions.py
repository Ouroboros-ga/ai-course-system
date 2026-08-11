"""Canonical teacher-facing capabilities for the preparation assistant.

Buttons and natural-language messages use the same action tokens.  The
tokens are deliberately an orchestration boundary, not model-facing tools:
the model may only plan a constrained action after the server has resolved
the action and its scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PrepAction(str, Enum):
    """The five preparation capabilities exposed to teachers."""

    OPTIMIZE_NODE_TITLE = "optimize_node_title"
    ORGANIZE_STRUCTURE = "organize_structure"
    OPTIMIZE_NODE_SCRIPT = "optimize_node_script"
    OPTIMIZE_ALL_SCRIPTS = "optimize_all_scripts"
    MATCH_PPT = "match_ppt"


# ``optimize_scripts`` was the previous public button value.  Keep accepting
# it at the HTTP/runtime boundary while every new caller uses the unambiguous
# canonical token above.
PREP_ACTION_ALIASES: dict[str, PrepAction] = {
    "optimize_scripts": PrepAction.OPTIMIZE_ALL_SCRIPTS,
}


@dataclass(frozen=True)
class PrepIntent:
    """Result of resolving a teacher request before any planning runs."""

    action: PrepAction | None
    instruction: str
    needs_clarification: bool = False
    clarification: str = ""
    apply_immediately: bool = False


class PrepIntentDecision(BaseModel):
    """Narrow model-facing result for free-text action routing.

    The classifier can select one existing capability, but cannot name
    targets or request a write operation.  ``None`` is the only valid empty
    action and all authorization thresholds are enforced by the server.
    """

    model_config = ConfigDict(extra="forbid")

    action: PrepAction | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    apply_immediately: bool = False
    needs_clarification: bool = False
    clarification: str = Field(default="", max_length=500)


def canonical_prep_action(value: str | PrepAction | None) -> PrepAction | None:
    """Return a supported action token, including the compatibility alias."""
    if value is None:
        return None
    if isinstance(value, PrepAction):
        return value
    normalized = str(value).strip()
    if normalized in PREP_ACTION_ALIASES:
        return PREP_ACTION_ALIASES[normalized]
    try:
        return PrepAction(normalized)
    except ValueError:
        return None


def resolve_prep_intent(
    instruction: str,
    *,
    selected_outline_node_id: str | None,
    explicit_action: str | PrepAction | None = None,
) -> PrepIntent:
    """Resolve an explicit action token without guessing from free text.

    Free-text requests are classified by :class:`PrepLLMAdapter`.  Keeping
    this compatibility helper deterministic ensures legacy callers cannot
    accidentally reintroduce a keyword-based route.
    """
    text = (instruction or "").strip()
    action = canonical_prep_action(explicit_action)
    if explicit_action is not None and action is None:
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification="未识别该助教动作，请选择优化节点、整理结构、优化讲解或匹配 PPT。",
        )
    if action is None:
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification="请说明希望优化节点标题、整理课程结构、优化讲解脚本还是匹配 PPT。",
        )
    if (
        action in {PrepAction.OPTIMIZE_NODE_TITLE, PrepAction.OPTIMIZE_NODE_SCRIPT}
        and not selected_outline_node_id
    ):
        label = "标题" if action == PrepAction.OPTIMIZE_NODE_TITLE else "讲解脚本"
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification=f"请先选中要优化{label}的课程节点，或改为请求全课程批量操作。",
        )
    return PrepIntent(action=action, instruction=text)


def prep_intent_from_decision(
    instruction: str,
    *,
    selected_outline_node_id: str | None,
    decision: PrepIntentDecision,
) -> PrepIntent:
    """Apply confidence and direct-apply authorization gates server-side."""
    text = (instruction or "").strip()
    action = canonical_prep_action(decision.action)
    if action is None or decision.needs_clarification or decision.confidence < 0.70:
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification=(
                decision.clarification.strip()
                or "请具体说明希望执行的备课操作和范围。"
            ),
        )
    if (
        action in {PrepAction.OPTIMIZE_NODE_TITLE, PrepAction.OPTIMIZE_NODE_SCRIPT}
        and not selected_outline_node_id
    ):
        label = "标题" if action == PrepAction.OPTIMIZE_NODE_TITLE else "讲解脚本"
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification=f"请先选中要优化{label}的课程节点，或改为请求全课程批量操作。",
        )
    return PrepIntent(
        action=action,
        instruction=text,
        apply_immediately=(
            decision.apply_immediately
            and decision.confidence >= 0.90
            and action in {PrepAction.ORGANIZE_STRUCTURE, PrepAction.OPTIMIZE_ALL_SCRIPTS}
        ),
    )


__all__ = [
    "PrepAction",
    "PrepIntent",
    "PrepIntentDecision",
    "PREP_ACTION_ALIASES",
    "canonical_prep_action",
    "prep_intent_from_decision",
    "resolve_prep_intent",
]
