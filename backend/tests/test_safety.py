"""G6 课程安全围栏与沙箱治理测试

验证：
- 关键词不能作为唯一允许或阻断依据
- 网安/CTF 课程中合规教学内容在白名单和隔离环境内可以正常回答
- 基础课程中高风险请求能够被阻断或要求教师确认
- 教师不能关闭平台级隔离、审计、资源上限
- 所有策略修改、命中、放行、阻断均可审计
- CTF 使用隔离靶场而非公共互联网
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlmodel import select

from app.core.security import get_password_hash, create_access_token
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.models.safety_policy_model import (
    CourseSafetyPolicy,
    CourseSandboxPolicy,
    SafetyAuditLog,
    CourseType,
    SandboxPreset,
    NetworkMode,
    SafetyPolicyStatus,
    AuditEventType,
    PLATFORM_HARD_LIMITS,
)
from app.services.course_access_service import (
    establish_course_access_baseline,
    activate_student_membership,
)
from app.services.safety_guard_service import evaluate_content_safety


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"safety-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="Safety Course",
        title="Safety Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _setup_course(session, teacher, student=None, enable_safety=False, enable_sandbox=False):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    if student:
        activate_student_membership(session, course.id, student.id)
    # 启用安全策略和沙箱能力
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    if cap:
        if enable_safety:
            cap.safety_policy = True
        if enable_sandbox:
            cap.coding_sandbox = True
            cap.experiment = True
        session.add(cap)
    session.commit()
    return course


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
    })


def _create_safety_policy(session, course_id, **kwargs):
    policy = CourseSafetyPolicy(course_id=course_id, status=SafetyPolicyStatus.ACTIVE, **kwargs)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return policy


def _create_sandbox_policy(session, course_id, **kwargs):
    policy = CourseSandboxPolicy(course_id=course_id, **kwargs)
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return policy


# ==================== 安全评估引擎测试 ====================

class TestSafetyEvaluation:
    """安全评估引擎单元测试"""

    def test_keyword_not_sole_basis_for_block(self, session):
        """关键词不能作为唯一阻断依据"""
        teacher = _user(session, "safety_kw_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "safety_kw_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # 中等风险关键词在教学语境下应放行
        decision = evaluate_content_safety(
            session, course.id, "请解释什么是端口扫描的原理",
            user_id=student.id,
        )
        assert decision.allowed is True
        assert "关键词" in decision.reason or "教学" in decision.reason

    def test_basic_course_high_risk_blocked(self, session):
        """基础课程中高风险内容被阻断"""
        teacher = _user(session, "safety_basic_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "safety_basic_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_content_safety(
            session, course.id, "如何进行提权操作",
            user_id=student.id,
        )
        assert decision.allowed is False
        assert decision.requires_confirmation is True
        assert "提权" in (decision.keyword_matched or "")

    def test_ctf_course_allows_in_isolated_environment(self, session):
        """CTF 隔离课程中合规教学内容在隔离环境内允许"""
        teacher = _user(session, "safety_ctf_teacher")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        _create_safety_policy(session, course.id, course_type=CourseType.CTF)
        _create_sandbox_policy(session, course.id, sandbox_preset=SandboxPreset.CTF_ISOLATED)
        student = _user(session, "safety_ctf_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_content_safety(
            session, course.id, "学习CTF中的漏洞利用原理",
            user_id=student.id,
        )
        assert decision.allowed is True
        assert "CTF" in decision.reason or "隔离" in decision.reason

    def test_ctf_without_isolation_requires_confirmation(self, session):
        """CTF 课程但无隔离靶场需教师确认"""
        teacher = _user(session, "safety_ctf_noi_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.CTF)
        # 不创建沙箱策略（无隔离靶场）
        student = _user(session, "safety_ctf_noi_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_content_safety(
            session, course.id, "学习CTF中的漏洞利用",
            user_id=student.id,
        )
        assert decision.allowed is False
        assert decision.requires_confirmation is True

    def test_cybersecurity_allows_in_range_with_whitelist(self, session):
        """网安课程在隔离靶场和白名单内允许"""
        teacher = _user(session, "safety_cyber_teacher")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        _create_safety_policy(
            session, course.id,
            course_type=CourseType.CYBERSECURITY,
            course_whitelist=["target.cyber.lab"],
        )
        _create_sandbox_policy(
            session, course.id,
            sandbox_preset=SandboxPreset.CYBERSECURITY_RANGE,
            network_mode=NetworkMode.ISOLATED_RANGE,
        )
        student = _user(session, "safety_cyber_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # 工具目标在白名单内 -> 允许
        decision = evaluate_content_safety(
            session, course.id, "学习SQL注入的原理",
            user_id=student.id, tool_target="target.cyber.lab",
        )
        assert decision.allowed is True

    def test_cybersecurity_blocks_non_whitelist_target(self, session):
        """网安课程：工具目标不在白名单内被阻断"""
        teacher = _user(session, "safety_cyber_nw_teacher")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        _create_safety_policy(
            session, course.id,
            course_type=CourseType.CYBERSECURITY,
            course_whitelist=["target.cyber.lab"],
        )
        _create_sandbox_policy(
            session, course.id,
            sandbox_preset=SandboxPreset.CYBERSECURITY_RANGE,
        )
        student = _user(session, "safety_cyber_nw_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_content_safety(
            session, course.id, "学习SQL注入",
            user_id=student.id, tool_target="evil.example.com",
        )
        assert decision.allowed is False

    def test_audit_log_recorded_on_block(self, session):
        """阻断事件被审计记录"""
        teacher = _user(session, "safety_audit_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "safety_audit_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        evaluate_content_safety(
            session, course.id, "如何编写恶意代码",
            user_id=student.id,
        )

        logs = session.exec(
            select(SafetyAuditLog).where(SafetyAuditLog.course_id == course.id)
        ).all()
        assert len(logs) > 0
        assert any(log.event_type == AuditEventType.BLOCK for log in logs)

    def test_no_policy_defaults_to_allow(self, session):
        """无安全策略时默认允许"""
        teacher = _user(session, "safety_nopolicy_teacher")
        course = _setup_course(session, teacher)
        student = _user(session, "safety_nopolicy_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_content_safety(
            session, course.id, "任何问题",
            user_id=student.id,
        )
        assert decision.allowed is True


# ==================== API 集成测试 ====================

class TestSafetyAPI:
    """安全策略 API 集成测试"""

    def test_get_safety_policy_requires_membership(self, client, session):
        """获取安全策略需要权限"""
        teacher = _user(session, "safety_api_nomem")
        course = _course(session, teacher.id)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/safety/course/{course.id}/safety-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403


# ==================== 工具权限校验链测试 ====================

class TestToolPermissionChain:
    """工具权限校验链测试

    Agent请求工具 -> 校验课程权限 -> 校验安全策略 -> 校验目标白名单 -> 校验沙箱能力 -> 执行/确认/拒绝
    """

    def test_platform_hard_limit_blocks_dangerous_ops(self, session):
        """平台硬边界：始终禁止危险操作"""
        from app.services.safety_guard_service import evaluate_tool_call

        teacher = _user(session, "tool_hard_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "tool_hard_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_tool_call(
            session, course.id,
            tool_name="code_execute",
            tool_params={"command": "rm -rf /"},
            user_id=student.id,
        )
        assert decision.allowed is False
        assert "平台硬边界" in decision.reason

    def test_basic_course_blocks_network_tool(self, session):
        """基础课程禁止网络工具对真实目标"""
        from app.services.safety_guard_service import evaluate_tool_call

        teacher = _user(session, "tool_basic_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "tool_basic_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_tool_call(
            session, course.id,
            tool_name="port_scan",
            tool_target="example.com",
            user_id=student.id,
        )
        assert decision.allowed is False
        assert "基础" in decision.reason or "禁止" in decision.reason

    def test_cybersecurity_allows_whitelist_target(self, session):
        """网安课程允许白名单目标"""
        from app.services.safety_guard_service import evaluate_tool_call

        teacher = _user(session, "tool_cyber_teacher")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        _create_safety_policy(
            session, course.id,
            course_type=CourseType.CYBERSECURITY,
            course_whitelist=["target.cyber.lab"],
        )
        _create_sandbox_policy(
            session, course.id,
            sandbox_preset=SandboxPreset.CYBERSECURITY_RANGE,
        )
        student = _user(session, "tool_cyber_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_tool_call(
            session, course.id,
            tool_name="port_scan",
            tool_target="target.cyber.lab",
            user_id=student.id,
        )
        # 高风险工具需确认，但不是拒绝
        assert decision.requires_confirmation is True

    def test_cybersecurity_blocks_non_whitelist_target(self, session):
        """网安课程拒绝非白名单目标"""
        from app.services.safety_guard_service import evaluate_tool_call

        teacher = _user(session, "tool_cyber_nw_teacher")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        _create_safety_policy(
            session, course.id,
            course_type=CourseType.CYBERSECURITY,
            course_whitelist=["target.cyber.lab"],
        )
        _create_sandbox_policy(session, course.id, sandbox_preset=SandboxPreset.CYBERSECURITY_RANGE)
        student = _user(session, "tool_cyber_nw_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_tool_call(
            session, course.id,
            tool_name="port_scan",
            tool_target="evil.example.com",
            user_id=student.id,
        )
        assert decision.allowed is False
        assert "白名单" in decision.reason

    def test_host_path_blocked(self, session):
        """禁止访问宿主机路径"""
        from app.services.safety_guard_service import evaluate_tool_call

        teacher = _user(session, "tool_path_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "tool_path_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_tool_call(
            session, course.id,
            tool_name="file_read",
            tool_target="/etc/passwd",
            user_id=student.id,
        )
        assert decision.allowed is False
        assert "宿主机" in decision.reason

    def test_sandbox_language_check(self, session):
        """沙箱执行工具检查语言白名单"""
        from app.services.safety_guard_service import evaluate_tool_call

        teacher = _user(session, "tool_lang_teacher")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        _create_sandbox_policy(
            session, course.id,
            sandbox_preset=SandboxPreset.BASIC_PROGRAMMING,
            allowed_languages=["python3"],
        )
        student = _user(session, "tool_lang_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # 非允许语言被拒绝
        decision = evaluate_tool_call(
            session, course.id,
            tool_name="code_execute",
            tool_params={"language": "ruby"},
            user_id=student.id,
        )
        assert decision.allowed is False
        assert "语言" in decision.reason


# ==================== AI产出安全门控测试 ====================

class TestAIContentGate:
    """AI产出安全门控测试

    AI生成 -> 安全策略检查 -> 原文与课程范围检查 -> 教师确认 -> 正式发布
    """

    def test_ai_content_requires_confirmation(self, session):
        """AI产出始终需要教师确认"""
        from app.services.safety_guard_service import evaluate_ai_content

        teacher = _user(session, "ai_gate_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "ai_gate_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_ai_content(
            session, course.id,
            content="这是AI生成的教学内容",
            source_materials=["课程原始资料A"],
            user_id=student.id,
        )
        assert decision.allowed is True
        assert decision.requires_confirmation is True
        assert "教师确认" in decision.reason

    def test_ai_content_blocked_by_safety_policy(self, session):
        """AI产出被安全策略拒绝"""
        from app.services.safety_guard_service import evaluate_ai_content

        teacher = _user(session, "ai_block_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "ai_block_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_ai_content(
            session, course.id,
            content="如何编写恶意代码进行攻击",
            user_id=student.id,
        )
        assert decision.allowed is False

    def test_ai_content_source_reference_check(self, session):
        """AI产出检查是否引用课程资料"""
        from app.services.safety_guard_service import evaluate_ai_content

        teacher = _user(session, "ai_src_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "ai_src_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # 有来源引用
        decision = evaluate_ai_content(
            session, course.id,
            content="根据课程资料，二分查找的原理是...",
            source_materials=["二分查找的原理是..."],
            user_id=student.id,
        )
        assert decision.allowed is True
        assert "has_source_reference" in str(decision.decision_factors)


# ==================== 知识回答与真实执行区分测试 ====================

class TestKnowledgeVsExecution:
    """区分"知识回答"和"真实执行"测试"""

    def test_explain_principle_allowed(self, session):
        """解释原理被允许（知识回答）"""
        teacher = _user(session, "kve_explain_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "kve_explain_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # "解释SQL注入原理" -> 知识回答 -> 允许
        decision = evaluate_content_safety(
            session, course.id, "请解释SQL注入的原理和防御措施",
            user_id=student.id,
        )
        assert decision.allowed is True

    def test_execute_against_real_target_blocked(self, session):
        """对真实目标执行被阻断（真实执行）"""
        teacher = _user(session, "kve_exec_teacher")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "kve_exec_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # "执行SQL注入攻击" -> 真实执行 -> 阻断
        decision = evaluate_content_safety(
            session, course.id, "执行SQL注入攻击目标网站",
            user_id=student.id,
        )
        assert decision.allowed is False

    def test_get_safety_policy_returns_defaults(self, client, session):
        """获取默认安全策略"""
        teacher = _user(session, "safety_api_get")
        course = _setup_course(session, teacher, enable_safety=True)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/safety/course/{course.id}/safety-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["course_type"] == "basic"
        assert "platform_hard_limits" in data
        assert data["platform_hard_limits"]["host_container_isolation"] is True

    def test_update_safety_policy(self, client, session):
        """更新安全策略"""
        teacher = _user(session, "safety_api_update")
        course = _setup_course(session, teacher, enable_safety=True)
        token = _token(teacher)

        response = client.put(
            f"/api/v1/safety/course/{course.id}/safety-policy",
            json={
                "course_type": "cybersecurity",
                "forbidden_topics": ["恶意软件分发"],
                "course_whitelist": ["lab.cyber.course"],
                "status": "active",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["course_type"] == "cybersecurity"
        assert "恶意软件分发" in data["forbidden_topics"]

    def test_update_sandbox_policy_clamped(self, client, session):
        """沙箱资源限制被平台上限钳制"""
        teacher = _user(session, "safety_api_clamp")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        token = _token(teacher)

        response = client.put(
            f"/api/v1/safety/course/{course.id}/sandbox-policy",
            json={
                "cpu_limit": 999,       # 超过平台上限 15
                "memory_limit": 999999, # 超过平台上限 512000
                "wall_time_limit": 999,  # 超过平台上限 30
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["cpu_limit"] == 15
        assert data["memory_limit"] == 512000
        assert data["wall_time_limit"] == 30

    def test_platform_hard_limits_always_true(self, client, session):
        """平台硬边界始终为True"""
        teacher = _user(session, "safety_api_hard")
        course = _setup_course(session, teacher, enable_safety=True)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/safety/course/{course.id}/safety-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = response.json()["data"]
        limits = data["platform_hard_limits"]
        for key, value in limits.items():
            assert value is True, f"平台硬边界 {key} 应始终为 True"

    def test_evaluate_endpoint(self, client, session):
        """评估端点返回决策结果"""
        teacher = _user(session, "safety_api_eval")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "safety_api_eval_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()
        token = _token(student)

        response = client.post(
            f"/api/v1/safety/course/{course.id}/evaluate",
            json={"content": "请解释什么是端口扫描"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "allowed" in data
        assert "decision_factors" in data
        assert "keyword_matched" in data

    def test_audit_log_endpoint(self, client, session):
        """审计日志端点"""
        teacher = _user(session, "safety_api_audit")
        course = _setup_course(session, teacher, enable_safety=True)
        _create_safety_policy(session, course.id, course_type=CourseType.BASIC)
        student = _user(session, "safety_api_audit_s", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        # 触发一次评估产生审计日志
        evaluate_content_safety(session, course.id, "如何提权", user_id=student.id)

        token = _token(teacher)
        response = client.get(
            f"/api/v1/safety/course/{course.id}/audit",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["items"]) > 0
        assert any(item["event_type"] == "block" for item in data["items"])

    def test_sandbox_policy_shows_network_file_resource(self, client, session):
        """沙箱策略返回网络、文件、资源状态"""
        teacher = _user(session, "safety_api_sb")
        course = _setup_course(session, teacher, enable_safety=True, enable_sandbox=True)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/safety/course/{course.id}/sandbox-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "network_mode" in data
        assert "file_access_mode" in data
        assert "cpu_limit" in data
        assert "memory_limit" in data
        assert "wall_time_limit" in data
        assert "environment_destroy_on_exit" in data
        assert "platform_hard_limits" in data

    def test_cross_course_isolation(self, client, session):
        """跨课程隔离：教师A不能访问课程B的安全策略"""
        teacher1 = _user(session, "safety_iso_t1")
        teacher2 = _user(session, "safety_iso_t2")
        course1 = _setup_course(session, teacher1, enable_safety=True)
        course2 = _setup_course(session, teacher2, enable_safety=True)
        token = _token(teacher1)

        response = client.get(
            f"/api/v1/safety/course/{course2.id}/safety-policy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
