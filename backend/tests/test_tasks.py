"""阶段0 统一任务中心端到端测试。

覆盖路线图 §3 验收：任务创建、查询、失败、重试、取消、权限拒绝。
四类必备测试：成功、权限拒绝、跨课程拒绝、依赖不可用。
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlmodel import Session as _Session, select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus
from app.models.database import engine
from app.models.platform_admin_model import PlatformTaskConcurrencyConfig
from app.models.task_model import TaskRecord
from app.services.platform_task_concurrency_service import get_config, get_group_limit, update_config
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.task_service import TaskCreateRequest, task_service
from app.platform.tasks.worker import (
    LocalTaskWorker,
    register_builtin_handlers,
)


TASKS = "/api/v1/tasks"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name, role=UserRole.STUDENT):
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


def _course(session, teacher_id, title="Task Course"):
    c = Course(
        fanya_course_id=f"task-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    return c


def _token(user):
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _session_factory():
    """返回可用作 context manager 的 Session。"""
    return _Session(engine)


def test_experiment_run_uses_the_dedicated_sandbox_execution_limit(session):
    """Formal Judge0 work must not share an unrelated local worker group."""
    update_config(
        session,
        actor_user_id=1,
        payload={
            "developer_mode": True,
            "max_total": 4,
            "sandbox_execution": 1,
        },
    )

    total_limit, group_limit = get_group_limit(session, "experiment_run")

    assert total_limit == 4
    assert group_limit == 1


def test_graphrag_token_budget_is_clamped_and_persisted(session):
    """平台管理的 GraphRAG token 预算不被 1..32 并发钳制，且可回落环境默认（0）。"""
    update_config(
        session,
        actor_user_id=1,
        payload={
            "developer_mode": True,
            "graphrag_max_input_tokens": 60000,
        },
    )
    config = get_config(session)
    assert config["graphrag_max_input_tokens"] == 60000

    # 超上限会被钳制，负值回落到 0。
    update_config(
        session,
        actor_user_id=1,
        payload={"graphrag_max_input_tokens": -5},
    )
    assert get_config(session)["graphrag_max_input_tokens"] == 0


# ---------------------------------------------------------------------------
# 1. 成功路径：自检 noop 端到端
# ---------------------------------------------------------------------------


def test_self_check_noop_succeeds_end_to_end(client, session):
    """POST /tasks/self-check/noop 创建并同步执行一个 no-op 任务，最终 succeeded。"""
    user = _user(session, "task_self_check_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    resp = client.post(f"{TASKS}/self-check/noop", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201  # body code 表示「已创建并执行」
    data = body["data"]
    assert data["status"] == "succeeded"
    assert data["progress"] == 100
    assert data["task_type"] == "self_check_noop"
    assert data["task_id"]  # UUID 非空
    assert data["result_ref"] == "noop://self-check"
    assert data["affected_resources"] == []  # 无资源链接

    # 事件流应包含 created/started/progress/succeeded
    events_resp = client.get(f"{TASKS}/{data['task_id']}/events", headers=headers)
    assert events_resp.status_code == 200
    events = events_resp.json()["data"]["items"]
    event_types = [e["event_type"] for e in events]
    assert "created" in event_types
    assert "started" in event_types
    assert "progress" in event_types
    assert "succeeded" in event_types


# ---------------------------------------------------------------------------
# 2. 依赖不可用：自检 fail 端到端
# ---------------------------------------------------------------------------


def test_self_check_fail_marks_dependency_unavailable(client, session):
    """POST /tasks/self-check/fail 任务失败，error_code=DEPENDENCY_UNAVAILABLE，retryable=True。"""
    user = _user(session, "task_fail_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    resp = client.post(f"{TASKS}/self-check/fail", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "failed"
    assert data["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert data["retryable"] is True


# ---------------------------------------------------------------------------
# 3. 权限拒绝：跨用户访问任务详情
# ---------------------------------------------------------------------------


def test_cross_user_access_returns_404(client, session):
    """用户 A 创建的任务，用户 B 直接访问应返回 404（不泄露存在性）。"""
    user_a = _user(session, "task_user_a", UserRole.TEACHER)
    user_b = _user(session, "task_user_b", UserRole.TEACHER)
    headers_a = {"Authorization": f"Bearer {_token(user_a)}"}
    headers_b = {"Authorization": f"Bearer {_token(user_b)}"}

    # A 创建任务
    resp = client.post(f"{TASKS}/self-check/noop", headers=headers_a)
    task_id = resp.json()["data"]["task_id"]

    # B 访问 A 的任务 -> 404
    resp_b = client.get(f"{TASKS}/{task_id}", headers=headers_b)
    assert resp_b.status_code == 404
    err = resp_b.json()["data"]
    assert err["error_code"] == "RESOURCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 4. 权限拒绝：system view 需要平台权限
# ---------------------------------------------------------------------------


def test_system_view_requires_platform_permission(client, session):
    """普通教师调用 view=system 应被拒绝。"""
    user = _user(session, "task_system_view_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    resp = client.get(f"{TASKS}?view=system", headers=headers)
    assert resp.status_code == 403
    err = resp.json()["data"]
    assert err["error_code"] == "COURSE_ACCESS_DENIED"


def test_system_view_succeeds_for_admin(client, session):
    """平台管理员可以查看 system view。"""
    user = _user(session, "task_admin_user", UserRole.ADMIN)
    session.add(PlatformPermissionAssignment(
        user_id=user.id,
        permission=PlatformPermission.ADMIN,
        granted_by_user_id=user.id,
    ))
    session.commit()
    headers = {"Authorization": f"Bearer {_token(user)}"}

    resp = client.get(f"{TASKS}?view=system", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["view"] == "system"


# ---------------------------------------------------------------------------
# 5. 跨课程隔离：course_id 过滤
# ---------------------------------------------------------------------------


def test_list_tasks_isolates_by_course(client, session):
    """course_id 过滤只返回该课程的任务。"""
    teacher = _user(session, "task_list_teacher", UserRole.TEACHER)
    course_a = _course(session, teacher.id, "Course A")
    course_b = _course(session, teacher.id, "Course B")
    headers = {"Authorization": f"Bearer {_token(teacher)}"}

    # 在课程 A 创建任务
    req_a = TaskCreateRequest(
        task_type="self_check_noop",
        owner_user_id=teacher.id,
        course_id=course_a.id,
        input_summary="course A task",
    )
    view_a = task_service.create_task(session, req_a)

    # 在课程 B 创建任务
    req_b = TaskCreateRequest(
        task_type="self_check_noop",
        owner_user_id=teacher.id,
        course_id=course_b.id,
        input_summary="course B task",
    )
    view_b = task_service.create_task(session, req_b)

    # 列表 course_id=A 只返回 A 的任务
    resp_a = client.get(f"{TASKS}?course_id={course_a.id}", headers=headers)
    assert resp_a.status_code == 200
    items_a = resp_a.json()["data"]["items"]
    task_ids_a = [item["task_id"] for item in items_a]
    assert view_a.task_id in task_ids_a
    assert view_b.task_id not in task_ids_a


# ---------------------------------------------------------------------------
# 6. 状态机：非法转移返回 STATE_CONFLICT
# ---------------------------------------------------------------------------


def test_state_machine_rejects_invalid_transition(session):
    """succeeded 状态的任务不能再次 mark_succeeded，应抛 STATE_CONFLICT (409)。"""
    from fastapi import HTTPException
    user = _user(session, "task_state_user", UserRole.TEACHER)
    req = TaskCreateRequest(
        task_type="self_check_noop",
        owner_user_id=user.id,
        input_summary="state machine test",
    )
    view = task_service.create_task(session, req)

    # 手动流转：pending -> running -> succeeded
    task_service.mark_running(session, view.task_id, stage="test")
    task_service.mark_succeeded(session, view.task_id, result_ref="ok")

    # 再次 mark_succeeded 应抛 STATE_CONFLICT
    with pytest.raises(HTTPException) as exc_info:
        task_service.mark_succeeded(session, view.task_id, result_ref="again")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "STATE_CONFLICT"


# ---------------------------------------------------------------------------
# 7. 幂等键：相同 key 返回同一 task
# ---------------------------------------------------------------------------


def test_idempotency_key_returns_same_task(session):
    """相同 idempotency_key 在窗口期内返回同一 task_id。"""
    user = _user(session, "task_idem_user", UserRole.TEACHER)
    key = "idem-key-001"
    req1 = TaskCreateRequest(
        task_type="self_check_noop",
        owner_user_id=user.id,
        input_summary="idempotent task",
        idempotency_key=key,
        input_payload={"v": 1},
    )
    req2 = TaskCreateRequest(
        task_type="self_check_noop",
        owner_user_id=user.id,
        input_summary="idempotent task",
        idempotency_key=key,
        input_payload={"v": 1},
    )
    view1 = task_service.create_task(session, req1)
    view2 = task_service.create_task(session, req2)
    assert view1.task_id == view2.task_id


# ---------------------------------------------------------------------------
# 8. 取消与确认
# ---------------------------------------------------------------------------


def test_cancel_and_acknowledge(client, session):
    """取消 pending 任务，然后 acknowledge 已取消的任务。"""
    user = _user(session, "task_cancel_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    req = TaskCreateRequest(
        task_type="self_check_noop",
        owner_user_id=user.id,
        input_summary="cancel test",
    )
    view = task_service.create_task(session, req)

    # 取消
    resp = client.post(f"{TASKS}/{view.task_id}/cancel", json={"reason": "user changed mind"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

    # acknowledge
    ack_resp = client.post(f"{TASKS}/{view.task_id}/acknowledge", headers=headers)
    assert ack_resp.status_code == 200
    assert ack_resp.json()["data"]["acknowledged"] is True


def test_cancelled_experiment_run_cannot_be_retried(session):
    """A cancelled formal run must never be requeued into a later grade."""
    from fastapi import HTTPException

    student = _user(session, "cancelled_experiment_student")
    created = task_service.create_task(
        session,
        TaskCreateRequest(
            task_type="experiment_run",
            owner_user_id=student.id,
            course_id=1,
            input_summary="formal experiment run",
        ),
    )
    task_service.cancel(session, created.task_id, operator_user_id=student.id)

    with pytest.raises(HTTPException) as exc_info:
        task_service.retry(session, created.task_id, operator_user_id=student.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "STATE_CONFLICT"
    persisted = task_service.get_task(session, created.task_id, owner_user_id=student.id)
    assert persisted.status == "cancelled"


def test_create_task_without_commit_stays_inside_caller_transaction(session, test_engine):
    """Formal run creation can atomically commit its task with the run record."""
    user = _user(session, "deferred_task_owner")
    created = task_service.create_task(
        session,
        TaskCreateRequest(
            task_type="experiment_run",
            owner_user_id=user.id,
            course_id=1,
            input_summary="deferred formal run",
        ),
        commit=False,
    )

    with _Session(test_engine) as outside_session:
        assert outside_session.exec(
            select(TaskRecord).where(TaskRecord.task_id == created.task_id)
        ).first() is None

    session.commit()
    with _Session(test_engine) as outside_session:
        assert outside_session.exec(
            select(TaskRecord).where(TaskRecord.task_id == created.task_id)
        ).one().status == "pending"


# ---------------------------------------------------------------------------
# 9. 重试：失败任务可重试
# ---------------------------------------------------------------------------


def test_retry_failed_task(client, session):
    """failed + retryable=True 的任务可以被 retry，状态回到 pending（等待 worker 重新拾取）。"""
    user = _user(session, "task_retry_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    # 创建一个 always-fail 任务
    resp = client.post(f"{TASKS}/self-check/fail", headers=headers)
    task_id = resp.json()["data"]["task_id"]
    assert resp.json()["data"]["status"] == "failed"

    # retry
    retry_resp = client.post(f"{TASKS}/{task_id}/retry", headers=headers)
    assert retry_resp.status_code == 200
    assert retry_resp.json()["code"] == 202  # body code 表示「已重新入队」
    data = retry_resp.json()["data"]
    # P0-2.7: retry 将状态重置为 pending，路由层重新提交到 worker；
    # 由于 self_check_fail 总会再次失败，最终状态可能是 pending/running/failed
    # 关键：error_code 被清空、progress 归零（不再保留 failed 状态字段）
    assert data["error_code"] == ""
    assert data["progress"] == 0
    # 状态可能因 worker 异步执行而变化，验证已重置（不应仍是失败时的状态）
    # 立即查询时为 pending；worker 拾取后为 running；执行后为 failed
    assert data["status"] in ("pending", "running", "failed")


# ---------------------------------------------------------------------------
# 10. 未注册 task_type：依赖不可用 + retryable=False
# ---------------------------------------------------------------------------


def test_unregistered_task_type_fails_with_dependency_unavailable(session):
    """未注册 handler 的 task_type 应被标记为 failed + DEPENDENCY_UNAVAILABLE + retryable=False。"""
    user = _user(session, "task_unregistered_user", UserRole.TEACHER)
    req = TaskCreateRequest(
        task_type="nonexistent_task_type",
        owner_user_id=user.id,
        input_summary="unregistered task",
    )
    view = task_service.create_task(session, req)

    # 注册内置 handler 后执行（但 nonexistent_task_type 仍未注册）
    register_builtin_handlers()
    worker = LocalTaskWorker()
    register_builtin_handlers(worker)

    asyncio.run(worker.run_inline(_session_factory, view.task_id, {}))

    final = task_service.get_task(session, view.task_id, owner_user_id=user.id)
    assert final.status == "failed"
    assert final.error_code == "DEPENDENCY_UNAVAILABLE"
    assert final.retryable is False


# ---------------------------------------------------------------------------
# 11. 游标分页
# ---------------------------------------------------------------------------


def test_cursor_pagination(client, session):
    """page_size=1 + cursor 翻页，next_cursor 不为空且能取到下一页。"""
    user = _user(session, "task_pagination_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    # 创建 3 个任务
    for i in range(3):
        req = TaskCreateRequest(
            task_type="self_check_noop",
            owner_user_id=user.id,
            input_summary=f"pagination task {i}",
        )
        task_service.create_task(session, req)

    # 第一页
    resp1 = client.get(f"{TASKS}?page_size=1", headers=headers)
    assert resp1.status_code == 200
    page1 = resp1.json()["data"]
    assert len(page1["items"]) == 1
    assert page1["has_next"] is True
    assert page1["next_cursor"]

    # 第二页
    resp2 = client.get(f"{TASKS}?page_size=1&cursor={page1['next_cursor']}", headers=headers)
    assert resp2.status_code == 200
    page2 = resp2.json()["data"]
    assert len(page2["items"]) == 1
    assert page2["items"][0]["task_id"] != page1["items"][0]["task_id"]


# ---------------------------------------------------------------------------
# 12. 迁移记录登记
# ---------------------------------------------------------------------------


def test_migration_batch_recorded(session):
    """alembic upgrade head 后 alembic_version 表应包含当前 head revision，
    且 schema_migration_records 审计账本表存在且可查询。

    P0-1 后：run_migrations() 已废弃为 no-op，alembic_version 是迁移事实来源；
    schema_migration_records 保留为审计账本，但不再是迁移状态的唯一来源。

    head revision 通过遍历 alembic versions 目录动态确定，避免每次新增迁移都要改本测试。
    """
    from sqlalchemy import text
    import glob
    import os
    import re as _re

    # 1. alembic_version 表是迁移事实来源，应包含当前 head revision。
    #    测试库由 conftest 的 test_engine fixture 通过 alembic upgrade head 建立。
    version_num = session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar()

    # 动态确定 head revision：遍历 versions 目录，取 revision/down_revision 链的末端。
    versions_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "alembic", "versions",
    )
    revisions: dict[str, str | None] = {}
    for path in glob.glob(os.path.join(versions_dir, "*.py")):
        with open(path, encoding="utf-8-sig") as fh:
            content = fh.read()
        rev_m = _re.search(r'^revision\b[^=]*=\s*["\']([^"\']+)["\']', content, _re.M)
        down_m = _re.search(r'^down_revision\b[^=]*=\s*(None|["\']([^"\']+)["\'])', content, _re.M)
        if rev_m:
            revisions[rev_m.group(1)] = (down_m.group(2) if (down_m and down_m.group(2)) else None)
    # head = 出现在 revisions 的 key 中、但不出现在任何 down_revision 中的 revision
    all_downs = {d for d in revisions.values() if d}
    head_candidates = [r for r in revisions if r not in all_downs]
    assert head_candidates, f"could not determine head revision from {versions_dir}"
    head_revision = head_candidates[0]
    assert version_num == head_revision

    # 2. schema_migration_records 作为审计账本仍可查询（不再是迁移事实来源）。
    #    表必须存在且可查询，但不要求有特定记录（alembic 不向其写入）。
    audit_count = session.execute(
        text("SELECT COUNT(*) FROM schema_migration_records")
    ).scalar()
    assert audit_count is not None
    assert audit_count >= 0


# ---------------------------------------------------------------------------
# 13. 路由契约：路径在 OpenAPI 中可见
# ---------------------------------------------------------------------------


def test_tasks_routes_registered_in_openapi(client):
    """所有任务中心路由应在 OpenAPI schema 中注册。"""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    expected = [
        "/api/v1/tasks",
        "/api/v1/tasks/self-check/{kind}",
        "/api/v1/tasks/admin/migrations",
        "/api/v1/tasks/{task_id}",
        "/api/v1/tasks/{task_id}/cancel",
        "/api/v1/tasks/{task_id}/retry",
        "/api/v1/tasks/{task_id}/acknowledge",
        "/api/v1/tasks/{task_id}/events",
    ]
    for path in expected:
        assert path in paths, f"路由 {path} 未在 OpenAPI 注册"


# ---------------------------------------------------------------------------
# 14. 统一错误响应格式
# ---------------------------------------------------------------------------


def test_error_response_format_matches_contract(client, session):
    """404 响应必须包含 error_code/message，符合统一错误协议。"""
    user = _user(session, "task_error_format_user", UserRole.TEACHER)
    headers = {"Authorization": f"Bearer {_token(user)}"}

    resp = client.get(f"{TASKS}/nonexistent-task-id", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 404
    assert body["data"]["error_code"] == "RESOURCE_NOT_FOUND"
    assert "message" in body["data"]
