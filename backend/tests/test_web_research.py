"""G7 WebResearchTool 受控研究测试

验证：
- 教师可以关闭课程级 WebResearch
- 不可用、无引用或越权来源时拒绝使用
- 每条外部参考带来源、时间和用途
- 不发送学生身份数据
- 外部资料标记为"补充参考"
- 不以外网结果修改掌握度/推荐/图谱
- 域名白名单过滤
- 检索预算控制
- 结果缓存
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import select

from app.core.security import get_password_hash, create_access_token
from app.models.access_control_model import (
    CourseCapability, CourseMembership, CourseRole, MembershipStatus,
    PlatformPermission, PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.models.web_research_model import (
    WebResearchConfig, WebResearchResult, ExternalReference, ResearchStatus,
    DEFAULT_ALLOWED_DOMAINS,
)
from app.services.course_access_service import (
    establish_course_access_baseline, activate_student_membership,
)
from app.services.web_research_service import (
    execute_research, get_or_create_config, sanitize_query,
    serialize_result, serialize_config,
)


def _user(session, name, role=UserRole.TEACHER):
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user); session.commit(); session.refresh(user)
    return user

def _course(session, teacher_id):
    course = Course(
        fanya_course_id=f"wr-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="WR", title="WR", teacher_id=teacher_id, status=CourseStatus.PUBLISHED,
    )
    session.add(course); session.commit(); session.refresh(course)
    return course

def _setup(session, teacher, student=None):
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    if student:
        activate_student_membership(session, course.id, student.id)
    cap = session.exec(select(CourseCapability).where(CourseCapability.course_id == course.id)).first()
    if cap:
        cap.safety_policy = True
        session.add(cap)
    session.commit()
    return course

def _token(user):
    return create_access_token({"sub": str(user.id), "username": user.username, "role": user.role.value})


class TestWebResearchService:
    """WebResearch 服务单元测试"""

    def test_disabled_returns_disabled(self, session):
        """教师关闭时返回 DISABLED"""
        teacher = _user(session, "wr_dis_t")
        course = _setup(session, teacher)
        config = get_or_create_config(session, course.id)
        config.enabled = False
        session.add(config); session.commit()

        result = execute_research(session, course.id, "二分查找")
        assert result.status == ResearchStatus.DISABLED

    def test_query_sanitized(self, session):
        """查询脱敏：移除学生身份数据"""
        query = "学号:20210001 请解释什么是递归"
        sanitized = sanitize_query(query)
        assert "20210001" not in sanitized
        assert "递归" in sanitized

    def test_no_results_returns_no_results(self, session):
        """无白名单域名结果时返回 NO_RESULTS"""
        teacher = _user(session, "wr_nr_t")
        course = _setup(session, teacher)
        config = get_or_create_config(session, course.id)
        config.enabled = True
        session.add(config); session.commit()

        # _perform_search 返回空列表
        result = execute_research(session, course.id, "测试查询")
        assert result.status in (ResearchStatus.NO_RESULTS, ResearchStatus.SEARCH_FAILED)

    def test_cache_hit(self, session):
        """缓存命中时返回 CACHE_HIT"""
        teacher = _user(session, "wr_cache_t")
        course = _setup(session, teacher)
        config = get_or_create_config(session, course.id)
        config.enabled = True
        session.add(config); session.commit()

        # 手动插入缓存
        import hashlib
        qh = hashlib.sha256("测试查询".encode()).hexdigest()
        cached = WebResearchResult(
            course_id=course.id, query_hash=qh, query_text="测试查询",
            status=ResearchStatus.SUCCESS, results=[{"source_domain": "wikipedia.org", "title": "test"}],
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
        session.add(cached); session.commit()

        result = execute_research(session, course.id, "测试查询")
        assert result.status == ResearchStatus.CACHE_HIT

    def test_budget_exceeded(self, session):
        """检索预算用尽时返回 BUDGET_EXCEEDED"""
        teacher = _user(session, "wr_budget_t")
        course = _setup(session, teacher)
        config = get_or_create_config(session, course.id)
        config.enabled = True
        config.search_budget_per_query = 1
        session.add(config); session.commit()

        # 插入一条已用搜索记录
        import hashlib
        qh = hashlib.sha256("已搜索".encode()).hexdigest()
        used = WebResearchResult(
            course_id=course.id, query_hash=qh, query_text="已搜索",
            status=ResearchStatus.SUCCESS, results=[], searches_used=1,
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
        session.add(used); session.commit()

        result = execute_research(session, course.id, "新查询")
        assert result.status == ResearchStatus.BUDGET_EXCEEDED

    def test_result_is_supplementary(self, session):
        """结果始终标记为补充参考"""
        import hashlib
        result = WebResearchResult(
            course_id=1, query_hash=hashlib.sha256(b"test").hexdigest(),
            query_text="test", status=ResearchStatus.SUCCESS,
            results=[{"source_domain": "wikipedia.org"}],
        )
        serialized = serialize_result(result)
        assert serialized["is_supplementary"] is True
        assert serialized["cannot_modify_mastery"] is True
        assert serialized["cannot_modify_recommendation"] is True
        assert serialized["cannot_modify_graph"] is True

    def test_default_domains_included(self):
        """默认域名白名单包含主要参考站点"""
        assert "wikipedia.org" in DEFAULT_ALLOWED_DOMAINS
        assert "stackoverflow.com" in DEFAULT_ALLOWED_DOMAINS


class TestWebResearchAPI:
    """WebResearch API 集成测试"""

    def test_config_requires_membership(self, client, session):
        """获取配置需要权限"""
        teacher = _user(session, "wr_api_nm")
        course = _course(session, teacher.id)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/web-research/course/{course.id}/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_get_config_returns_defaults(self, client, session):
        """获取默认配置"""
        teacher = _user(session, "wr_api_get")
        course = _setup(session, teacher)
        token = _token(teacher)

        response = client.get(
            f"/api/v1/web-research/course/{course.id}/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["enabled"] is False
        assert "wikipedia.org" in data["allowed_domains"]

    def test_update_config(self, client, session):
        """更新配置"""
        teacher = _user(session, "wr_api_upd")
        course = _setup(session, teacher)
        token = _token(teacher)

        response = client.put(
            f"/api/v1/web-research/course/{course.id}/config",
            json={"enabled": True, "allowed_domains": ["wikipedia.org", "example.edu"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["enabled"] is True
        assert "example.edu" in data["allowed_domains"]

    def test_search_when_disabled(self, client, session):
        """WebResearch 关闭时搜索返回 DISABLED"""
        teacher = _user(session, "wr_api_dis")
        student = _user(session, "wr_api_dis_s", UserRole.STUDENT)
        course = _setup(session, teacher, student)
        token = _token(student)

        response = client.post(
            f"/api/v1/web-research/course/{course.id}/search",
            json={"query": "二分查找原理"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "disabled"

    def test_references_list(self, client, session):
        """列出外部参考"""
        teacher = _user(session, "wr_api_ref")
        course = _setup(session, teacher)
        token = _token(teacher)

        # 手动插入参考
        ref = ExternalReference(
            course_id=course.id, source_domain="wikipedia.org",
            source_url="https://wikipedia.org/test", title="Test",
            snippet="Test snippet",
        )
        session.add(ref); session.commit()

        response = client.get(
            f"/api/v1/web-research/course/{course.id}/references",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["items"]) > 0
        assert data["items"][0]["is_supplementary"] is True
        assert data["items"][0]["source_domain"] == "wikipedia.org"

    def test_cross_course_isolation(self, client, session):
        """跨课程隔离"""
        t1 = _user(session, "wr_iso_t1")
        t2 = _user(session, "wr_iso_t2")
        s1 = _user(session, "wr_iso_s1", UserRole.STUDENT)
        c1 = _setup(session, t1, s1)
        c2 = _setup(session, t2)

        token = _token(s1)
        response = client.get(
            f"/api/v1/web-research/course/{c2.id}/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
