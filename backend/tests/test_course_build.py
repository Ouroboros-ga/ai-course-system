"""阶段3 课程建设工作流 端到端测试。

覆盖路线图 §6 验收：
- 七步建设状态机：materials → structure → scripts → page_mappings → media → validate → release
- 质量门禁：error/blocker 阻断发布
- 发布不可变：published 后不可重复发布
- 回滚：产生新激活版本而非破坏历史
- 教师锁定：locked 步骤 AI 重跑不可覆盖
- 跨课程/跨用户严格隔离

四类必备测试：成功、权限拒绝、跨课程拒绝、降级。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import CourseMembership, MembershipStatus
from app.models.course_build_model import (
    BuildStepName,
    BuildStepStatus,
    CourseBuildStep,
    CourseRelease,
    CourseReleaseArtifact,
    MaterialStatus,
    ReleaseStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


COURSE_BUILD = "/api/v1/course-build"
FACADE = "/api/v1/facade"


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
    title: str = "Build Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
) -> Course:
    c = Course(
        fanya_course_id=f"bc-{teacher_id}-{datetime.utcnow().timestamp()}",
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


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_material(
    client,
    course_id: int,
    teacher_token: str,
    *,
    name: str = "测试材料.pdf",
    file_hash: str = "abc123",
) -> str:
    """创建材料并返回 material_id。"""
    resp = client.post(
        f"{COURSE_BUILD}/course/{course_id}/materials",
        json={
            "name": name,
            "material_type": "document",
            "file_path": "uploads/test.pdf",
            "file_hash": file_hash,
            "file_size": 1024,
            "mime_type": "application/pdf",
        },
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["material"]["material_id"]


def _mark_material_parsed(
    client,
    course_id: int,
    material_id: str,
    version_id: str,
    teacher_token: str,
) -> None:
    """标记材料已解析。"""
    resp = client.post(
        f"{COURSE_BUILD}/course/{course_id}/materials/{material_id}/parse",
        json={
            "version_id": version_id,
            "status": "parsed",
            "parse_task_id": "task-parse-001",
            "parse_output_ref": "docling://parsed",
        },
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text


def _advance_step(
    client,
    course_id: int,
    step_name: str,
    teacher_token: str,
    *,
    target_status: str = "approved",
    output_ref: str = "artifact://step",
) -> None:
    """推进单步状态。"""
    resp = client.put(
        f"{COURSE_BUILD}/course/{course_id}/steps/{step_name}",
        json={
            "target_status": "in_progress",
            "output_ref": output_ref,
        },
        headers=_auth(teacher_token),
    )
    assert resp.status_code == 200, resp.text
    resp2 = client.put(
        f"{COURSE_BUILD}/course/{course_id}/steps/{step_name}",
        json={
            "target_status": target_status,
            "output_ref": output_ref,
        },
        headers=_auth(teacher_token),
    )
    assert resp2.status_code == 200, resp2.text


# ---------------------------------------------------------------------------
# 1. 成功路径：facade /build 返回七步状态
# ---------------------------------------------------------------------------


def test_facade_build_view_returns_seven_steps(client, session):
    """教师访问 facade /build -> 自动初始化草稿并返回七步状态。"""
    teacher = _user(session, "bc_facade_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    resp = client.get(
        f"{FACADE}/course/{course.id}/build",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["can_build"] is True
    assert data["can_publish"] is True
    assert data["draft"] is not None
    assert data["current_step"] == "materials"
    step_names = [s["step_name"] for s in data["steps"]]
    expected = ["materials", "structure", "scripts", "page_mappings", "media", "validate", "release"]
    assert step_names == expected
    for s in data["steps"]:
        assert s["status"] == "not_started"


# ---------------------------------------------------------------------------
# 2. 源材料管理
# ---------------------------------------------------------------------------


def test_material_create_and_add_version(client, session):
    """创建材料 + 添加新版本；旧版本标记为 superseded。"""
    teacher = _user(session, "bc_mat_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 创建材料 + 首版本
    resp1 = client.post(
        f"{COURSE_BUILD}/course/{course.id}/materials",
        json={"name": "课件 v1", "file_hash": "hash-v1"},
        headers=_auth(_token(teacher)),
    )
    assert resp1.status_code == 200
    assert resp1.json()["code"] == 201
    material_id = resp1.json()["data"]["material"]["material_id"]
    v1_id = resp1.json()["data"]["version"]["version_id"]
    assert resp1.json()["data"]["version"]["version"] == 1
    assert resp1.json()["data"]["version"]["is_current"] is True

    # 添加新版本
    resp2 = client.post(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/versions",
        json={"file_hash": "hash-v2"},
        headers=_auth(_token(teacher)),
    )
    assert resp2.status_code == 200
    assert resp2.json()["code"] == 201
    assert resp2.json()["data"]["version"] == 2
    assert resp2.json()["data"]["is_current"] is True

    # 旧版本应标记为非 current
    versions = client.get(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/versions",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    v1 = next(v for v in versions if v["version_id"] == v1_id)
    assert v1["is_current"] is False
    v2 = next(v for v in versions if v["version"] == 2)
    assert v2["is_current"] is True


def test_material_parse_status_update(client, session):
    """更新材料解析状态：uploaded -> parsing -> parsed。"""
    teacher = _user(session, "bc_parse_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)
    material_id = _create_material(client, course.id, _token(teacher))
    versions = client.get(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/versions",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    version_id = versions[0]["version_id"]

    # 标记为 parsing
    r1 = client.post(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/parse",
        json={"version_id": version_id, "status": "parsing", "parse_task_id": "task-001"},
        headers=_auth(_token(teacher)),
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["parse_status"] == "parsing"

    # 标记为 parsed
    r2 = client.post(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/parse",
        json={"version_id": version_id, "status": "parsed", "parse_output_ref": "docling://ok"},
        headers=_auth(_token(teacher)),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["parse_status"] == "parsed"


# ---------------------------------------------------------------------------
# 3. 七步状态机
# ---------------------------------------------------------------------------


def test_step_state_machine_transitions(client, session):
    """单步状态机：not_started → in_progress → ready_for_review → approved。"""
    teacher = _user(session, "bc_step_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # not_started -> in_progress
    r1 = client.put(
        f"{COURSE_BUILD}/course/{course.id}/steps/materials",
        json={"target_status": "in_progress"},
        headers=_auth(_token(teacher)),
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["status"] == "in_progress"

    # in_progress -> ready_for_review
    r2 = client.put(
        f"{COURSE_BUILD}/course/{course.id}/steps/materials",
        json={"target_status": "ready_for_review", "output_ref": "mat://ok"},
        headers=_auth(_token(teacher)),
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "ready_for_review"

    # ready_for_review -> approved
    r3 = client.put(
        f"{COURSE_BUILD}/course/{course.id}/steps/materials",
        json={"target_status": "approved"},
        headers=_auth(_token(teacher)),
    )
    assert r3.status_code == 200
    assert r3.json()["data"]["status"] == "approved"


def test_step_invalid_transition_returns_conflict(client, session):
    """非法状态转移 -> 409 STATE_CONFLICT。"""
    teacher = _user(session, "bc_invalid_step_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # not_started 直接 -> approved (非法)
    resp = client.put(
        f"{COURSE_BUILD}/course/{course.id}/steps/materials",
        json={"target_status": "approved"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_code"] == "STATE_CONFLICT"


# ---------------------------------------------------------------------------
# 4. 教师锁定：AI 重跑不可覆盖
# ---------------------------------------------------------------------------


def test_step_lock_blocks_ai_rerun(client, session):
    """教师锁定步骤后，AI 重跑（target_status=in_progress）被拒绝。"""
    teacher = _user(session, "bc_lock_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 推进到 ready_for_review
    _advance_step(client, course.id, "scripts", _token(teacher), target_status="ready_for_review")

    # 教师锁定
    r_lock = client.post(
        f"{COURSE_BUILD}/course/{course.id}/steps/scripts/lock",
        json={"lock_reason": "讲稿已审定"},
        headers=_auth(_token(teacher)),
    )
    assert r_lock.status_code == 200
    assert r_lock.json()["data"]["status"] == "locked"
    assert r_lock.json()["data"]["locked_by"] is not None

    # AI 重跑 -> 被拒绝
    r_rerun = client.put(
        f"{COURSE_BUILD}/course/{course.id}/steps/scripts",
        json={"target_status": "in_progress"},
        headers=_auth(_token(teacher)),
    )
    assert r_rerun.status_code == 409
    assert r_rerun.json()["data"]["error_code"] == "STATE_CONFLICT"

    # 教师解锁
    r_unlock = client.post(
        f"{COURSE_BUILD}/course/{course.id}/steps/scripts/unlock",
        headers=_auth(_token(teacher)),
    )
    assert r_unlock.status_code == 200
    assert r_unlock.json()["data"]["status"] == "approved"
    assert r_unlock.json()["data"]["locked_by"] is None


def test_step_lock_only_after_review(client, session):
    """未到 ready_for_review 状态不可锁定。"""
    teacher = _user(session, "bc_lock_early_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # not_started 状态尝试锁定 -> 409
    resp = client.post(
        f"{COURSE_BUILD}/course/{course.id}/steps/materials/lock",
        json={"lock_reason": "过早锁定"},
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 5. 质量门禁
# ---------------------------------------------------------------------------


def test_quality_gate_blocks_publish_when_no_materials(client, session):
    """没有材料时质量门禁失败 -> 阻断发布。"""
    teacher = _user(session, "bc_gate_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 运行质量门禁
    r_gate = client.post(
        f"{COURSE_BUILD}/course/{course.id}/validate",
        headers=_auth(_token(teacher)),
    )
    assert r_gate.status_code == 200
    data = r_gate.json()["data"]
    assert data["passed"] is False
    assert data["error_count"] >= 1

    # 尝试发布 -> 409 STATE_CONFLICT
    r_release = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        json={"label": "v1"},
        headers=_auth(_token(teacher)),
    )
    release_id = r_release.json()["data"]["release_id"]

    r_pub = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id}/publish",
        json={"run_quality_gate": True},
        headers=_auth(_token(teacher)),
    )
    assert r_pub.status_code == 409
    assert r_pub.json()["data"]["error_code"] == "STATE_CONFLICT"


def test_quality_gate_passes_with_materials_and_steps(client, session):
    """有材料 + 关键步骤已启动 -> 质量门禁通过。"""
    teacher = _user(session, "bc_gate_pass_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 创建材料并标记已解析
    material_id = _create_material(client, course.id, _token(teacher))
    versions = client.get(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/versions",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    _mark_material_parsed(client, course.id, material_id, versions[0]["version_id"], _token(teacher))

    # 推进 materials/structure/scripts 到 approved
    _advance_step(client, course.id, "materials", _token(teacher))
    _advance_step(client, course.id, "structure", _token(teacher))
    _advance_step(client, course.id, "scripts", _token(teacher))

    # 运行质量门禁
    r_gate = client.post(
        f"{COURSE_BUILD}/course/{course.id}/validate",
        headers=_auth(_token(teacher)),
    )
    assert r_gate.status_code == 200
    assert r_gate.json()["data"]["passed"] is True
    assert r_gate.json()["data"]["error_count"] == 0
    assert r_gate.json()["data"]["blocker_count"] == 0


# ---------------------------------------------------------------------------
# 6. 发布与回滚
# ---------------------------------------------------------------------------


def test_release_publish_and_rollback(client, session):
    """发布 -> 回滚 -> 产生新激活版本，旧版本历史保留。"""
    teacher = _user(session, "bc_release_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 准备：材料 + 解析 + 步骤推进
    material_id = _create_material(client, course.id, _token(teacher), name="发布材料")
    versions = client.get(
        f"{COURSE_BUILD}/course/{course.id}/materials/{material_id}/versions",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    _mark_material_parsed(client, course.id, material_id, versions[0]["version_id"], _token(teacher))
    _advance_step(client, course.id, "materials", _token(teacher))
    _advance_step(client, course.id, "structure", _token(teacher))
    _advance_step(client, course.id, "scripts", _token(teacher))

    # 创建发布草稿
    r_draft = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        json={"label": "v1.0", "release_notes": "首次发布"},
        headers=_auth(_token(teacher)),
    )
    release_id_v1 = r_draft.json()["data"]["release_id"]
    assert r_draft.json()["data"]["status"] == "draft"
    assert r_draft.json()["data"]["version"] == 1

    # 发布
    r_pub = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id_v1}/publish",
        json={
            "structure_snapshot": {"nodes": 10},
            "scripts_snapshot": {"scripts": 5},
            "run_quality_gate": True,
        },
        headers=_auth(_token(teacher)),
    )
    assert r_pub.status_code == 200, r_pub.text
    assert r_pub.json()["data"]["status"] == "published"
    assert r_pub.json()["data"]["is_active"] is True
    assert r_pub.json()["data"]["published_by"] is not None

    # 验证发布后不可重复发布
    r_pub_again = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id_v1}/publish",
        json={"run_quality_gate": False},
        headers=_auth(_token(teacher)),
    )
    assert r_pub_again.status_code == 409

    # 创建第二个发布并发布
    r_draft2 = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        json={"label": "v2.0"},
        headers=_auth(_token(teacher)),
    )
    release_id_v2 = r_draft2.json()["data"]["release_id"]
    r_pub2 = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id_v2}/publish",
        json={"run_quality_gate": True},
        headers=_auth(_token(teacher)),
    )
    assert r_pub2.status_code == 200
    assert r_pub2.json()["data"]["is_active"] is True

    # v1 应被标记为 superseded
    releases = client.get(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    v1 = next(r for r in releases if r["release_id"] == release_id_v1)
    assert v1["status"] == "superseded"
    assert v1["is_active"] is False

    # 回滚到 v1
    r_rollback = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/rollback",
        json={"target_release_id": release_id_v1},
        headers=_auth(_token(teacher)),
    )
    assert r_rollback.status_code == 200, r_rollback.text
    rolled = r_rollback.json()["data"]
    assert rolled["status"] == "published"
    assert rolled["is_active"] is True
    assert rolled["version"] == 3  # 新版本号
    assert "回滚" in rolled["label"]

    # v2 应被标记为 rolled_back
    releases_after = client.get(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        headers=_auth(_token(teacher)),
    ).json()["data"]["items"]
    v2 = next(r for r in releases_after if r["release_id"] == release_id_v2)
    assert v2["status"] == "rolled_back"
    assert v2["is_active"] is False


def test_release_artifact_association(client, session):
    """为发布关联产物。"""
    teacher = _user(session, "bc_art_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id)

    # 创建发布草稿
    r_draft = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        json={"label": "v1"},
        headers=_auth(_token(teacher)),
    )
    release_id = r_draft.json()["data"]["release_id"]

    # 关联产物
    r_add = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id}/artifacts",
        json={
            "artifact_type": "material",
            "artifact_id": "mat-001",
            "artifact_version": 1,
            "artifact_ref": "materials://mat-001/v1",
        },
        headers=_auth(_token(teacher)),
    )
    assert r_add.status_code == 200
    assert r_add.json()["code"] == 201

    # 列出产物
    r_list = client.get(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id}/artifacts",
        headers=_auth(_token(teacher)),
    )
    assert r_list.status_code == 200
    assert any(a["artifact_id"] == "mat-001" for a in r_list.json()["data"]["items"])


# ---------------------------------------------------------------------------
# 7. 权限拒绝
# ---------------------------------------------------------------------------


def test_student_cannot_create_material(client, session):
    """学生不能创建材料 -> 403。"""
    teacher = _user(session, "bc_perm_teacher", UserRole.TEACHER)
    student = _user(session, "bc_perm_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    resp = client.post(
        f"{COURSE_BUILD}/course/{course.id}/materials",
        json={"name": "学生上传"},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


def test_student_cannot_publish(client, session):
    """学生不能发布 -> 403。"""
    teacher = _user(session, "bc_pub_perm_teacher", UserRole.TEACHER)
    student = _user(session, "bc_pub_perm_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    # 教师先创建 release 草稿
    r_draft = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases",
        json={"label": "v1"},
        headers=_auth(_token(teacher)),
    )
    release_id = r_draft.json()["data"]["release_id"]

    # 学生尝试发布
    resp = client.post(
        f"{COURSE_BUILD}/course/{course.id}/releases/{release_id}/publish",
        json={"run_quality_gate": False},
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. 跨课程隔离
# ---------------------------------------------------------------------------


def test_material_cross_course_access_denied(client, session):
    """教师 B 不能在课程 A 创建材料。"""
    teacher_a = _user(session, "bc_cross_ta", UserRole.TEACHER)
    teacher_b = _user(session, "bc_cross_tb", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="课程 A")

    resp = client.post(
        f"{COURSE_BUILD}/course/{course_a.id}/materials",
        json={"name": "B 试图上传"},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 403


def test_release_cross_course_not_found(client, session):
    """课程 A 的 release 在课程 B 查询 -> 404。"""
    teacher_a = _user(session, "bc_cross_rel_ta", UserRole.TEACHER)
    teacher_b = _user(session, "bc_cross_rel_tb", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="课程 A")
    course_b = _course(session, teacher_b.id, title="课程 B")

    # 在课程 A 创建 release
    r_draft = client.post(
        f"{COURSE_BUILD}/course/{course_a.id}/releases",
        json={"label": "v1"},
        headers=_auth(_token(teacher_a)),
    )
    release_id_a = r_draft.json()["data"]["release_id"]

    # 教师 B 在课程 B 中查询课程 A 的 release -> 404
    resp = client.post(
        f"{COURSE_BUILD}/course/{course_b.id}/releases/{release_id_a}/publish",
        json={"run_quality_gate": False},
        headers=_auth(_token(teacher_b)),
    )
    assert resp.status_code == 404
    assert resp.json()["data"]["error_code"] == "RESOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 9. facade /build 学生视角
# ---------------------------------------------------------------------------


def test_facade_build_student_view_no_draft_init(client, session):
    """学生访问 facade /build 不会初始化草稿，can_build=False。"""
    teacher = _user(session, "bc_stu_facade_teacher", UserRole.TEACHER)
    student = _user(session, "bc_stu_facade_student", UserRole.STUDENT)
    course = _course(session, teacher.id)
    activate_student_membership(session, course.id, student.id)
    session.commit()

    # 教师先初始化草稿
    client.get(f"{FACADE}/course/{course.id}/build", headers=_auth(_token(teacher)))

    # 学生访问
    resp = client.get(
        f"{FACADE}/course/{course.id}/build",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["can_build"] is False
    assert data["can_publish"] is False
    # 学生能看到步骤状态（只读）
    assert len(data["steps"]) == 7
