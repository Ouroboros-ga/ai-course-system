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

    def test_result_domain_is_derived_from_url_not_provider_label(self, session):
        teacher = _user(session, "wr_spoof_t")
        course = _setup(session, teacher)
        config = get_or_create_config(session, course.id)
        config.enabled = True
        config.allowed_domains = ["wikipedia.org"]
        session.add(config)
        session.commit()

        spoofed = [{
            "source_domain": "wikipedia.org",
            "source_url": "https://evil.example/forged",
            "title": "伪造来源",
            "snippet": "untrusted",
        }]
        with patch(
            "app.services.web_research_service._perform_search",
            return_value=spoofed,
        ):
            result = execute_research(session, course.id, "测试来源")
        assert result.status == ResearchStatus.NO_RESULTS

    def test_disabled_query_is_redacted_and_persisted(self, session):
        teacher = _user(session, "wr_redact_t")
        course = _setup(session, teacher)
        result = execute_research(
            session,
            course.id,
            "邮箱 user@example.com 手机号 13812345678 请解释递归",
        )
        assert result.id is not None
        assert "user@example.com" not in result.query_text
        assert "13812345678" not in result.query_text
        assert result.failure_reason


class TestWebResearchAPIRetired:
    """S2 切换期：旧 web-research 接口已退役（410 Gone + 迁移说明）。

    中间件在路由之前短路，无需鉴权也应得到 410；路由注册保留至 S3 删除。
    """

    @pytest.mark.parametrize(
        ("method", "path", "json_body"),
        [
            ("get", "/api/v1/web-research/policy", None),
            ("get", "/api/v1/web-research/course/1/config", None),
            ("put", "/api/v1/web-research/course/1/config", {"enabled": True}),
            ("post", "/api/v1/web-research/course/1/search", {"query": "二分查找原理"}),
            ("get", "/api/v1/web-research/course/1/references", None),
        ],
    )
    def test_returns_410_gone(self, client, method, path, json_body):
        call = getattr(client, method)
        response = call(path, json=json_body) if json_body is not None else call(path)

        assert response.status_code == 410
        body = response.json()
        assert body["error"] == "RESEARCH_API_RETIRED"
        assert body["migration"] == "Use /api/v1/nexus/* instead"
        assert response.headers["Link"] == '</api/v1/nexus/chat>; rel="successor-version"'
        assert response.headers["X-Deprecation-Phase"] == "S2-research-retired"
        assert "Deprecation" not in response.headers
