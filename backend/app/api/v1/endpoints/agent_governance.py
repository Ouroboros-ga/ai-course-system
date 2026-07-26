"""阶段9 Agent 工具治理与教师安全阀 API 路由。

路由前缀：
- /api/v1/agent-governance/course/{course_id}/tools                    工具策略列表/批量更新
- /api/v1/agent-governance/course/{course_id}/versions                 策略版本历史
- /api/v1/agent-governance/course/{course_id}/proposals                提案列表
- /api/v1/agent-governance/course/{course_id}/proposals/{proposal_id}  提案详情
- /api/v1/agent-governance/course/{course_id}/proposals/{proposal_id}/decision  教师决策
- /api/v1/agent-governance/course/{course_id}/invocations              工具调用审计
- /api/v1/agent-governance/course/{course_id}/decisions                教师决策审计

权限模型：
- agent.policy.view: 教师查看工具策略/提案/决策/调用审计
- agent.policy.configure: 教师更新工具策略/决策提案
- 跨课程严格隔离：所有查询按 course_id 过滤
- 数据最小化：响应体仅含结构化摘要，绝不返回 raw message/answer/prompt
- 与正式 LearningEvent/LearningEvidence 严格分离，仅用于运营审计与教师治理
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_validation_failed,
    unified_response,
)
from app.core.security import get_current_user
from app.models.agent_governance_model import (
    AgentActionDecision,
    AgentActionProposal,
    AgentPolicyVersion,
    AgentToolInvocation,
    AgentToolPolicy,
)
from app.models.database import get_session
from app.schemas.agent import (
    BUILTIN_TOOL_NAMES,
    ProposalDecisionRequest,
    ToolInvocationView,
    ToolPolicyBatchView,
    ToolPolicyItem,
    ToolPolicyUpdateRequest,
    ToolPolicyVersionView,
    ProposalView,
    ProposalDecisionView,
    ProposalDetailWithDecisionView,
)
from app.services.agent_governance_service import (
    DEFAULT_TOOL_POLICY,
    agent_governance_service,
)
from app.services.course_access_service import require_course_permission


agent_governance_router = APIRouter()


# ---------------------------------------------------------------------------
# 序列化助手
# ---------------------------------------------------------------------------


def _serialize_version(version: AgentPolicyVersion) -> dict[str, Any]:
    return {
        "version": version.version,
        "summary": version.summary,
        "is_active": bool(version.is_active),
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else "",
    }


def _serialize_tool_policy(row: AgentToolPolicy) -> dict[str, Any]:
    return {
        "tool_name": row.tool_name,
        "enabled": bool(row.enabled),
        "require_confirmation": bool(row.require_confirmation),
        "confirmation_threshold": row.confirmation_threshold,
        "locked": bool(row.locked),
        "locked_reason": row.locked_reason,
    }


def _serialize_proposal(p: AgentActionProposal) -> dict[str, Any]:
    try:
        proposed_action = json.loads(p.proposed_action) if p.proposed_action else {}
    except Exception:  # noqa: BLE001 -- 容错损坏 JSON
        proposed_action = {}
    return {
        "proposal_id": p.proposal_id,
        "trace_id": p.trace_id,
        "student_id": p.student_id,
        "course_id": p.course_id,
        "session_id": p.session_id,
        "proposal_type": p.proposal_type,
        "tool_name": p.tool_name,
        "proposed_action": proposed_action,
        "risk_level": p.risk_level,
        "requires_confirmation": bool(p.requires_confirmation),
        "status": p.status,
        "agent_policy_version_id": p.agent_policy_version_id,
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
    }


def _serialize_decision(d: AgentActionDecision) -> dict[str, Any]:
    return {
        "proposal_id": d.proposal_id,
        "decision": d.decision,
        "decided_by": d.decided_by,
        "decision_reason": d.decision_reason,
        "rerun_trace_id": d.rerun_trace_id,
        "decided_at": d.decided_at.isoformat() if d.decided_at else "",
    }


def _serialize_invocation(inv: AgentToolInvocation) -> dict[str, Any]:
    try:
        input_summary = json.loads(inv.input_summary) if inv.input_summary else {}
    except Exception:  # noqa: BLE001
        input_summary = {}
    try:
        output_summary = json.loads(inv.output_summary) if inv.output_summary else {}
    except Exception:  # noqa: BLE001
        output_summary = {}
    return {
        "trace_id": inv.trace_id,
        "student_id": inv.student_id,
        "course_id": inv.course_id,
        "tool_name": inv.tool_name,
        "invoked_at": inv.invoked_at.isoformat() if inv.invoked_at else "",
        "input_summary": input_summary,
        "output_summary": output_summary,
        "duration_ms": inv.duration_ms,
        "degraded": bool(inv.degraded),
        "degraded_reason": inv.degraded_reason,
        "allowed_by_policy": bool(inv.allowed_by_policy),
        "agent_policy_version_id": inv.agent_policy_version_id,
    }


def _build_tool_policy_view(
    session: Session, *, course_id: int,
) -> dict[str, Any]:
    """构造工具策略批次视图：DB 行 + 缺失内置工具默认值。"""
    rows = agent_governance_service.list_tool_policies(session, course_id=course_id)
    rows_by_name = {row.tool_name: row for row in rows}
    items: list[dict[str, Any]] = []
    for name in BUILTIN_TOOL_NAMES:
        row = rows_by_name.get(name)
        if row is None:
            default = DEFAULT_TOOL_POLICY.get(name, {})
            items.append({
                "tool_name": name,
                "enabled": bool(default.get("enabled", True)),
                "require_confirmation": bool(default.get("require_confirmation", False)),
                "confirmation_threshold": str(default.get("confirmation_threshold", "never")),
                "locked": False,
                "locked_reason": None,
            })
        else:
            items.append(_serialize_tool_policy(row))
    active_version = agent_governance_service.get_active_policy_version(session, course_id=course_id)
    return {
        "course_id": course_id,
        "active_version": _serialize_version(active_version) if active_version else None,
        "items": items,
    }


# ---------------------------------------------------------------------------
# 工具策略
# ---------------------------------------------------------------------------


@agent_governance_router.get("/course/{course_id}/tools")
async def list_tool_policies(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看课程工具策略；包含未配置的内置工具默认值。"""
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    view = _build_tool_policy_view(session, course_id=course_id)
    return unified_response(200, "获取工具策略成功", view)


@agent_governance_router.put("/course/{course_id}/tools")
async def update_tool_policies(
    course_id: int,
    payload: ToolPolicyUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师批量更新工具策略；生成新策略版本快照。

    - expected_version 用于乐观锁；不匹配返回 409 VERSION_CONFLICT
    - locked=True 的策略行教师显式调用本方法可解锁
    - 教师禁用工具后 Agent 工作流跳过该工具节点并记录 governance_skipped_tools
    """
    require_course_permission(session, current_user, course_id, "agent.policy.configure")
    user_id = int(current_user["user_id"])
    updates_dicts: list[dict[str, Any]] = [item.model_dump() for item in payload.updates]
    version, rows = agent_governance_service.upsert_tool_policies(
        session,
        course_id=course_id,
        updates=updates_dicts,
        created_by=user_id,
        expected_version=payload.expected_version,
    )
    session.commit()
    return unified_response(
        200,
        "工具策略已更新",
        {
            "course_id": course_id,
            "active_version": _serialize_version(version),
            "items": [_serialize_tool_policy(row) for row in rows],
        },
    )


# ---------------------------------------------------------------------------
# 策略版本
# ---------------------------------------------------------------------------


@agent_governance_router.get("/course/{course_id}/versions")
async def list_policy_versions(
    course_id: int,
    only_active: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看策略版本历史；支持回滚所需的版本对比。"""
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    stmt = select(AgentPolicyVersion).where(
        AgentPolicyVersion.course_id == course_id,
    )
    if only_active:
        stmt = stmt.where(AgentPolicyVersion.is_active == True)  # noqa: E712
    stmt = stmt.order_by(AgentPolicyVersion.version.desc()).limit(limit)
    rows = list(session.exec(stmt).all())
    return unified_response(
        200,
        "获取策略版本成功",
        {
            "course_id": course_id,
            "items": [_serialize_version(row) for row in rows],
            "total": len(rows),
        },
    )


# ---------------------------------------------------------------------------
# 动作提案
# ---------------------------------------------------------------------------


@agent_governance_router.get("/course/{course_id}/proposals")
async def list_proposals(
    course_id: int,
    status: Optional[str] = Query(default=None, description="pending|approved|rejected|locked|superseded"),
    student_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看课程 Agent 动作提案；按 course_id 严格隔离。"""
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    rows = agent_governance_service.list_proposals(
        session,
        course_id=course_id,
        status=status,
        student_id=student_id,
        limit=limit,
    )
    return unified_response(
        200,
        "获取提案列表成功",
        {
            "course_id": course_id,
            "items": [_serialize_proposal(p) for p in rows],
            "total": len(rows),
        },
    )


@agent_governance_router.get("/course/{course_id}/proposals/{proposal_id}")
async def get_proposal(
    course_id: int,
    proposal_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看提案详情，包含最新决策记录。"""
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    proposal = agent_governance_service.get_proposal(
        session, course_id=course_id, proposal_id=proposal_id,
    )
    # 查询最新决策
    decision_stmt = (
        select(AgentActionDecision)
        .where(AgentActionDecision.proposal_id == proposal_id)
        .order_by(AgentActionDecision.decided_at.desc())
        .limit(1)
    )
    latest_decision = session.exec(decision_stmt).first()
    view = _serialize_proposal(proposal)
    view["latest_decision"] = _serialize_decision(latest_decision) if latest_decision else None
    return unified_response(200, "获取提案详情成功", view)


@agent_governance_router.post("/course/{course_id}/proposals/{proposal_id}/decision")
async def decide_proposal(
    course_id: int,
    proposal_id: str,
    payload: ProposalDecisionRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师决策提案：approve / reject / lock / rerun。

    - approve: pending → approved；Agent 可继续执行
    - reject:  pending → rejected
    - lock:    pending → locked；后续相同模式提案自动 superseded
    - rerun:   rejected/superseded → pending；生成新 trace_id
    """
    require_course_permission(session, current_user, course_id, "agent.policy.configure")
    user_id = int(current_user["user_id"])
    proposal, decision_record = agent_governance_service.decide_proposal(
        session,
        course_id=course_id,
        proposal_id=proposal_id,
        decision=payload.decision,
        decided_by=user_id,
        decision_reason=payload.decision_reason,
    )
    session.commit()
    return unified_response(
        200,
        "提案决策已记录",
        {
            "proposal": _serialize_proposal(proposal),
            "decision": _serialize_decision(decision_record),
        },
    )


# ---------------------------------------------------------------------------
# 工具调用审计
# ---------------------------------------------------------------------------


@agent_governance_router.get("/course/{course_id}/invocations")
async def list_invocations(
    course_id: int,
    trace_id: Optional[str] = Query(default=None),
    tool_name: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看工具调用审计；按 course_id 严格隔离。"""
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    rows = agent_governance_service.list_invocations(
        session,
        course_id=course_id,
        trace_id=trace_id,
        tool_name=tool_name,
        limit=limit,
    )
    return unified_response(
        200,
        "获取工具调用审计成功",
        {
            "course_id": course_id,
            "items": [_serialize_invocation(inv) for inv in rows],
            "total": len(rows),
        },
    )


# ---------------------------------------------------------------------------
# 教师决策审计
# ---------------------------------------------------------------------------


@agent_governance_router.get("/course/{course_id}/decisions")
async def list_decisions(
    course_id: int,
    proposal_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师查看决策审计记录；按 course_id 严格隔离。"""
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    pairs = agent_governance_service.list_decisions(
        session,
        course_id=course_id,
        proposal_id=proposal_id,
        limit=limit,
    )
    items = []
    for decision, proposal in pairs:
        items.append({
            "decision": _serialize_decision(decision),
            "proposal": _serialize_proposal(proposal),
        })
    return unified_response(
        200,
        "获取决策审计成功",
        {
            "course_id": course_id,
            "items": items,
            "total": len(items),
        },
    )


# ---------------------------------------------------------------------------
# 内置工具名清单（前端展示用）
# ---------------------------------------------------------------------------


@agent_governance_router.get("/builtin-tools")
async def list_builtin_tools(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """返回内置工具名清单与默认策略；用于前端配置面板初始化。"""
    return unified_response(
        200,
        "获取内置工具清单成功",
        {
            "items": [
                {
                    "tool_name": name,
                    "default": DEFAULT_TOOL_POLICY.get(name, {
                        "enabled": True,
                        "require_confirmation": False,
                        "confirmation_threshold": "never",
                    }),
                }
                for name in BUILTIN_TOOL_NAMES
            ],
        },
    )
