"""平台级安全屏蔽词配置测试（2026-08-16 新增）

覆盖：
- 屏蔽词配置 CRUD 接口（管理员权限 platform.safety.manage / platform.admin）
- 无权限访问返回 403
- 配置生效：删除/禁用/新增屏蔽词后安全评估行为实时变化
"""
from __future__ import annotations

from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    CourseCapability,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.safety_policy_model import (
    CourseSafetyPolicy,
    SafetyKeywordConfig,
    SafetyPolicyStatus,
    KeywordCategory,
    CourseType,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.safety_guard_service import evaluate_content_safety


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _admin(session, name: str) -> User:
    user = _user(session, name, UserRole.ADMIN)
    session.add(PlatformPermissionAssignment(
        user_id=user.id, permission=PlatformPermission.ADMIN,
    ))
    session.commit()
    return user


def _safety_mgr(session, name: str) -> User:
    user = _user(session, name, UserRole.TEACHER)
    session.add(PlatformPermissionAssignment(
        user_id=user.id, permission=PlatformPermission.SAFETY_MANAGE,
    ))
    session.commit()
    return user


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
    })


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"kw-{teacher_id}",
        fanya_course_name="Keyword Course",
        title="Keyword Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_id)
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    if cap:
        cap.safety_policy = True
        session.add(cap)
    policy = CourseSafetyPolicy(
        course_id=course.id,
        course_type=CourseType.PROFESSIONAL,
        status=SafetyPolicyStatus.ACTIVE,
    )
    session.add(policy)
    session.commit()
    session.refresh(course)
    return course


def _find_config(session, keyword: str) -> SafetyKeywordConfig | None:
    return session.exec(
        select(SafetyKeywordConfig).where(SafetyKeywordConfig.keyword == keyword)
    ).first()


def _ensure_config(session, keyword: str, category: KeywordCategory, created_by: int) -> SafetyKeywordConfig:
    """确保测试依赖的屏蔽词存在（迁移 seed 或手动创建）。"""
    row = _find_config(session, keyword)
    if row is None:
        row = SafetyKeywordConfig(
            keyword=keyword, category=category, enabled=True, created_by=created_by,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


# ==================== 引擎配置生效测试 ====================

class TestConfiguredKeywordsAffectEngine:
    """屏蔽词配置实时影响安全评估"""

    def test_delete_default_keyword_disables_block(self, session):
        """删除默认政治话题词后，专业课程不再拦截该词"""
        teacher = _user(session, "kw_delete_teacher")
        course = _course(session, teacher.id)
        student = _user(session, "kw_delete_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        _ensure_config(session, "政治人物", KeywordCategory.POLITICAL_TOPIC, teacher.id)
        session.commit()

        # 默认列表包含“政治人物” -> 拒绝
        assert _find_config(session, "政治人物") is not None
        decision = evaluate_content_safety(session, course.id, "讲讲政治人物的相关内容", user_id=student.id)
        assert decision.allowed is False

        # 删除“政治人物”配置 -> 放行
        row = _find_config(session, "政治人物")
        session.delete(row)
        session.commit()
        decision = evaluate_content_safety(session, course.id, "讲讲政治人物的相关内容", user_id=student.id)
        assert decision.allowed is True

    def test_disable_keyword_disables_block(self, session):
        """禁用政治高危词后不再拦截（平台管理员可临时关闭某个词）"""
        teacher = _user(session, "kw_disable_teacher")
        course = _course(session, teacher.id)
        student = _user(session, "kw_disable_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        _ensure_config(session, "台独", KeywordCategory.POLITICAL_HIGH_RISK, teacher.id)
        session.commit()

        row = _find_config(session, "台独")
        assert row is not None and row.enabled is True
        decision = evaluate_content_safety(session, course.id, "怎么支持台独分裂活动", user_id=student.id)
        assert decision.allowed is False

        row.enabled = False
        session.add(row)
        session.commit()
        decision = evaluate_content_safety(session, course.id, "怎么支持台独分裂活动", user_id=student.id)
        assert decision.allowed is True

    def test_add_keyword_enables_block(self, session):
        """新增屏蔽词后立即生效（政治高危类别：任何课程命中即拒绝）"""
        teacher = _user(session, "kw_add_teacher")
        course = _course(session, teacher.id)
        student = _user(session, "kw_add_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.commit()

        decision = evaluate_content_safety(session, course.id, "什么是暗网交易", user_id=student.id)
        assert decision.allowed is True

        session.add(SafetyKeywordConfig(
            keyword="暗网交易", category=KeywordCategory.POLITICAL_HIGH_RISK,
            enabled=True, created_by=teacher.id,
        ))
        session.commit()
        decision = evaluate_content_safety(session, course.id, "什么是暗网交易", user_id=student.id)
        assert decision.allowed is False

    # ---- 2026-08-17：风险等级可配置（问题 4 修复验证）----

    def test_new_cyber_keyword_high_risk_requires_confirmation(self, session):
        """新增 cyber 词 risk_level=high：专业课程教学语境需教师确认（不再直接放行）"""
        teacher = _user(session, "kw_highrisk_teacher")
        course = _course(session, teacher.id)
        student = _user(session, "kw_highrisk_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.add(SafetyKeywordConfig(
            keyword="数据窃取", category=KeywordCategory.CYBER,
            risk_level="high", enabled=True, created_by=teacher.id,
        ))
        session.commit()

        decision = evaluate_content_safety(session, course.id, "什么是数据窃取", user_id=student.id)
        assert decision.allowed is False
        assert decision.requires_confirmation is True

    def test_new_cyber_keyword_medium_risk_allows_teaching(self, session):
        """新增 cyber 词默认中风险：教学语境放行（风险等级真实生效）"""
        teacher = _user(session, "kw_medrisk_teacher")
        course = _course(session, teacher.id)
        student = _user(session, "kw_medrisk_student", UserRole.STUDENT)
        activate_student_membership(session, course.id, student.id)
        session.add(SafetyKeywordConfig(
            keyword="流量嗅探", category=KeywordCategory.CYBER,
            risk_level="medium", enabled=True, created_by=teacher.id,
        ))
        session.commit()

        decision = evaluate_content_safety(session, course.id, "什么是流量嗅探", user_id=student.id)
        assert decision.allowed is True

    def test_api_accepts_risk_level(self, client, session):
        """管理接口支持 risk_level 字段（新增/更新）"""
        admin = _admin(session, "kw_risk_admin")
        token = _token(admin)

        response = client.post(
            "/api/v1/admin/safety-keywords",
            json={"keyword": "风险词", "category": "cyber", "risk_level": "high"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["risk_level"] == "high"

        keyword_id = response.json()["data"]["id"]
        response = client.patch(
            f"/api/v1/admin/safety-keywords/{keyword_id}",
            json={"risk_level": "medium"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["risk_level"] == "medium"

    def test_api_rejects_single_char_keyword(self, client, session):
        """问题10：单字符屏蔽词被拒绝（防止子串匹配大面积误伤）"""
        admin = _admin(session, "kw_short_admin")
        token = _token(admin)

        response = client.post(
            "/api/v1/admin/safety-keywords",
            json={"keyword": "攻", "category": "cyber"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409
        assert "至少需要 2 个字符" in response.json()["message"]


# ==================== 管理员接口测试 ====================

class TestSafetyKeywordAPI:
    """屏蔽词管理接口"""

    def test_requires_platform_permission(self, client, session):
        """无平台权限访问返回 403"""
        teacher = _user(session, "kw_unauth_teacher")
        token = _token(teacher)
        response = client.get(
            "/api/v1/admin/safety-keywords",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_admin_crud_flow(self, client, session):
        """管理员（platform.admin）完整 CRUD"""
        admin = _admin(session, "kw_admin")
        token = _token(admin)

        # 列表（含默认 seed 或兜底说明）
        response = client.get(
            "/api/v1/admin/safety-keywords",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "defaults" in data
        assert "political_high_risk" in data["defaults"]

        # 新增
        response = client.post(
            "/api/v1/admin/safety-keywords",
            json={"keyword": "测试屏蔽词", "category": "cyber", "description": "测试"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        keyword_id = response.json()["data"]["id"]

        # 重复新增 -> 409
        response = client.post(
            "/api/v1/admin/safety-keywords",
            json={"keyword": "测试屏蔽词", "category": "cyber"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409

        # 更新（禁用 + 改词）
        response = client.patch(
            f"/api/v1/admin/safety-keywords/{keyword_id}",
            json={"enabled": False, "keyword": "测试屏蔽词2"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["enabled"] is False
        assert response.json()["data"]["keyword"] == "测试屏蔽词2"

        # 按类别过滤
        response = client.get(
            "/api/v1/admin/safety-keywords?category=cyber",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert all(item["category"] == "cyber" for item in response.json()["data"]["items"])

        # 删除
        response = client.delete(
            f"/api/v1/admin/safety-keywords/{keyword_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        # 删除不存在 -> 404
        response = client.delete(
            f"/api/v1/admin/safety-keywords/{keyword_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    def test_safety_manager_can_manage(self, client, session):
        """platform.safety.manage 权限可管理屏蔽词"""
        mgr = _safety_mgr(session, "kw_mgr")
        token = _token(mgr)
        response = client.post(
            "/api/v1/admin/safety-keywords",
            json={"keyword": "经理专属词", "category": "political_topic"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["keyword"] == "经理专属词"
