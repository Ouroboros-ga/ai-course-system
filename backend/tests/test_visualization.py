"""G4 算法可视化测试

测试要点：
1. 算法白名单与参数校验（纯单元测试，不需要数据库）
   - 白名单包含首批算法
   - 非白名单算法被拒绝
   - 参数超范围被拒绝
   - 非法步骤类型被拒绝
   - 危险内容被拒绝
   - 合法计划通过验证，返回 sanitized_plan
2. API 集成测试（需要数据库和权限）
   - 创建计划需要权限（无 CourseMembership 时 403）
   - 创建合法计划成功（教师 course.mapping.edit）
   - 学生不能创建计划（403）
   - 学生只能看 published 计划
   - 获取计划详情用于回放
   - 发布计划后学生可见
   - 跨课程隔离
   - 平台管理员可跨课程

使用 conftest.py 的 session / client fixture 和统一权限解析器，
不依赖旧 teacher_id 或 StudentEnrollment。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.visualization.algorithm_registry import (
    ALGORITHM_WHITELIST,
    list_allowed_algorithms,
)
from app.services.visualization.plan_validator import validate_visualization_plan


# ==================== 辅助函数 ====================

def _user(session, name, role=UserRole.STUDENT):
    """创建测试用户并提交。"""
    user = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id):
    """创建测试课程并提交。"""
    course = Course(
        fanya_course_id=f"viz-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="Viz Course",
        title="Viz Course",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _token(user):
    """为用户生成 JWT 访问令牌。"""
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token):
    """构造 Bearer 认证头。"""
    return {"Authorization": f"Bearer {token}"}


VIZ = "/api/v1/visualization"

# 首批支持的算法标识
FIRST_BATCH_ALGORITHMS = [
    "binary_search",
    "bubble_sort",
    "stack_operations",
    "queue_operations",
    "factorial_recursion",
    "tree_traversal",
    "graph_bfs",
    "graph_dfs",
]

# 标准合法的二分查找可视化计划
VALID_BINARY_SEARCH_PLAN = {
    "algorithm_id": "binary_search",
    "initial_params": {
        "array": [1, 3, 5, 7, 9, 11, 13],
        "target": 7,
    },
    "steps": [
        {"type": "compare", "description": "比较中间元素 7 与目标 7", "index": 3},
        {"type": "found", "description": "找到目标值", "index": 3},
    ],
    "highlights": [
        {"step": 0, "elements": [3], "color": "yellow"},
    ],
    "playback_speed": 1.0,
}


def _valid_plan_request():
    """构造合法的创建计划请求体（与 CreatePlanRequest 对齐）。"""
    return {
        "algorithm_id": VALID_BINARY_SEARCH_PLAN["algorithm_id"],
        "initial_params": VALID_BINARY_SEARCH_PLAN["initial_params"],
        "steps": VALID_BINARY_SEARCH_PLAN["steps"],
        "highlights": VALID_BINARY_SEARCH_PLAN["highlights"],
        "playback_speed": VALID_BINARY_SEARCH_PLAN["playback_speed"],
    }


# ==================== 算法白名单与参数校验测试（纯单元测试）====================

def test_whitelist_contains_first_batch_algorithms():
    """白名单包含首批算法。

    binary_search, bubble_sort, stack_operations, queue_operations,
    factorial_recursion, tree_traversal, graph_bfs, graph_dfs
    均应在白名单中。
    """
    for algo_id in FIRST_BATCH_ALGORITHMS:
        assert algo_id in ALGORITHM_WHITELIST, f"算法 {algo_id} 不在白名单中"

    # list_allowed_algorithms 返回的列表也应包含这些算法
    listed_ids = {a["algorithm_id"] for a in list_allowed_algorithms()}
    for algo_id in FIRST_BATCH_ALGORITHMS:
        assert algo_id in listed_ids, f"算法 {algo_id} 未出现在算法列表中"


def test_non_whitelisted_algorithm_rejected():
    """非白名单算法被拒绝：提交 "evil_algorithm" 应验证失败。"""
    plan = {
        "algorithm_id": "evil_algorithm",
        "initial_params": {},
        "steps": [],
    }
    result = validate_visualization_plan(plan)
    assert not result.valid
    assert any("不在白名单中" in err for err in result.errors)
    assert result.sanitized_plan is None


def test_param_out_of_range_rejected():
    """参数超范围被拒绝：binary_search 的 array 长度超过 30 应失败。

    binary_search 的 array 参数 max_length=30，提交 31 个元素应被拒绝。
    """
    plan = {
        "algorithm_id": "binary_search",
        "initial_params": {
            "array": list(range(31)),  # 31 个元素，上限为 30
            "target": 15,
        },
        "steps": [
            {"type": "compare", "description": "比较", "index": 0},
        ],
    }
    result = validate_visualization_plan(plan)
    assert not result.valid
    assert any("array" in err and "超出范围" in err for err in result.errors)


def test_illegal_step_type_rejected():
    """非法步骤类型被拒绝：步骤 type="eval" 应失败。

    binary_search 允许的步骤类型为 compare/narrow_left/narrow_right/found/not_found，
    "eval" 不在允许列表中。
    """
    plan = {
        "algorithm_id": "binary_search",
        "initial_params": {
            "array": [1, 3, 5, 7, 9],
            "target": 5,
        },
        "steps": [
            {"type": "eval", "description": "恶意步骤"},
        ],
    }
    result = validate_visualization_plan(plan)
    assert not result.valid
    assert any("eval" in err and "不在允许列表中" in err for err in result.errors)


def test_step_indices_are_preserved_and_bounds_checked():
    plan = {
        "algorithm_id": "bubble_sort",
        "initial_params": {"array": [3, 1, 2]},
        "steps": [
            {"type": "swap", "description": "交换", "i": 0, "j": 1},
        ],
    }
    result = validate_visualization_plan(plan)
    assert result.valid
    assert result.sanitized_plan["steps"][0]["i"] == 0
    assert result.sanitized_plan["steps"][0]["j"] == 1

    plan["steps"][0]["j"] = 3
    invalid = validate_visualization_plan(plan)
    assert not invalid.valid
    assert any("j 超出数组范围" in error for error in invalid.errors)


def test_dangerous_content_rejected():
    """危险内容被拒绝：计划含 <script> 或 eval( 应失败。

    验证器应检测到 <script、eval( 等危险模式并拒绝整个计划。
    """
    # 测试 <script>
    plan_with_script = {
        "algorithm_id": "binary_search",
        "initial_params": {"array": [1, 2, 3], "target": 2},
        "steps": [
            {"type": "compare", "description": "<script>alert(1)</script>", "index": 0},
        ],
    }
    result = validate_visualization_plan(plan_with_script)
    assert not result.valid
    assert any("危险内容" in err for err in result.errors)

    # 测试 eval(
    plan_with_eval = {
        "algorithm_id": "binary_search",
        "initial_params": {"array": [1, 2, 3], "target": 2},
        "steps": [
            {"type": "compare", "description": "eval(malicious_code)", "index": 0},
        ],
    }
    result = validate_visualization_plan(plan_with_eval)
    assert not result.valid
    assert any("危险内容" in err for err in result.errors)


def test_valid_plan_passes_validation():
    """合法计划通过验证，返回 sanitized_plan。

    标准二分查找计划应通过验证，sanitized_plan 包含版本号、算法信息和净化后的步骤。
    """
    result = validate_visualization_plan(VALID_BINARY_SEARCH_PLAN)
    assert result.valid
    assert result.errors == []
    assert result.algorithm_spec is not None
    assert result.algorithm_spec.algorithm_id == "binary_search"

    sanitized = result.sanitized_plan
    assert sanitized is not None
    assert sanitized["version"] == "viz-plan-v1.0"
    assert sanitized["algorithm_id"] == "binary_search"
    assert sanitized["algorithm_name"] == "二分查找"
    assert sanitized["algorithm_category"] == "binary"
    assert sanitized["initial_params"]["array"] == [1, 3, 5, 7, 9, 11, 13]
    assert sanitized["initial_params"]["target"] == 7
    assert len(sanitized["steps"]) == 2
    assert sanitized["steps"][0]["type"] == "compare"
    assert sanitized["steps"][1]["type"] == "found"
    assert sanitized["playback_speed"] == 1.0
    assert len(sanitized["highlights"]) == 1
    assert sanitized["highlights"][0]["step"] == 0


# ==================== API 集成测试（需要数据库和权限）====================

def test_create_plan_requires_membership(client, session):
    """创建计划需要权限：无 CourseMembership 时返回 403。

    仅设置 Course.teacher_id 但不创建 CourseMembership 和 CourseCapability，
    则 resolve_course_access 返回无权限，API 返回 403。
    """
    teacher = _user(session, "viz_no_member_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    # 故意不调用 establish_course_access_baseline
    session.commit()

    token = _token(teacher)
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_create_valid_plan_succeeds(client, session):
    """创建合法计划成功：有 course.mapping.edit 权限的教师可创建。

    建立课程访问基线后（创建 CourseMembership + CourseCapability），
    教师可创建可视化计划，计划状态为 validated。
    """
    teacher = _user(session, "viz_create_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    token = _token(teacher)
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan_id"] is not None
    assert data["algorithm_id"] == "binary_search"
    assert data["algorithm_name"] == "二分查找"
    assert data["status"] == "validated"
    assert data["course_id"] == course.id
    assert data["plan_data"]["algorithm_id"] == "binary_search"
    assert data["plan_data"]["initial_params"]["target"] == 7


def test_student_cannot_create_plan(client, session):
    """学生不能创建计划：学生角色返回 403。

    学生只有 course.content.read 权限，没有 course.mapping.edit，
    创建计划需要 course.mapping.edit，因此返回 403。
    """
    teacher = _user(session, "viz_student_create_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "viz_student_create_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    token = _token(student)
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_student_only_sees_published_plans(client, session):
    """学生只能看 published 计划：未发布的计划学生不可见。

    教师创建计划后默认状态为 validated，学生列表看不到，
    学生获取详情也返回 403（计划未发布）。
    """
    teacher = _user(session, "viz_pubonly_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "viz_pubonly_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    teacher_token = _token(teacher)
    student_token = _token(student)

    # 教师创建计划（默认 status=validated）
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    plan_id = resp.json()["data"]["plan_id"]

    # 学生列出计划 -> 看不到（未发布）
    resp = client.get(
        f"{VIZ}/course/{course.id}/plans",
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    # 学生获取计划详情 -> 403（未发布）
    resp = client.get(
        f"{VIZ}/{plan_id}",
        headers=_auth(student_token),
    )
    assert resp.status_code == 403

    # 教师列出计划 -> 可看到
    resp = client.get(
        f"{VIZ}/course/{course.id}/plans",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1


def test_get_plan_detail_for_playback(client, session):
    """获取计划详情用于回放：GET /{plan_id} 返回计划数据。

    教师创建计划后，通过 plan_id 获取详情，响应包含完整的 plan_data
    （算法、参数、步骤），且回放统计 play_count 递增。
    """
    teacher = _user(session, "viz_detail_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    teacher_token = _token(teacher)

    # 创建计划
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    plan_id = resp.json()["data"]["plan_id"]

    # 获取计划详情
    resp = client.get(
        f"{VIZ}/{plan_id}",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan_id"] == plan_id
    assert data["algorithm_id"] == "binary_search"
    assert data["algorithm_name"] == "二分查找"
    assert data["plan_data"]["algorithm_id"] == "binary_search"
    assert data["plan_data"]["initial_params"]["target"] == 7
    assert len(data["plan_data"]["steps"]) == 2
    assert data["plan_data"]["steps"][0]["type"] == "compare"
    assert data["plan_data"]["steps"][1]["type"] == "found"
    # 回放统计已更新
    assert data["play_count"] >= 1


def test_publish_plan_makes_student_visible(client, session):
    """发布计划：教师可发布，学生可见后。

    教师创建计划 -> 发布 -> 学生列表可见且可获取详情。
    """
    teacher = _user(session, "viz_publish_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    student = _user(session, "viz_publish_student")
    activate_student_membership(session, course.id, student.id)
    session.commit()

    teacher_token = _token(teacher)
    student_token = _token(student)

    # 教师创建计划
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    plan_id = resp.json()["data"]["plan_id"]

    # 发布前：学生看不到
    resp = client.get(
        f"{VIZ}/course/{course.id}/plans",
        headers=_auth(student_token),
    )
    assert resp.json()["data"]["total"] == 0

    # 教师发布
    resp = client.post(
        f"{VIZ}/course/{course.id}/{plan_id}/publish",
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "published"

    # 发布后：学生列表可见
    resp = client.get(
        f"{VIZ}/course/{course.id}/plans",
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["plan_id"] == plan_id
    assert items[0]["status"] == "published"

    # 学生可获取计划详情
    resp = client.get(
        f"{VIZ}/{plan_id}",
        headers=_auth(student_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["plan_id"] == plan_id


def test_cross_course_isolation(client, session):
    """跨课程隔离：教师 A 不能访问教师 B 课程的计划。

    使用统一权限解析器（CourseMembership），不是旧的 teacher_id 判断。
    教师 A 无课程 B 的 CourseMembership，所有操作返回 403。
    """
    teacher_a = _user(session, "viz_iso_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "viz_iso_teacher_b", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id)
    course_b = _course(session, teacher_b.id)
    establish_course_access_baseline(session, course_a.id, teacher_a.id)
    establish_course_access_baseline(session, course_b.id, teacher_b.id)
    session.commit()

    teacher_b_token = _token(teacher_b)
    teacher_a_token = _token(teacher_a)

    # 教师B在课程B中创建计划
    resp = client.post(
        f"{VIZ}/course/{course_b.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(teacher_b_token),
    )
    assert resp.status_code == 200
    plan_id = resp.json()["data"]["plan_id"]

    # 教师A列出课程B计划 -> 403
    resp = client.get(
        f"{VIZ}/course/{course_b.id}/plans",
        headers=_auth(teacher_a_token),
    )
    assert resp.status_code == 403

    # 教师A获取课程B计划详情 -> 403
    resp = client.get(
        f"{VIZ}/{plan_id}",
        headers=_auth(teacher_a_token),
    )
    assert resp.status_code == 403

    # 教师A在课程B中创建计划 -> 403
    resp = client.post(
        f"{VIZ}/course/{course_b.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(teacher_a_token),
    )
    assert resp.status_code == 403

    # 教师A发布课程B计划 -> 403
    resp = client.post(
        f"{VIZ}/course/{course_b.id}/{plan_id}/publish",
        headers=_auth(teacher_a_token),
    )
    assert resp.status_code == 403

    # 教师B可以管理自己的课程
    resp = client.get(
        f"{VIZ}/course/{course_b.id}/plans",
        headers=_auth(teacher_b_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1


def test_platform_admin_cross_course_access(client, session):
    """平台管理员可跨课程：持有 platform.admin 的用户可访问。

    管理员无 CourseMembership，但有 PlatformPermissionAssignment(ADMIN)，
    可以访问任何课程的可视化计划，且不限于 published 状态。
    """
    teacher = _user(session, "viz_admin_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()

    teacher_token = _token(teacher)

    # 教师创建计划（validated 状态，未发布）
    resp = client.post(
        f"{VIZ}/course/{course.id}/plan",
        json=_valid_plan_request(),
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200
    plan_id = resp.json()["data"]["plan_id"]

    # 平台管理员（无课程成员关系，全局角色为 STUDENT）
    admin = _user(session, "viz_admin_user", UserRole.STUDENT)
    session.add(PlatformPermissionAssignment(
        user_id=admin.id, permission=PlatformPermission.ADMIN,
    ))
    session.commit()

    admin_token = _token(admin)

    # 管理员列出课程计划 -> 200，可看到非 published 的计划
    resp = client.get(
        f"{VIZ}/course/{course.id}/plans",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["plan_id"] == plan_id
    assert items[0]["status"] == "validated"

    # 管理员获取计划详情 -> 200
    resp = client.get(
        f"{VIZ}/{plan_id}",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["plan_id"] == plan_id
