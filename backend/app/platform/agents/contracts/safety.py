"""Content-safety guard port for the TeachingAgent.

``SafetyGuardPort`` runs the course safety fence (G6 ``evaluate_content_safety``)
as the first content-level gate of the teaching workflow, right after request
validation. It returns the same structured decision as the standalone
``POST /safety/course/{id}/evaluate`` endpoint so the workflow can:

- allow: continue to intent parsing and answer generation;
- require_confirmation: the action/content is held for teacher decision;
- block: stop the workflow and return a compliance reply to the learner.

The port is strictly isolated by ``course_id``; a missing/inactive policy
(policy is None / draft / conflict) always resolves to allow, preserving the
existing fail-open behaviour for courses that never configured a policy.
"""

from __future__ import annotations

from typing import Mapping, Optional, Protocol


class SafetyGuardPort(Protocol):
    """内容安全闸门端口：在教学问答主链路上执行课程安全围栏评估。

    - check_content(course_id, user_message, user_id, tool_target) → Mapping：
      返回与 ``/safety/course/{id}/evaluate`` 一致的结构化决策：
      allowed / action / requires_confirmation / reason / decision_factors /
      keyword_matched / compliance_reply / policy_version
    - 端口实现按 course_id 严格隔离；无策略或策略未启用时放行（fail-open）。
    - 阻断时 ``compliance_reply`` 携带预设的思政合规回答文案，供工作流直接返回。
    """

    async def check_content(
        self,
        *,
        course_id: str,
        user_message: str,
        user_id: Optional[str] = None,
        tool_target: Optional[str] = None,
    ) -> Mapping[str, Any]: ...


__all__ = ["SafetyGuardPort"]
