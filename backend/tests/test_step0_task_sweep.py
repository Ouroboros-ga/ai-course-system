"""Step 0 - 统一课程建设九步实施计划：启动任务扫尾测试。

覆盖决策：后端重启后，遗留的 pending/running 任务必须标为 interrupted，
不再永久显示"解析中"；interrupted 可被 retry() 回到 pending 重新触发解析。

见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §4 Step 0。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import Session as _Session, select

from app.core.security import create_access_token, get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.database import engine
from app.models.document_parse_model import DocumentParseRun, ParseRunStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.task_service import TaskCreateRequest, task_service


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name):
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(session, teacher_id):
    c = Course(
        fanya_course_id=f"step0-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="Step0 Sweep Course",
        title="Step0 Sweep Course",
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    return c


def _session_factory():
    return _Session(engine)


# ---------------------------------------------------------------------------
# 1. 启动扫尾：running 任务 -> interrupted
# ---------------------------------------------------------------------------


def test_sweep_marks_running_tasks_interrupted(session):
    """遗留 running 任务被扫尾标为 interrupted，error_code=INTERRUPTED，retryable=True。"""
    user = _user(session, "step0_sweep_user")
    course = _course(session, user.id)

    # 创建一个任务并手动置为 running（模拟上一进程遗留状态）
    view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse",
        owner_user_id=user.id,
        course_id=course.id,
        input_summary="遗留的解析任务",
        input_payload={"course_id": course.id},
    ))
    task_service.mark_running(session, view.task_id, stage="parse")

    # 扫尾
    report = task_service.sweep_stale_running(_session_factory(), grace_seconds=0)
    assert report["swept"] >= 1
    assert view.task_id in report["task_ids"]

    # 校验状态
    after = task_service.get_task(_session_factory(), view.task_id, owner_user_id=user.id)
    assert after.status == "interrupted"
    assert after.error_code == "INTERRUPTED"
    assert after.retryable is True
    assert "重启" in after.error_message


# ---------------------------------------------------------------------------
# 2. interrupted 可重试回到 pending
# ---------------------------------------------------------------------------


def test_interrupted_task_can_retry_to_pending(session):
    """interrupted 不是业务终态：retry() 可回到 pending 重新触发解析。"""
    user = _user(session, "step0_retry_user")
    course = _course(session, user.id)

    view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse",
        owner_user_id=user.id,
        course_id=course.id,
        input_payload={"course_id": course.id},
    ))
    task_service.mark_running(session, view.task_id, stage="parse")
    task_service.sweep_stale_running(_session_factory(), grace_seconds=0)

    # retry 应回到 pending（不触发 worker，仅重置状态）
    retried = task_service.retry(_session_factory(), view.task_id, operator_user_id=user.id)
    assert retried.status == "pending"
    assert retried.progress == 0


# ---------------------------------------------------------------------------
# 3. 扫尾同步标记 DocumentParseRun
# ---------------------------------------------------------------------------


def test_sweep_syncs_document_parse_run_to_interrupted(session):
    """扫尾时，与 task_id 关联的 DocumentParseRun.status 也同步标为 interrupted。"""
    from app.services.document_parse_service import document_parse_service

    user = _user(session, "step0_run_user")
    course = _course(session, user.id)

    view = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse",
        owner_user_id=user.id,
        course_id=course.id,
        input_payload={"course_id": course.id},
    ))
    task_service.mark_running(session, view.task_id, stage="parse")

    run = document_parse_service.create_run(
        session,
        course_id=course.id,
        material_id="sm_test_material",
        material_version_id="smv_test_version",
        document_id=None,
        task_id=view.task_id,
        initiated_by=user.id,
    )
    run_id = run.run_id
    # 关键：提交并清空 session 缓存，避免 fixture session 与扫尾 session
    # 在 SQLite 单写锁下互相阻塞（生产 PostgreSQL 无此问题）。
    session.commit()
    session.expunge_all()

    task_service.sweep_stale_running(_session_factory(), grace_seconds=0)

    # DocumentParseRun 应被同步标记为 interrupted
    sf = _session_factory()
    with sf as s:
        refreshed = s.exec(
            select(DocumentParseRun).where(DocumentParseRun.run_id == run_id)
        ).first()
        assert refreshed is not None
        assert refreshed.status == "interrupted"
        assert refreshed.error_code == "INTERRUPTED"
        assert refreshed.finished_at is not None


# ---------------------------------------------------------------------------
# 4. 扫尾幂等：已终态任务不再被扫
# ---------------------------------------------------------------------------


def test_sweep_is_idempotent_for_terminal_tasks(session):
    """已 succeeded/failed 的任务不应被扫尾改动。"""
    user = _user(session, "step0_idem_user")
    course = _course(session, user.id)

    succeeded = task_service.create_task(session, TaskCreateRequest(
        task_type="document_parse",
        owner_user_id=user.id,
        course_id=course.id,
        input_payload={"course_id": course.id},
    ))
    task_service.mark_running(session, succeeded.task_id)
    task_service.mark_succeeded(session, succeeded.task_id, result_ref="ok")

    report = task_service.sweep_stale_running(_session_factory(), grace_seconds=0)
    assert succeeded.task_id not in report["task_ids"]

    after = task_service.get_task(_session_factory(), succeeded.task_id, owner_user_id=user.id)
    assert after.status == "succeeded"
