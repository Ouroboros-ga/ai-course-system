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
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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
from app.models.teaching_constraint_model import (
    TeachingConstraintEvaluation,
    TeachingConstraintPolicyVersion,
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
from app.services.teaching_constraint_service import teaching_constraint_service
from app.platform.agents.edu.constraints import canonicalize_snapshot
from app.platform.agents.tools.catalog import DEFAULT_TOOL_CATALOG


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
    descriptor = DEFAULT_TOOL_CATALOG.get(row.tool_name)
    return {
        "tool_name": row.tool_name,
        "enabled": bool(row.enabled),
        "require_confirmation": bool(row.require_confirmation),
        "confirmation_threshold": row.confirmation_threshold,
        "locked": bool(row.locked),
        "locked_reason": row.locked_reason,
        "configurable": descriptor.configurable if descriptor is not None else True,
        "status": descriptor.status if descriptor is not None else "active",
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
        descriptor = DEFAULT_TOOL_CATALOG.get(name)
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
                "configurable": descriptor.configurable if descriptor is not None else True,
                "status": descriptor.status if descriptor is not None else "active",
            })
        else:
            items.append(_serialize_tool_policy(row))
    active_version = agent_governance_service.get_active_policy_version(session, course_id=course_id)
    return {
        "course_id": course_id,
        "active_version": _serialize_version(active_version) if active_version else None,
        "items": items,
    }


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TeachingConstraintUpdateRequest(_StrictRequest):
    expected_version: int = Field(ge=0)
    change_reason: str = Field(min_length=3, max_length=256)
    policy: dict[str, Any]


class TeachingConstraintRollbackRequest(_StrictRequest):
    target_version: int = Field(ge=1)
    expected_version: int = Field(ge=1)
    change_reason: str = Field(min_length=3, max_length=256)


class TeachingConstraintPreviewRequest(_StrictRequest):
    student_id: int = Field(ge=1)
    intent: Literal[
        "concept_question",
        "code_debugging",
        "learning_guidance",
        "other",
    ] | None = None
    concept_id: str | None = Field(default=None, min_length=1, max_length=128)
    policy: dict[str, Any] | None = None


def _serialize_constraint_version(
    row: TeachingConstraintPolicyVersion | None,
    *,
    include_policy: bool,
) -> dict[str, Any]:
    if row is None:
        snapshot = teaching_constraint_service.parse_snapshot(None)
        return {
            "id": None,
            "version": 0,
            "policy_hash": None,
            "is_active": True,
            "change_reason": "platform default",
            "created_by": None,
            "created_at": None,
            "policy": snapshot.model_dump(mode="json") if include_policy else None,
        }
    payload = {
        "id": row.id,
        "version": row.version,
        "policy_hash": row.policy_hash,
        "is_active": bool(row.is_active),
        "change_reason": row.change_reason,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_policy:
        payload["policy"] = teaching_constraint_service.parse_snapshot(row).model_dump(
            mode="json"
        )
    return payload


def _safe_json_array(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _serialize_constraint_evaluation(
    row: TeachingConstraintEvaluation,
) -> dict[str, Any]:
    return {
        "trace_id": row.trace_id,
        "course_id": row.course_id,
        "student_id": row.student_id,
        "policy_version_id": row.policy_version_id,
        "effective_level": row.effective_level,
        "matched_rule_ids": _safe_json_array(row.matched_rule_ids),
        "applied_scopes": _safe_json_array(row.applied_scopes),
        "decision_codes": _safe_json_array(row.decision_codes),
        "context_input_chars": row.context_input_chars,
        "context_output_chars": row.context_output_chars,
        "valid_citation_count": row.valid_citation_count,
        "enforcement_status": row.enforcement_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
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
# TeachingAgent hardness / constraint policy
# ---------------------------------------------------------------------------


@agent_governance_router.get("/course/{course_id}/teaching-constraints")
async def get_teaching_constraints(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    current = teaching_constraint_service.get_current(session, course_id=course_id)
    return unified_response(
        200,
        "获取教学约束策略成功",
        {
            "course_id": course_id,
            "active_version": _serialize_constraint_version(
                current, include_policy=True
            ),
        },
    )


@agent_governance_router.put("/course/{course_id}/teaching-constraints")
async def update_teaching_constraints(
    course_id: int,
    payload: TeachingConstraintUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(
        session, current_user, course_id, "agent.policy.configure"
    )
    row = teaching_constraint_service.save(
        session,
        course_id=course_id,
        expected_version=payload.expected_version,
        actor_user_id=int(current_user["user_id"]),
        change_reason=payload.change_reason,
        payload=payload.policy,
    )
    session.commit()
    session.refresh(row)
    return unified_response(
        200,
        "教学约束策略已保存",
        {
            "course_id": course_id,
            "active_version": _serialize_constraint_version(row, include_policy=True),
        },
    )


@agent_governance_router.get(
    "/course/{course_id}/teaching-constraints/versions"
)
async def list_teaching_constraint_versions(
    course_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    rows = teaching_constraint_service.list_versions(
        session, course_id=course_id, limit=limit
    )
    return unified_response(
        200,
        "获取教学约束版本成功",
        {
            "course_id": course_id,
            "items": [
                _serialize_constraint_version(row, include_policy=False) for row in rows
            ],
            "total": len(rows),
        },
    )


@agent_governance_router.post(
    "/course/{course_id}/teaching-constraints/rollback"
)
async def rollback_teaching_constraints(
    course_id: int,
    payload: TeachingConstraintRollbackRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(
        session, current_user, course_id, "agent.policy.configure"
    )
    row = teaching_constraint_service.rollback(
        session,
        course_id=course_id,
        target_version=payload.target_version,
        expected_version=payload.expected_version,
        actor_user_id=int(current_user["user_id"]),
        change_reason=payload.change_reason,
    )
    session.commit()
    session.refresh(row)
    return unified_response(
        200,
        "教学约束策略已回滚为新版本",
        {
            "course_id": course_id,
            "active_version": _serialize_constraint_version(row, include_policy=True),
        },
    )


@agent_governance_router.post(
    "/course/{course_id}/teaching-constraints/preview"
)
async def preview_teaching_constraints(
    course_id: int,
    payload: TeachingConstraintPreviewRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    snapshot = None
    if payload.policy is not None:
        try:
            snapshot = canonicalize_snapshot(payload.policy)
        except ValidationError as exc:
            reject_validation_failed(
                "教学约束策略不符合契约",
                details={
                    "reason_code": "CONSTRAINT_POLICY_INVALID",
                    "errors": exc.errors(include_url=False, include_input=False),
                },
            )
    envelope = teaching_constraint_service.preview(
        session,
        course_id=course_id,
        student_id=payload.student_id,
        snapshot=snapshot,
        intent=payload.intent,
        concept_id=payload.concept_id,
    )
    return unified_response(
        200,
        "教学约束预览成功",
        {
            "course_id": course_id,
            "student_id": payload.student_id,
            "effective": envelope.model_dump(mode="json"),
        },
    )


@agent_governance_router.get(
    "/course/{course_id}/teaching-constraints/evaluations"
)
async def list_teaching_constraint_evaluations(
    course_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "agent.policy.view")
    rows = teaching_constraint_service.list_evaluations(
        session, course_id=course_id, limit=limit
    )
    return unified_response(
        200,
        "获取教学约束执行审计成功",
        {
            "course_id": course_id,
            "items": [_serialize_constraint_evaluation(row) for row in rows],
            "total": len(rows),
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

    - approve: pending → approved；同时为高风险动作创建 TaskRecord 异步执行
    - reject:  pending → rejected
    - lock:    pending → locked；后续相同模式提案自动 superseded
    - rerun:   rejected/superseded → pending；生成新 trace_id

    P0-2.6: approve 高风险动作时创建 TaskRecord，使动作执行可追踪、可重试、可取消，
    不再依赖"接口返回成功、后台无执行"的隐性约定。
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

    # approve 时创建 TaskRecord 异步执行高风险动作
    task_view = None
    if payload.decision == "approve" and proposal.status == "approved":
        try:
            from app.services.task_service import TaskCreateRequest, task_service
            proposed_action = json.loads(proposal.proposed_action) if proposal.proposed_action else {}
            task_view = task_service.create_task(session, TaskCreateRequest(
                task_type="agent_action_execute",
                owner_user_id=user_id,
                course_id=course_id,
                input_summary=(
                    f"Agent 高风险动作执行: {proposal.proposal_type} "
                    f"(proposal={proposal.proposal_id[:16]})"
                )[:500],
                input_payload={
                    "course_id": course_id,
                    "proposal_id": proposal.proposal_id,
                    "proposal_type": proposal.proposal_type,
                    "tool_name": proposal.tool_name,
                    "trace_id": proposal.trace_id,
                    "student_id": proposal.student_id,
                    "session_id": proposal.session_id,
                    "proposed_action": proposed_action,
                    "decided_by": user_id,
                },
                resource_links=[
                    {"resource_kind": "course", "resource_id": str(course_id), "relation": "input"},
                    {"resource_kind": "agent_proposal", "resource_id": proposal.proposal_id, "relation": "input"},
                    {"resource_kind": "agent_decision", "resource_id": str(decision_record.id), "relation": "input"},
                ],
            ))
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to create agent_action_execute TaskRecord for proposal %s; "
                "approval recorded but action not dispatched",
                proposal.proposal_id,
                exc_info=True,
            )

    session.commit()

    # 异步触发 worker 执行
    if task_view is not None:
        try:
            from app.platform.tasks.worker import local_task_worker
            from app.models.database import session_factory as _session_factory
            if local_task_worker.has_handler("agent_action_execute"):
                local_task_worker.submit(
                    _session_factory,
                    task_view.task_id,
                    {
                        "course_id": course_id,
                        "proposal_id": proposal.proposal_id,
                        "proposal_type": proposal.proposal_type,
                    },
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to submit agent_action_execute task %s to worker; stays pending",
                task_view.task_id,
                exc_info=True,
            )

    return unified_response(
        200,
        "提案决策已记录",
        {
            "proposal": _serialize_proposal(proposal),
            "decision": _serialize_decision(decision_record),
            "task_id": task_view.task_id if task_view else None,
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
                    "configurable": (
                        DEFAULT_TOOL_CATALOG.get(name).configurable
                        if DEFAULT_TOOL_CATALOG.get(name) is not None else True
                    ),
                    "status": (
                        DEFAULT_TOOL_CATALOG.get(name).status
                        if DEFAULT_TOOL_CATALOG.get(name) is not None else "active"
                    ),
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
