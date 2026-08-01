"""Canonical teacher-facing capabilities for the preparation assistant.

Buttons and natural-language messages use the same action tokens.  The
tokens are deliberately an orchestration boundary, not model-facing tools:
the model may only plan a constrained action after the server has resolved
the action and its scope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


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
    # Natural-language "one-click" wording is an explicit teacher decision
    # for a whole-course action, so it should use the same atomic apply path
    # as the corresponding button rather than stop at a pending proposal.
    apply_immediately: bool = False


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
    """Resolve natural language to one of the five capabilities.

    This intentionally uses transparent, deterministic language cues.  The
    actual teaching requirement remains in ``instruction`` and is supplied to
    the capability planner.  Ambiguous text is never silently attached to an
    arbitrary node or bulk action.
    """
    text = (instruction or "").strip()
    has_bulk_request = bool(re.search(r"一键|全部|全量|整门|整个课程|批量|统一", text))
    action = canonical_prep_action(explicit_action)
    if explicit_action is not None and action is None:
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification="未识别该助教动作，请选择优化节点、整理结构、优化讲解或匹配 PPT。",
        )
    if action is None:
        lowered = text.lower()
        has_bulk = has_bulk_request
        # OCR appears in both title cleanup and slide matching requests.  It
        # becomes a PPT intent only when the request also names a deck/page or
        # mapping action; otherwise title cleanup takes precedence.
        has_ppt = bool(re.search(r"ppt|课件|幻灯片|映射|匹配|页码|页面", lowered))
        has_script = bool(re.search(r"讲解|讲稿|脚本|授课|作业脚本", text))
        has_structure = bool(re.search(r"课程结构|目录|知识点|节点|层级|排序|顺序|上移|下移|前移|后移|重排|删除|保留|父节点", text))
        has_title = bool(re.search(r"标题|题目|命名|名称|用词|ocr", lowered))

        if has_ppt:
            action = PrepAction.MATCH_PPT
        elif has_script:
            action = (
                PrepAction.OPTIMIZE_ALL_SCRIPTS
                if has_bulk else PrepAction.OPTIMIZE_NODE_SCRIPT
            )
        elif has_structure:
            action = PrepAction.ORGANIZE_STRUCTURE
        elif has_title:
            action = PrepAction.OPTIMIZE_NODE_TITLE

    if action is None:
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification="我可以优化当前节点标题、整理课程结构、优化讲解脚本或匹配 PPT。请说明希望执行哪一项。",
        )
    if action in {PrepAction.OPTIMIZE_NODE_TITLE, PrepAction.OPTIMIZE_NODE_SCRIPT} and not selected_outline_node_id:
        label = "标题" if action == PrepAction.OPTIMIZE_NODE_TITLE else "讲解脚本"
        return PrepIntent(
            action=None,
            instruction=text,
            needs_clarification=True,
            clarification=f"请先选中要优化{label}的课程节点，或改为请求全课程的一键操作。",
        )
    return PrepIntent(
        action=action,
        instruction=text,
        apply_immediately=(
            explicit_action is None
            and has_bulk_request
            and action in {PrepAction.ORGANIZE_STRUCTURE, PrepAction.OPTIMIZE_ALL_SCRIPTS}
        ),
    )


__all__ = [
    "PrepAction",
    "PrepIntent",
    "PREP_ACTION_ALIASES",
    "canonical_prep_action",
    "resolve_prep_intent",
]
