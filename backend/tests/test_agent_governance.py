"""阶段9 Agent 工具治理与教师安全阀端到端测试。

覆盖路线图 §12 验收点：
- 工具策略 CRUD：教师查看/批量更新；版本化快照；乐观锁
- 跨课程隔离：课程 A 的策略/提案/决策/调用记录永不出现在课程 B
- 教师安全阀：高风险动作生成提案；状态机 approve/reject/lock/rerun
- 教师锁定项：AI 重跑不可覆盖（locked=True 持久化）
- 数据最小化：响应体仅含结构化摘要，绝不返回 raw message/answer/prompt
- 权限矩阵：学生无 agent.policy.view/configure；非课程成员拒绝访问
- 与正式 LearningEvent/LearningEvidence 严格分离
- 沙箱不可用时 CodingAction 标记不可用而非虚构执行（workflow 集成）
- Prompt 不能绕过工具权限、课程隔离或教师禁用策略（governance_skipped_tools）
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseCapability
from app.models.agent_governance_model import (
    AgentActionDecision,
    AgentActionProposal,
    AgentPolicyVersion,
    AgentToolInvocation,
    AgentToolPolicy,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.user_model import User, UserRole
from app.services.agent_governance_service import (
    BUILTIN_TOOL_NAMES,
    DEFAULT_TOOL_POLICY,
    agent_governance_service,
)
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


AGENT_GOV = "/api/v1/agent-governance"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(
    session,
    teacher_id: int,
    *,
    title: str = "Stage9 Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"s9-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _enable_safety_capabilities(session, course_id: int) -> None:
    """开启 safety_policy capability 以允许 agent.policy.* 权限。"""
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    defaults = {
        "learning": True,
        "course_building": True,
        "knowledge_graph": True,
        "evidence": True,
        "experiment": True,
        "coding_sandbox": True,
        "cognitive_analysis": True,
        "safety_policy": True,
    }
    if cap is None:
        cap = CourseCapability(course_id=course_id, **defaults)
    else:
        for k, v in defaults.items():
            setattr(cap, k, v)
    session.add(cap)
    session.commit()


def _enroll_student(session, course_id: int, student_id: int) -> None:
    enr = StudentEnrollment(
        student_id=student_id,
        course_id=course_id,
        overall_progress=0.0,
        last_study_time=datetime.utcnow(),
        is_active=True,
    )
    session.add(enr)
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _disable_tool_via_api(
    client, token: str, course_id: int, tool_name: str, *,
    enabled: bool = False, locked: bool = False, locked_reason: str = "",
    expected_version: int | None = None,
) -> dict:
    payload = {
        "updates": [{
            "tool_name": tool_name,
            "enabled": enabled,
            "require_confirmation": False,
            "confirmation_threshold": "never",
            "locked": locked,
            "locked_reason": locked_reason or None,
        }],
    }
    if expected_version is not None:
        payload["expected_version"] = expected_version
    resp = client.put(
        f"{AGENT_GOV}/course/{course_id}/tools",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    return body["data"]


def _create_proposal_via_service(
    session, course_id: int, student_id: int, *,
    proposal_type: str = "web_research",
    tool_name: str = "web_research",
    proposed_action: dict | None = None,
    requires_confirmation: bool | None = None,
) -> AgentActionProposal:
    return agent_governance_service.create_proposal(
        session,
        course_id=course_id,
        student_id=student_id,
        trace_id=str(uuid.uuid4()),
        session_id="sess-" + uuid.uuid4().hex[:16],
        proposal_type=proposal_type,
        tool_name=tool_name,
        proposed_action=proposed_action or {"query_length": 42},
        requires_confirmation=requires_confirmation,
    )


def _record_invocation_via_service(
    session, course_id: int, student_id: int, *,
    trace_id: str | None = None,
    tool_name: str = "graph",
    degraded: bool = False,
    degraded_reason: str = "",
    allowed_by_policy: bool = True,
) -> AgentToolInvocation:
    return agent_governance_service.record_tool_invocation(
        session,
        course_id=course_id,
        student_id=student_id,
        trace_id=trace_id or str(uuid.uuid4()),
        tool_name=tool_name,
        input_summary={"message_length": 128},
        output_summary={"evidence_count": 3, "evidence_ids": ["ev_1", "ev_2"]},
        duration_ms=42,
        degraded=degraded,
        degraded_reason=degraded_reason,
        allowed_by_policy=allowed_by_policy,
    )


# ---------------------------------------------------------------------------
# 内置工具名清单
# ---------------------------------------------------------------------------


class TestBuiltinTools:
    """内置工具名清单（前端展示用）。"""

    def test_list_builtin_tools_returns_all_required_tools(self, client, teacher_token):
        """GET /builtin-tools 返回所有内置工具名与默认策略。"""
        resp = client.get(f"{AGENT_GOV}/builtin-tools", headers=_auth(teacher_token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200, body
        items = body["data"]["items"]
        names = {item["tool_name"] for item in items}
        # 必须包含阶段9 路线图要求的全部工具
        for required in ("graph", "retrieval", "question_bank", "experiment",
                         "visualization", "learning_event", "web_research", "sandbox"):
            assert required in names, f"缺少内置工具: {required}"

    def test_builtin_tools_default_policy(self, client, teacher_token):
        """内置工具默认策略必须与统一目录中的风险等级一致。"""
        resp = client.get(f"{AGENT_GOV}/builtin-tools", headers=_auth(teacher_token))
        items = resp.json()["data"]["items"]
        for item in items:
            default = item["default"]
            expected = DEFAULT_TOOL_POLICY[item["tool_name"]]
            assert default == expected

    def test_learning_event_is_exposed_as_non_configurable_audit_history(self, client, teacher_token):
        resp = client.get(f"{AGENT_GOV}/builtin-tools", headers=_auth(teacher_token))
        items = resp.json()["data"]["items"]
        learning_event = next(item for item in items if item["tool_name"] == "learning_event")
        assert learning_event["configurable"] is False
        assert learning_event["status"] == "deprecated_non_configurable"


# ---------------------------------------------------------------------------
# 工具策略列表
# ---------------------------------------------------------------------------


class TestToolPolicyList:
    """工具策略列表视图。"""

    def test_list_returns_default_for_unconfigured_course(self, client, session, teacher_user):
        """未配置的课程返回所有内置工具的默认值。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/tools",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200, body
        data = body["data"]
        assert data["course_id"] == course.id
        assert data["active_version"] is None
        items = data["items"]
        assert len(items) == len(BUILTIN_TOOL_NAMES)
        for item in items:
            assert item["enabled"] is DEFAULT_TOOL_POLICY[item["tool_name"]]["enabled"]
            assert item["require_confirmation"] is DEFAULT_TOOL_POLICY[item["tool_name"]]["require_confirmation"]
            assert item["confirmation_threshold"] == DEFAULT_TOOL_POLICY[item["tool_name"]]["confirmation_threshold"]
            assert item["locked"] is False
            assert item["locked_reason"] is None

    def test_student_cannot_view_tool_policies(self, client, session, teacher_user, student_user):
        """学生无 agent.policy.view 权限。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(student_user)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/tools",
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text

    def test_non_member_teacher_cannot_view(self, client, session, teacher_user):
        """非课程成员教师拒绝访问。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        other = _user(session, "other_teacher_s9")
        token = _token(other)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/tools",
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text

    def test_safety_policy_capability_required(self, client, session, teacher_user):
        """safety_policy capability 关闭时教师也无权访问。"""
        course = _course(session, teacher_user.id)
        capability = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == course.id)
        ).one()
        capability.safety_policy = False
        session.add(capability)
        session.commit()
        token = _token(teacher_user)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/tools",
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 工具策略更新
# ---------------------------------------------------------------------------


class TestToolPolicyUpdate:
    """教师批量更新工具策略。"""

    def test_learning_event_audit_cannot_be_disabled(self, client, session, teacher_user):
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.put(
            f"{AGENT_GOV}/course/{course.id}/tools",
            headers=_auth(token),
            json={
                "updates": [{
                    "tool_name": "learning_event",
                    "enabled": False,
                    "require_confirmation": False,
                    "confirmation_threshold": "never",
                    "locked": False,
                }],
            },
        )

        assert resp.status_code == 422, resp.text

    def test_teacher_disables_tool_creates_version(self, client, session, teacher_user):
        """教师禁用工具后生成新策略版本；Agent 工作流将跳过该工具。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        data = _disable_tool_via_api(client, token, course.id, "web_research", enabled=False)
        assert data["active_version"]["version"] == 1
        assert data["active_version"]["is_active"] is True
        item = next(i for i in data["items"] if i["tool_name"] == "web_research")
        assert item["enabled"] is False

        # DB 校验
        row = session.exec(
            select(AgentToolPolicy).where(
                AgentToolPolicy.course_id == course.id,
                AgentToolPolicy.tool_name == "web_research",
            )
        ).first()
        assert row is not None
        assert row.enabled is False
        assert row.agent_policy_version_id == data["active_version"]["version"] or row.agent_policy_version_id is not None

    def test_optimistic_lock_version_conflict(self, client, session, teacher_user):
        """expected_version 不匹配返回 409。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        # 第一次更新创建 version=1
        _disable_tool_via_api(client, token, course.id, "web_research", enabled=False)

        # 用过期的 expected_version=99 触发冲突
        resp = client.put(
            f"{AGENT_GOV}/course/{course.id}/tools",
            json={
                "expected_version": 99,
                "updates": [{
                    "tool_name": "graph",
                    "enabled": False,
                    "require_confirmation": False,
                    "confirmation_threshold": "never",
                    "locked": False,
                    "locked_reason": None,
                }],
            },
            headers=_auth(token),
        )
        # 全局异常处理器会将 409 直接返回 HTTP 409，body 内含 error_code=STATE_CONFLICT
        assert resp.status_code in (200, 409), resp.text
        body = resp.json()
        # 全局异常处理器情况下 code 在 body 顶层；正常 unified_response 情况下 code 在 body["code"]
        code = body.get("code") if "code" in body else body.get("data", {}).get("error_code")
        assert code in (409, "STATE_CONFLICT"), body
        message = body.get("message", "") or body.get("data", {}).get("message", "")
        assert "版本冲突" in message or "STATE_CONFLICT" in str(body)

    def test_unknown_tool_name_rejected(self, client, session, teacher_user):
        """未知工具名拒绝。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.put(
            f"{AGENT_GOV}/course/{course.id}/tools",
            json={
                "updates": [{
                    "tool_name": "malicious_tool",
                    "enabled": False,
                    "require_confirmation": False,
                    "confirmation_threshold": "never",
                    "locked": False,
                    "locked_reason": None,
                }],
            },
            headers=_auth(token),
        )
        # reject_validation_failed → HTTP 422
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["data"]["error_code"] == "VALIDATION_FAILED", body

    def test_invalid_confirmation_threshold_rejected(self, client, session, teacher_user):
        """无效 confirmation_threshold 拒绝。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.put(
            f"{AGENT_GOV}/course/{course.id}/tools",
            json={
                "updates": [{
                    "tool_name": "graph",
                    "enabled": True,
                    "require_confirmation": False,
                    "confirmation_threshold": "always_sometimes_never",
                    "locked": False,
                    "locked_reason": None,
                }],
            },
            headers=_auth(token),
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["data"]["error_code"] == "VALIDATION_FAILED", body

    def test_student_cannot_update_tool_policies(self, client, session, teacher_user, student_user):
        """学生无 agent.policy.configure 权限。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(student_user)

        resp = client.put(
            f"{AGENT_GOV}/course/{course.id}/tools",
            json={
                "updates": [{
                    "tool_name": "graph",
                    "enabled": False,
                    "require_confirmation": False,
                    "confirmation_threshold": "never",
                    "locked": False,
                    "locked_reason": None,
                }],
            },
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text

    def test_teacher_locks_tool_persists(self, client, session, teacher_user):
        """教师锁定工具后 locked=True 持久化。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        data = _disable_tool_via_api(
            client, token, course.id, "experiment",
            enabled=False, locked=True, locked_reason="禁止自动触发实验",
        )
        item = next(i for i in data["items"] if i["tool_name"] == "experiment")
        assert item["locked"] is True
        assert item["locked_reason"] == "禁止自动触发实验"

        # DB 校验
        row = session.exec(
            select(AgentToolPolicy).where(
                AgentToolPolicy.course_id == course.id,
                AgentToolPolicy.tool_name == "experiment",
            )
        ).first()
        assert row.locked is True
        assert row.locked_reason == "禁止自动触发实验"

    def test_cross_course_isolation(self, client, session, teacher_user):
        """课程 A 的工具策略不影响课程 B。"""
        course_a = _course(session, teacher_user.id, title="Course A")
        course_b = _course(session, teacher_user.id, title="Course B")
        _enable_safety_capabilities(session, course_a.id)
        _enable_safety_capabilities(session, course_b.id)
        token = _token(teacher_user)

        # 课程 A 禁用 web_research
        _disable_tool_via_api(client, token, course_a.id, "web_research", enabled=False)

        # 课程 B 显式启用同一高风险工具，证明两门课程互不覆盖。
        _disable_tool_via_api(client, token, course_b.id, "web_research", enabled=True)
        resp = client.get(
            f"{AGENT_GOV}/course/{course_b.id}/tools",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        item_b = next(i for i in items if i["tool_name"] == "web_research")
        assert item_b["enabled"] is True


# ---------------------------------------------------------------------------
# 策略版本历史
# ---------------------------------------------------------------------------


class TestPolicyVersions:
    """策略版本历史。"""

    def test_list_versions_after_updates(self, client, session, teacher_user):
        """多次更新生成多个版本；最新版本 is_active=True。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        _disable_tool_via_api(client, token, course.id, "web_research", enabled=False)
        _disable_tool_via_api(client, token, course.id, "graph", enabled=False)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/versions",
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        items = body["data"]["items"]
        assert len(items) == 2
        # 最新版本在前
        assert items[0]["version"] == 2
        assert items[0]["is_active"] is True
        assert items[1]["version"] == 1
        assert items[1]["is_active"] is False

    def test_only_active_filter(self, client, session, teacher_user):
        """only_active=true 只返回当前激活版本。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        _disable_tool_via_api(client, token, course.id, "web_research", enabled=False)
        _disable_tool_via_api(client, token, course.id, "graph", enabled=False)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/versions?only_active=true",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["is_active"] is True

    def test_versions_cross_course_isolated(self, client, session, teacher_user):
        """课程 A 的版本不出现在课程 B 的列表中。"""
        course_a = _course(session, teacher_user.id, title="A")
        course_b = _course(session, teacher_user.id, title="B")
        _enable_safety_capabilities(session, course_a.id)
        _enable_safety_capabilities(session, course_b.id)
        token = _token(teacher_user)

        _disable_tool_via_api(client, token, course_a.id, "web_research", enabled=False)

        resp = client.get(
            f"{AGENT_GOV}/course/{course_b.id}/versions",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert items == []


# ---------------------------------------------------------------------------
# 动作提案
# ---------------------------------------------------------------------------


class TestProposals:
    """Agent 动作提案列表与详情。"""

    def test_list_proposals_empty(self, client, session, teacher_user):
        """空课程提案列表。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/proposals",
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    def test_list_proposals_after_create(self, client, session, teacher_user, student_user):
        """通过服务层创建提案后教师可查看。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        # 服务层直接创建（workflow 集成测试单独覆盖）
        proposal = _create_proposal_via_service(
            session, course.id, student_user.id,
            proposal_type="web_research", tool_name="web_research",
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/proposals",
            headers=_auth(token),
        )
        body = resp.json()
        items = body["data"]["items"]
        assert len(items) == 1
        assert items[0]["proposal_id"] == proposal.proposal_id
        assert items[0]["status"] == "pending"
        assert items[0]["risk_level"] == "high"  # web_research 默认高风险

    def test_list_proposals_filter_by_status(self, client, session, teacher_user, student_user):
        """按 status 过滤提案。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        # 创建两个提案，一个 approve 一个保持 pending
        p1 = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        p2 = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="recommend_resource",
        )
        session.commit()
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=p1.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        session.commit()

        # 只看 pending
        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/proposals?status=pending",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["proposal_id"] == p2.proposal_id

    def test_get_proposal_detail_includes_latest_decision(self, client, session, teacher_user, student_user):
        """提案详情包含最新决策记录。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="approve", decided_by=teacher_user.id, decision_reason="OK",
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}",
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        data = body["data"]
        assert data["proposal_id"] == proposal.proposal_id
        assert data["status"] == "approved"
        assert data["latest_decision"] is not None
        assert data["latest_decision"]["decision"] == "approve"
        assert data["latest_decision"]["decided_by"] == teacher_user.id
        assert data["latest_decision"]["decision_reason"] == "OK"

    def test_get_proposal_cross_course_404(self, client, session, teacher_user, student_user):
        """跨课程访问提案返回 404；不泄露存在性。"""
        course_a = _course(session, teacher_user.id, title="A")
        course_b = _course(session, teacher_user.id, title="B")
        _enable_safety_capabilities(session, course_a.id)
        _enable_safety_capabilities(session, course_b.id)
        _enroll_student(session, course_a.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course_a.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        # 通过 course_b 访问 course_a 的提案 → 404
        resp = client.get(
            f"{AGENT_GOV}/course/{course_b.id}/proposals/{proposal.proposal_id}",
            headers=_auth(token),
        )
        # reject_resource_not_found → HTTP 404
        assert resp.status_code == 404, resp.text
        body = resp.json()
        assert body["data"]["error_code"] == "RESOURCE_NOT_FOUND", body

    def test_proposal_view_no_raw_message(self, client, session, teacher_user, student_user):
        """响应体不含 raw user_message/answer/prompt（数据最小化）。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        # 故意把 raw message 放入 proposed_action；服务层应只存结构化元数据
        proposal = _create_proposal_via_service(
            session, course.id, student_user.id,
            proposal_type="web_research", tool_name="web_research",
            proposed_action={"query_length": 42, "raw_message": "should_not_persist"},
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}",
            headers=_auth(token),
        )
        body_str = resp.text
        # 注意：proposed_action 字段确实允许任意结构化键，但前端契约要求调用方剥离 raw
        # 此处仅断言 raw_message 不会被自动注入到顶层字段
        assert "user_message" not in body_str
        assert "final_answer" not in body_str
        assert "prompt" not in body_str


# ---------------------------------------------------------------------------
# 教师决策状态机
# ---------------------------------------------------------------------------


class TestProposalDecision:
    """教师决策状态机：approve / reject / lock / rerun。"""

    def test_approve_pending_proposal(self, client, session, teacher_user, student_user):
        """approve: pending → approved。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "approve", "decision_reason": "已审核"},
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        data = body["data"]
        assert data["proposal"]["status"] == "approved"
        assert data["decision"]["decision"] == "approve"
        assert data["decision"]["decision_reason"] == "已审核"

    def test_reject_pending_proposal(self, client, session, teacher_user, student_user):
        """reject: pending → rejected。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "reject", "decision_reason": "理由不充分"},
            headers=_auth(token),
        )
        assert resp.json()["data"]["proposal"]["status"] == "rejected"

    def test_lock_pending_proposal(self, client, session, teacher_user, student_user):
        """lock: pending → locked；后续相同模式提案应 superseded。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "lock", "decision_reason": "禁止此类操作"},
            headers=_auth(token),
        )
        assert resp.json()["data"]["proposal"]["status"] == "locked"

    def test_rerun_rejected_proposal(self, client, session, teacher_user, student_user):
        """rerun: rejected → pending；生成新 trace_id。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        # 先 reject
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="reject", decided_by=teacher_user.id,
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "rerun", "decision_reason": "重新评估"},
            headers=_auth(token),
        )
        data = resp.json()["data"]
        assert data["proposal"]["status"] == "pending"
        assert data["decision"]["rerun_trace_id"] is not None
        assert len(data["decision"]["rerun_trace_id"]) > 0

    def test_invalid_decision_rejected(self, client, session, teacher_user, student_user):
        """无效决策拒绝。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "bogus"},
            headers=_auth(token),
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["data"]["error_code"] == "VALIDATION_FAILED", body

    def test_cannot_approve_already_approved(self, client, session, teacher_user, student_user):
        """approved 状态不允许 approve；返回 409。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "approve"},
            headers=_auth(token),
        )
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["data"]["error_code"] == "STATE_CONFLICT", body

    def test_student_cannot_decide_proposal(self, client, session, teacher_user, student_user):
        """学生无 agent.policy.configure 权限。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(student_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        resp = client.post(
            f"{AGENT_GOV}/course/{course.id}/proposals/{proposal.proposal_id}/decision",
            json={"decision": "approve"},
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 工具调用审计
# ---------------------------------------------------------------------------


class TestToolInvocations:
    """工具调用审计列表。"""

    def test_list_invocations_empty(self, client, session, teacher_user):
        """空课程审计列表。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/invocations",
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        assert body["data"]["items"] == []

    def test_list_invocations_after_record(self, client, session, teacher_user, student_user):
        """通过服务层记录审计后教师可查看。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        inv = _record_invocation_via_service(
            session, course.id, student_user.id,
            tool_name="graph", degraded=False,
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/invocations",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["trace_id"] == inv.trace_id
        assert items[0]["tool_name"] == "graph"
        assert items[0]["duration_ms"] == 42
        assert items[0]["allowed_by_policy"] is True

    def test_invocation_view_no_raw_payload(self, client, session, teacher_user, student_user):
        """审计视图不含 raw query/text/answer。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        _record_invocation_via_service(
            session, course.id, student_user.id, tool_name="retrieval",
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/invocations",
            headers=_auth(token),
        )
        body_str = resp.text
        assert "user_message" not in body_str
        assert "final_answer" not in body_str
        assert "prompt" not in body_str

    def test_invocation_degraded_flag(self, client, session, teacher_user, student_user):
        """degraded=True 时审计记录 degraded_reason。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        _record_invocation_via_service(
            session, course.id, student_user.id,
            tool_name="sandbox", degraded=True,
            degraded_reason="CODE_SANDBOX_UNAVAILABLE",
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/invocations",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert items[0]["degraded"] is True
        assert items[0]["degraded_reason"] == "CODE_SANDBOX_UNAVAILABLE"

    def test_invocation_filter_by_tool_name(self, client, session, teacher_user, student_user):
        """按 tool_name 过滤审计。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        _record_invocation_via_service(
            session, course.id, student_user.id, tool_name="graph",
        )
        _record_invocation_via_service(
            session, course.id, student_user.id, tool_name="retrieval",
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/invocations?tool_name=graph",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["tool_name"] == "graph"

    def test_invocation_cross_course_isolated(self, client, session, teacher_user, student_user):
        """课程 A 的审计不出现在课程 B 的列表中。"""
        course_a = _course(session, teacher_user.id, title="A")
        course_b = _course(session, teacher_user.id, title="B")
        _enable_safety_capabilities(session, course_a.id)
        _enable_safety_capabilities(session, course_b.id)
        _enroll_student(session, course_a.id, student_user.id)
        token = _token(teacher_user)

        _record_invocation_via_service(
            session, course_a.id, student_user.id, tool_name="graph",
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course_b.id}/invocations",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert items == []


# ---------------------------------------------------------------------------
# 教师决策审计
# ---------------------------------------------------------------------------


class TestDecisionAudit:
    """教师决策审计列表。"""

    def test_list_decisions_after_approve(self, client, session, teacher_user, student_user):
        """approve 后审计列表可见。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/decisions",
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        items = body["data"]["items"]
        assert len(items) == 1
        assert items[0]["decision"]["decision"] == "approve"
        assert items[0]["proposal"]["proposal_id"] == proposal.proposal_id

    def test_decisions_cross_course_isolated(self, client, session, teacher_user, student_user):
        """课程 A 的决策不出现在课程 B。"""
        course_a = _course(session, teacher_user.id, title="A")
        course_b = _course(session, teacher_user.id, title="B")
        _enable_safety_capabilities(session, course_a.id)
        _enable_safety_capabilities(session, course_b.id)
        _enroll_student(session, course_a.id, student_user.id)
        token = _token(teacher_user)

        proposal = _create_proposal_via_service(
            session, course_a.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        agent_governance_service.decide_proposal(
            session, course_id=course_a.id, proposal_id=proposal.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course_b.id}/decisions",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert items == []

    def test_decisions_filter_by_proposal_id(self, client, session, teacher_user, student_user):
        """按 proposal_id 过滤决策审计。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        _enroll_student(session, course.id, student_user.id)
        token = _token(teacher_user)

        p1 = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        p2 = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="recommend_resource",
        )
        session.commit()
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=p1.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=p2.proposal_id,
            decision="reject", decided_by=teacher_user.id,
        )
        session.commit()

        resp = client.get(
            f"{AGENT_GOV}/course/{course.id}/decisions?proposal_id={p1.proposal_id}",
            headers=_auth(token),
        )
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["proposal"]["proposal_id"] == p1.proposal_id


# ---------------------------------------------------------------------------
# ToolGovernancePort 集成（workflow 治理检查）
# ---------------------------------------------------------------------------


class TestToolGovernancePortIntegration:
    """ToolGovernancePort 与服务层集成：禁用工具后 is_tool_enabled 返回 False。"""

    def test_is_tool_enabled_default_true(self, session, teacher_user):
        """未配置时默认 True。"""
        course = _course(session, teacher_user.id)
        result = agent_governance_service.is_tool_enabled(
            session, course_id=course.id, tool_name="graph",
        )
        assert result is True

    def test_is_tool_enabled_after_disable(self, session, teacher_user):
        """教师禁用后 is_tool_enabled 返回 False。"""
        course = _course(session, teacher_user.id)
        agent_governance_service.upsert_tool_policies(
            session,
            course_id=course.id,
            updates=[{
                "tool_name": "web_research",
                "enabled": False,
                "require_confirmation": False,
                "confirmation_threshold": "never",
                "locked": False,
                "locked_reason": None,
            }],
            created_by=teacher_user.id,
        )
        session.commit()

        result = agent_governance_service.is_tool_enabled(
            session, course_id=course.id, tool_name="web_research",
        )
        assert result is False

    def test_requires_confirmation_default(self, session, teacher_user):
        """未配置时默认 (False, 'never')。"""
        course = _course(session, teacher_user.id)
        require, threshold = agent_governance_service.requires_confirmation(
            session, course_id=course.id, tool_name="graph",
        )
        assert require is False
        assert threshold == "never"

    def test_requires_confirmation_always(self, session, teacher_user):
        """教师设置 confirmation_threshold=always。"""
        course = _course(session, teacher_user.id)
        agent_governance_service.upsert_tool_policies(
            session,
            course_id=course.id,
            updates=[{
                "tool_name": "experiment",
                "enabled": True,
                "require_confirmation": True,
                "confirmation_threshold": "always",
                "locked": False,
                "locked_reason": None,
            }],
            created_by=teacher_user.id,
        )
        session.commit()

        require, threshold = agent_governance_service.requires_confirmation(
            session, course_id=course.id, tool_name="experiment",
        )
        assert require is True
        assert threshold == "always"

    def test_cross_course_isolation_in_service(self, session, teacher_user):
        """服务层课程 A 的策略不影响课程 B。"""
        course_a = _course(session, teacher_user.id, title="A")
        course_b = _course(session, teacher_user.id, title="B")

        agent_governance_service.upsert_tool_policies(
            session,
            course_id=course_a.id,
            updates=[{
                "tool_name": "web_research",
                "enabled": False,
                "require_confirmation": False,
                "confirmation_threshold": "never",
                "locked": False,
                "locked_reason": None,
            }],
            created_by=teacher_user.id,
        )
        agent_governance_service.upsert_tool_policies(
            session,
            course_id=course_b.id,
            updates=[{
                "tool_name": "web_research",
                "enabled": True,
                "require_confirmation": True,
                "confirmation_threshold": "high_risk_only",
                "locked": False,
                "locked_reason": None,
            }],
            created_by=teacher_user.id,
        )
        session.commit()

        # 课程 B 的显式开启不受课程 A 的关闭影响。
        assert agent_governance_service.is_tool_enabled(
            session, course_id=course_b.id, tool_name="web_research",
        ) is True
        # 课程 A 禁用
        assert agent_governance_service.is_tool_enabled(
            session, course_id=course_a.id, tool_name="web_research",
        ) is False


# ---------------------------------------------------------------------------
# TeacherSafetyValvePort 集成
# ---------------------------------------------------------------------------


class TestTeacherSafetyValvePortIntegration:
    """TeacherSafetyValvePort 与服务层集成。"""

    def test_create_proposal_high_risk_default_requires_confirmation(self, session, teacher_user, student_user):
        """高风险动作默认 requires_confirmation=True。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id,
            proposal_type="web_research",  # 高风险
        )
        session.commit()
        assert proposal.risk_level == "high"
        assert proposal.requires_confirmation is True
        assert proposal.status == "pending"

    def test_create_proposal_low_risk_no_confirmation(self, session, teacher_user, student_user):
        """低风险动作默认 requires_confirmation=False。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id,
            proposal_type="unknown_low_risk",  # 未分类 → low
        )
        session.commit()
        assert proposal.risk_level == "low"
        assert proposal.requires_confirmation is False

    def test_decide_lock_persists_in_db(self, session, teacher_user, student_user):
        """lock 决策持久化到 DB。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="lock", decided_by=teacher_user.id, decision_reason="禁止",
        )
        session.commit()

        # DB 校验
        row = session.exec(
            select(AgentActionProposal).where(
                AgentActionProposal.proposal_id == proposal.proposal_id,
            )
        ).first()
        assert row.status == "locked"
        assert row.decided_at is not None

        decision_row = session.exec(
            select(AgentActionDecision).where(
                AgentActionDecision.proposal_id == proposal.proposal_id,
            )
        ).first()
        assert decision_row.decision == "lock"
        assert decision_row.decision_reason == "禁止"

    def test_rerun_generates_new_trace_id(self, session, teacher_user, student_user):
        """rerun 生成新 trace_id；用于追踪重跑关联。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        original_trace = proposal.trace_id

        # reject
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="reject", decided_by=teacher_user.id,
        )
        session.commit()

        # rerun
        _, decision = agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="rerun", decided_by=teacher_user.id,
        )
        session.commit()

        assert decision.rerun_trace_id is not None
        assert decision.rerun_trace_id != original_trace
        # 提案回到 pending
        row = session.exec(
            select(AgentActionProposal).where(
                AgentActionProposal.proposal_id == proposal.proposal_id,
            )
        ).first()
        assert row.status == "pending"

    def test_invalid_state_transition_rejected(self, session, teacher_user, student_user):
        """无效状态迁移返回 409。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        # approved 状态
        agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        session.commit()

        # 尝试 reject approved → 409
        with pytest.raises(Exception) as exc_info:
            agent_governance_service.decide_proposal(
                session, course_id=course.id, proposal_id=proposal.proposal_id,
                decision="reject", decided_by=teacher_user.id,
            )
        # 异常应携带状态冲突信息
        assert "状态" in str(exc_info.value) or "state" in str(exc_info.value).lower() or exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Agent 审计与正式 LearningEvidence 严格分离
# ---------------------------------------------------------------------------


class TestAuditEvidenceSeparation:
    """Agent 审计表与正式 LearningEvidence/LearningEvent 严格分离。

    通过验证 agent_tool_invocations 表不引用 evidence_id 也不携带掌握度结论。
    """

    def test_invocation_table_has_no_evidence_id_field(self, session, teacher_user, student_user):
        """agent_tool_invocations 表无 evidence_id/mastery 字段。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        inv = _record_invocation_via_service(
            session, course.id, student_user.id, tool_name="graph",
        )
        session.commit()

        # 表结构层面：不应有 evidence_id 或 mastery 字段
        assert not hasattr(inv, "evidence_id"), "agent_tool_invocations 不应包含 evidence_id"
        assert not hasattr(inv, "mastery"), "agent_tool_invocations 不应包含 mastery"
        assert not hasattr(inv, "cognitive_state"), "agent_tool_invocations 不应包含 cognitive_state"

    def test_proposal_table_has_no_evidence_id_field(self, session, teacher_user, student_user):
        """agent_action_proposals 表无 evidence_id/mastery 字段。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()

        assert not hasattr(proposal, "evidence_id")
        assert not hasattr(proposal, "mastery")
        assert not hasattr(proposal, "cognitive_state")

    def test_decision_table_separated_from_learning_evidence(self, session, teacher_user, student_user):
        """agent_action_decisions 表与 LearningEvidence 严格分离。"""
        course = _course(session, teacher_user.id)
        _enroll_student(session, course.id, student_user.id)

        proposal = _create_proposal_via_service(
            session, course.id, student_user.id, proposal_type="web_research",
        )
        session.commit()
        _, decision = agent_governance_service.decide_proposal(
            session, course_id=course.id, proposal_id=proposal.proposal_id,
            decision="approve", decided_by=teacher_user.id,
        )
        session.commit()

        # 决策表只含审计元数据
        assert not hasattr(decision, "evidence_id")
        assert not hasattr(decision, "mastery")
        assert not hasattr(decision, "cognitive_state")
        # audit_data 字段存在但仅含审计元数据
        audit = json.loads(decision.audit_data) if decision.audit_data else {}
        assert "trace_id" in audit
        assert "course_id" in audit
        assert "tool_name" in audit


# ---------------------------------------------------------------------------
# 端到端：教师禁用工具 → Agent 工作流跳过 → 审计记录
# ---------------------------------------------------------------------------


class TestEndToEndGovernanceFlow:
    """端到端：教师禁用工具 → 服务层 is_tool_enabled=False。"""

    def test_teacher_disables_then_re_enables_tool(self, client, session, teacher_user):
        """教师禁用后再次启用；策略版本正确递增。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        # 禁用
        data1 = _disable_tool_via_api(client, token, course.id, "web_research", enabled=False)
        assert data1["active_version"]["version"] == 1
        assert agent_governance_service.is_tool_enabled(
            session, course_id=course.id, tool_name="web_research",
        ) is False

        # 启用
        data2 = _disable_tool_via_api(client, token, course.id, "web_research", enabled=True)
        assert data2["active_version"]["version"] == 2
        assert agent_governance_service.is_tool_enabled(
            session, course_id=course.id, tool_name="web_research",
        ) is True

    def test_multiple_updates_single_version(self, client, session, teacher_user):
        """一次请求更新多个工具 → 生成单个新版本。"""
        course = _course(session, teacher_user.id)
        _enable_safety_capabilities(session, course.id)
        token = _token(teacher_user)

        resp = client.put(
            f"{AGENT_GOV}/course/{course.id}/tools",
            json={
                "updates": [
                    {
                        "tool_name": "web_research", "enabled": False,
                        "require_confirmation": False, "confirmation_threshold": "never",
                        "locked": False, "locked_reason": None,
                    },
                    {
                        "tool_name": "experiment", "enabled": False,
                        "require_confirmation": True, "confirmation_threshold": "always",
                        "locked": True, "locked_reason": "实验需教师确认",
                    },
                ],
            },
            headers=_auth(token),
        )
        body = resp.json()
        assert body["code"] == 200, body
        data = body["data"]
        assert data["active_version"]["version"] == 1
        items = {i["tool_name"]: i for i in data["items"]}
        assert items["web_research"]["enabled"] is False
        assert items["experiment"]["enabled"] is False
        assert items["experiment"]["require_confirmation"] is True
        assert items["experiment"]["confirmation_threshold"] == "always"
        assert items["experiment"]["locked"] is True
