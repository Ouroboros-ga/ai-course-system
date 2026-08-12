"""阶段6 课程实验、Judge0 与 CodingAgent API

契约来源：PageDesign前端API契约规划.md §3.7

权限模型：
- experiment.configure / experiment.assign：教师管理实验定义、版本、测试用例
- experiment.run：学生创建尝试、提交代码、请求提示
- experiment.view：学生/教师查看实验列表与详情
- 跨课程严格隔离：所有查询都按 course_id 过滤
- 学生只能看自己的尝试，教师只能管理所属课程实验
- 最终评分型结果才产生 LearningEvidence；单次运行日志不直接修改认知状态
- Judge0 不可用时课程学习页可以降级，且保留明确恢复提示
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.experiment_model import (
    AttemptStatus,
    CodingHintLevel,
    ExperimentPublishStatus,
    RunOutcome,
)
from app.services.course_access_service import require_course_permission as _base_require_course_permission
from app.services.experiment_service import (
    attempt_service,
    coding_hint_service,
    definition_service,
    finalize_service,
    run_service,
    version_service,
)
from app.services.coding_eduagent_service import coding_eduagent, serialize_diagnosis
from app.models.coding_diagnosis_model import CodingDiagnosisRecord


experiment_router = APIRouter()


def _require_experiment_platform(session: Session, current_user: dict, course_id: int, permission: str):
    """The course experiment platform requires both coupled capability flags."""
    context = _base_require_course_permission(session, current_user, course_id, permission)
    if not context.capabilities.get("experiment", False) or not context.capabilities.get("coding_sandbox", False):
        raise HTTPException(
            status_code=403,
            detail={"error_code": "EXPERIMENT_PLATFORM_DISABLED", "message": "课程实验平台未启用"},
        )
    return context


# All routes in this module are inside the coupled experiment platform.  Keep
# existing call sites fail-closed without relying on each future endpoint to
# remember both capability checks.
require_course_permission = _require_experiment_platform


# ---------------------------------------------------------------------------
# 请求 schema
# ---------------------------------------------------------------------------


class DefinitionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    language_whitelist: list[str] = Field(default_factory=list)
    knowledge_node_ids: list[int] = Field(default_factory=list)
    max_attempts: int = Field(default=3, ge=1, le=20)
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)


class DefinitionUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    language_whitelist: Optional[list[str]] = None
    max_attempts: Optional[int] = Field(default=None, ge=1, le=20)
    cooldown_minutes: Optional[int] = Field(default=None, ge=0, le=1440)


class VersionCreateRequest(BaseModel):
    label: str = Field(default="", max_length=100)
    cpu_time_limit: int = Field(default=5, ge=1, le=30)
    memory_limit: int = Field(default=128_000, ge=16_000, le=512_000)
    wall_time_limit: int = Field(default=10, ge=1, le=60)
    max_processes: int = Field(default=30, ge=1, le=120)
    max_file_size: int = Field(default=1024, ge=1, le=8192)
    passing_score: float = Field(default=1.0, ge=1.0, le=1.0)
    writes_formal_evidence: bool = True
    test_cases: list[dict] = Field(default_factory=list)
    activate: bool = True


class AttemptCreateRequest(BaseModel):
    return_anchor: dict = Field(default_factory=dict)


class RunCreateRequest(BaseModel):
    language: str = Field(min_length=1, max_length=50)
    source_code: str = Field(min_length=1, max_length=100_000)


class HintRequest(BaseModel):
    hint_level: CodingHintLevel
    reason_codes: list[str] = Field(default_factory=list)
    hint_text: str = Field(default="", max_length=10_000)
    hint_metadata: dict = Field(default_factory=dict)


class HintReviewRequest(BaseModel):
    decision: str = Field(..., description="approved|rejected")
    note: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _serialize_definition(d) -> dict[str, Any]:
    return {
        "experiment_id": d.experiment_id,
        "course_id": d.course_id,
        "title": d.title,
        "description": d.description,
        "language_whitelist": d.language_whitelist,
        "default_version_id": d.default_version_id,
        "publish_status": d.publish_status.value,
        "knowledge_node_ids": d.knowledge_node_ids,
        "max_attempts": d.max_attempts,
        "cooldown_minutes": d.cooldown_minutes,
        "created_by": d.created_by,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialize_version(v, include_test_cases: bool = False, include_hidden: bool = False) -> dict[str, Any]:
    data = {
        "version_id": v.version_id,
        "experiment_id": v.experiment_id,
        "course_id": v.course_id,
        "version_number": v.version_number,
        "label": v.label,
        "cpu_time_limit": v.cpu_time_limit,
        "memory_limit": v.memory_limit,
        "wall_time_limit": v.wall_time_limit,
        "max_processes": v.max_processes,
        "max_file_size": v.max_file_size,
        "enable_network": v.enable_network,
        "passing_score": v.passing_score,
        "writes_formal_evidence": v.writes_formal_evidence,
        "is_locked": v.is_locked,
        "is_active": v.is_active,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }
    if include_test_cases:
        # include_hidden 仅教师视图；学生视图始终 False
        data["test_cases"] = [
            _serialize_test_case(tc, reveal_hidden=include_hidden)
            for tc in v._test_cases
        ] if hasattr(v, "_test_cases") else []
    return data


def _serialize_test_case(tc, reveal_hidden: bool = False) -> dict[str, Any]:
    """序列化测试用例；隐藏测试仅教师可见，学生视图不暴露 stdin/expected"""
    if tc.is_hidden and not reveal_hidden:
        return {
            "case_id": tc.case_id,
            "case_name": f"hidden_{tc.case_id[:8]}",
            "is_hidden": True,
            "weight": tc.weight,
        }
    return {
        "case_id": tc.case_id,
        "case_name": tc.case_name,
        "is_hidden": tc.is_hidden,
        "weight": tc.weight,
        "stdin": tc.stdin,
        "expected_stdout": tc.expected_stdout,
        "time_limit_override": tc.time_limit_override,
    }


def _serialize_attempt(a, include_student_id: bool = True) -> dict[str, Any]:
    data = {
        "attempt_id": a.attempt_id,
        "experiment_id": a.experiment_id,
        "version_id": a.version_id,
        "course_id": a.course_id,
        "status": a.status.value,
        "started_at": a.started_at.isoformat() if a.started_at else None,
        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        "finalized_at": a.finalized_at.isoformat() if a.finalized_at else None,
        "final_score": a.final_score,
        "passed": a.passed,
        "evidence_id": a.evidence_id,
        "return_anchor": a.return_anchor,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }
    if include_student_id:
        data["student_id"] = a.student_id
    return data


def _serialize_run(r) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "attempt_id": r.attempt_id,
        "course_id": r.course_id,
        "language": r.language,
        "outcome": r.outcome.value,
        "passed_count": r.passed_count,
        "total_count": r.total_count,
        "score": r.score,
        "compile_ok": r.compile_ok,
        "compile_message": r.compile_message,
        "runtime_message": r.runtime_message,
        "test_summary": r.test_summary,
        "cpu_time_ms": r.cpu_time_ms,
        "wall_time_ms": r.wall_time_ms,
        "memory_kb": r.memory_kb,
        "error_code": r.error_code,
        "error_message": r.error_message,
        "task_id": r.task_id,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _serialize_hint(h) -> dict[str, Any]:
    return {
        "hint_id": h.hint_id,
        "attempt_id": h.attempt_id,
        "course_id": h.course_id,
        "student_id": h.student_id,
        "hint_level": h.hint_level.value,
        "reason_codes": h.reason_codes,
        "policy_version": h.policy_version,
        "hint_text": h.hint_text,
        "hint_metadata": h.hint_metadata,
        "fulfilled_by_agent": h.fulfilled_by_agent,
        "teacher_reviewed": h.teacher_reviewed,
        "teacher_decision": h.teacher_decision,
        "teacher_note": h.teacher_note,
        "requested_at": h.requested_at.isoformat() if h.requested_at else None,
        "fulfilled_at": h.fulfilled_at.isoformat() if h.fulfilled_at else None,
        "reviewed_at": h.reviewed_at.isoformat() if h.reviewed_at else None,
    }


# ---------------------------------------------------------------------------
# 实验定义
# ---------------------------------------------------------------------------


@experiment_router.get("/course/{course_id}/definitions")
async def list_definitions(
    course_id: int,
    publish_status: Optional[ExperimentPublishStatus] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程实验定义。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    # 学生仅看 published；教师可看全部
    if context.role is None or context.role.value == "student":
        publish_status = ExperimentPublishStatus.PUBLISHED
    definitions = definition_service.list_definitions(
        session, course_id=course_id, publish_status=publish_status,
    )
    return unified_response(
        code=200,
        message="获取实验列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_definition(d) for d in definitions],
            "total": len(definitions),
        },
    )


@experiment_router.post("/course/{course_id}/definitions")
async def create_definition(
    course_id: int,
    payload: DefinitionCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师创建实验定义。"""
    _require_experiment_platform(session, current_user, course_id, "experiment.configure")
    user_id = int(current_user["user_id"])
    definition = definition_service.create_definition(
        session,
        course_id=course_id,
        title=payload.title,
        description=payload.description,
        language_whitelist=payload.language_whitelist,
        knowledge_node_ids=payload.knowledge_node_ids,
        max_attempts=payload.max_attempts,
        cooldown_minutes=payload.cooldown_minutes,
        created_by=user_id,
    )
    session.commit()
    session.refresh(definition)
    return unified_response(
        code=201,
        message="实验定义已创建",
        data=_serialize_definition(definition),
    )


@experiment_router.get("/course/{course_id}/definitions/{experiment_id}")
async def get_definition(
    course_id: int,
    experiment_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取实验定义详情（学生视图不返回 draft/archived）。"""
    context = _require_experiment_platform(session, current_user, course_id, "experiment.view")
    definition = definition_service.get_definition(
        session, course_id=course_id, experiment_id=experiment_id,
    )
    if context.role is None or context.role.value == "student":
        if definition.publish_status != ExperimentPublishStatus.PUBLISHED:
            from app.core.exceptions import reject_resource_not_found
            reject_resource_not_found(f"实验 {experiment_id} 不存在")
    return unified_response(
        code=200,
        message="获取实验详情成功",
        data=_serialize_definition(definition),
    )


@experiment_router.put("/course/{course_id}/definitions/{experiment_id}")
async def update_definition(
    course_id: int,
    experiment_id: str,
    payload: DefinitionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师更新实验定义。"""
    _require_experiment_platform(session, current_user, course_id, "experiment.configure")
    definition = definition_service.update_definition(
        session,
        course_id=course_id,
        experiment_id=experiment_id,
        title=payload.title,
        description=payload.description,
        language_whitelist=payload.language_whitelist,
        max_attempts=payload.max_attempts,
        cooldown_minutes=payload.cooldown_minutes,
    )
    session.commit()
    session.refresh(definition)
    return unified_response(
        code=200,
        message="实验定义已更新",
        data=_serialize_definition(definition),
    )


@experiment_router.post("/course/{course_id}/definitions/{experiment_id}/publish")
async def publish_definition(
    course_id: int,
    experiment_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师发布实验。"""
    _require_experiment_platform(session, current_user, course_id, "experiment.configure")
    definition = definition_service.publish_definition(
        session, course_id=course_id, experiment_id=experiment_id,
    )
    session.commit()
    session.refresh(definition)
    return unified_response(
        code=200,
        message="实验已发布",
        data=_serialize_definition(definition),
    )


@experiment_router.post("/course/{course_id}/definitions/{experiment_id}/archive")
async def archive_definition(
    course_id: int,
    experiment_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师归档实验。"""
    _require_experiment_platform(session, current_user, course_id, "experiment.configure")
    definition = definition_service.archive_definition(
        session, course_id=course_id, experiment_id=experiment_id,
    )
    session.commit()
    session.refresh(definition)
    return unified_response(
        code=200,
        message="实验已归档",
        data=_serialize_definition(definition),
    )


# ---------------------------------------------------------------------------
# 实验版本与测试用例
# ---------------------------------------------------------------------------


@experiment_router.get("/{experiment_id}/versions")
async def list_versions(
    experiment_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出实验版本。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    versions = version_service.list_versions(
        session, course_id=course_id, experiment_id=experiment_id,
    )
    # 学生仅看 active 版本
    if context.role is None or context.role.value == "student":
        versions = [v for v in versions if v.is_active]
    return unified_response(
        code=200,
        message="获取实验版本列表成功",
        data={
            "course_id": course_id,
            "experiment_id": experiment_id,
            "items": [_serialize_version(v) for v in versions],
            "total": len(versions),
        },
    )


@experiment_router.post("/{experiment_id}/versions")
async def create_version(
    experiment_id: str,
    payload: VersionCreateRequest,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师创建实验版本。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    user_id = int(current_user["user_id"])
    version = version_service.create_version(
        session,
        course_id=course_id,
        experiment_id=experiment_id,
        label=payload.label,
        cpu_time_limit=payload.cpu_time_limit,
        memory_limit=payload.memory_limit,
        wall_time_limit=payload.wall_time_limit,
        max_processes=payload.max_processes,
        max_file_size=payload.max_file_size,
        passing_score=payload.passing_score,
        writes_formal_evidence=payload.writes_formal_evidence,
        created_by=user_id,
        test_cases=payload.test_cases,
        activate=payload.activate,
    )
    session.commit()
    session.refresh(version)
    return unified_response(
        code=201,
        message="实验版本已创建",
        data=_serialize_version(version),
    )


@experiment_router.get("/versions/{version_id}")
async def get_version(
    version_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取实验版本详情（含测试用例；学生视图不暴露隐藏测试 stdin/expected）。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    version = version_service.get_version(
        session, course_id=course_id, version_id=version_id,
    )
    # 学生视图：返回隐藏测试条目但不暴露 stdin/expected_stdout；教师视图完整暴露
    reveal_hidden = context.role is not None and context.role.value != "student"
    test_cases = version_service.list_test_cases(
        session, course_id=course_id, version_id=version_id,
        include_hidden=True,
    )
    data = _serialize_version(version)
    data["test_cases"] = [_serialize_test_case(tc, reveal_hidden=reveal_hidden) for tc in test_cases]
    return unified_response(code=200, message="获取实验版本详情成功", data=data)


@experiment_router.put("/versions/{version_id}")
async def update_version(
    version_id: str,
    payload: VersionCreateRequest,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师更新实验版本（仅未锁定时；锁定后需先解锁）。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    version = version_service.get_version(
        session, course_id=course_id, version_id=version_id,
    )
    if version.is_locked:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("版本已锁定，无法修改")
    # 版本不可变，更新通过创建新版本实现；这里仅更新可变元数据
    version.label = payload.label
    version.passing_score = payload.passing_score
    version.writes_formal_evidence = payload.writes_formal_evidence
    session.add(version)
    session.commit()
    session.refresh(version)
    return unified_response(
        code=200,
        message="实验版本已更新",
        data=_serialize_version(version),
    )


@experiment_router.post("/versions/{version_id}/activate")
async def activate_version(
    version_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师激活实验版本。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    version = version_service.activate_version(
        session, course_id=course_id, version_id=version_id,
    )
    session.commit()
    session.refresh(version)
    return unified_response(
        code=200,
        message="实验版本已激活",
        data=_serialize_version(version),
    )


@experiment_router.post("/versions/{version_id}/reference-preview")
async def preview_reference_solution(
    version_id: str,
    payload: ReferencePreviewRequest,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Validate a transient reference solution without storing its source."""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    from app.services.experiment_service import publish_validator

    result = publish_validator.verify_reference_solution(
        session,
        course_id=course_id,
        version_id=version_id,
        language=payload.language,
        source_code=payload.source_code,
    )
    session.commit()
    return unified_response(code=200, message="参考解预览完成", data=result)


@experiment_router.post("/versions/{version_id}/lock")
async def lock_version(
    version_id: str,
    course_id: int = Query(...),
    locked: bool = Query(True),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师锁定/解锁实验版本。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    version = version_service.lock_version(
        session, course_id=course_id, version_id=version_id, locked=locked,
    )
    session.commit()
    session.refresh(version)
    return unified_response(
        code=200,
        message="版本已锁定" if locked else "版本已解锁",
        data=_serialize_version(version),
    )


# ---------------------------------------------------------------------------
# 学生尝试
# ---------------------------------------------------------------------------


@experiment_router.post("/{experiment_id}/attempts")
async def create_attempt(
    experiment_id: str,
    payload: AttemptCreateRequest,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生创建一次实验尝试。"""
    require_course_permission(session, current_user, course_id, "experiment.run")
    user_id = int(current_user["user_id"])
    attempt = attempt_service.create_attempt(
        session,
        course_id=course_id,
        experiment_id=experiment_id,
        student_id=user_id,
        return_anchor=payload.return_anchor,
    )
    session.commit()
    session.refresh(attempt)
    return unified_response(
        code=201,
        message="实验尝试已创建",
        data=_serialize_attempt(attempt),
    )


@experiment_router.get("/attempts/{attempt_id}")
async def get_attempt(
    attempt_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取尝试详情（学生只能看自己的尝试）。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    # 学生只能看自己
    student_filter = None
    if context.role is not None and context.role.value == "student":
        student_filter = int(current_user["user_id"])
    attempt = attempt_service.get_attempt(
        session, course_id=course_id, attempt_id=attempt_id, student_id=student_filter,
    )
    # 学生视图不暴露 student_id（即使有权限）
    include_student_id = context.role is not None and context.role.value != "student"
    return unified_response(
        code=200,
        message="获取尝试详情成功",
        data=_serialize_attempt(attempt, include_student_id=include_student_id),
    )


# ---------------------------------------------------------------------------
# 代码运行
# ---------------------------------------------------------------------------


@experiment_router.post("/attempts/{attempt_id}/runs", status_code=202)
async def create_run(
    attempt_id: str,
    payload: RunCreateRequest,
    course_id: int = Query(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建正式异步评测任务；永不在请求内等待 Judge0。"""
    context = require_course_permission(session, current_user, course_id, "experiment.run")
    if not context.capabilities.get("coding_sandbox", False):
        raise HTTPException(
            status_code=403,
            detail={"error_code": "CODING_SANDBOX_DISABLED", "message": "课程未启用代码沙箱能力"},
        )
    user_id = int(current_user["user_id"])

    # 创建 ExperimentRun（PENDING）+ TaskRecord，返回 202 + task_id。
    # 同一 Idempotency-Key 返回现有运行，不重复评分或生成实验记录。
    from app.services.task_service import TaskCreateRequest, task_service

    existing = run_service.get_run_by_idempotency(
        session, attempt_id=attempt_id, idempotency_key=idempotency_key,
    )
    if existing is not None:
        return unified_response(
            code=202,
            message="代码运行任务已存在",
            data={"run_id": existing.run_id, "task_id": existing.task_id, "status": existing.outcome.value},
        )

    attempt = attempt_service.get_attempt(
        session, course_id=course_id, attempt_id=attempt_id, student_id=user_id,
    )
    if attempt.status == AttemptStatus.IN_PROGRESS:
        attempt_service.submit_attempt(session, course_id=course_id, attempt_id=attempt_id)
    elif attempt.status != AttemptStatus.SUBMITTED:
        raise HTTPException(status_code=409, detail="该实验尝试已经终结或取消")

    run = await run_service.create_run(
        session,
        course_id=course_id,
        attempt_id=attempt_id,
        language=payload.language,
        source_code=payload.source_code,
        student_id=user_id,
        execute=False,
        idempotency_key=idempotency_key,
    )

    task_view = task_service.create_task(session, TaskCreateRequest(
        task_type="experiment_run",
        owner_user_id=user_id,
        course_id=course_id,
        input_summary=f"课程 {course_id} 实验 attempt {attempt_id} 代码运行",
        input_payload={
            "course_id": course_id,
            "run_id": run.run_id,
            "attempt_id": attempt_id,
            "language": payload.language,
            "student_id": user_id,
        },
        resource_links=[
            {"resource_kind": "course", "resource_id": str(course_id), "relation": "input"},
            {"resource_kind": "experiment_attempt", "resource_id": attempt_id, "relation": "input"},
            {"resource_kind": "experiment_run", "resource_id": run.run_id, "relation": "output"},
        ],
        idempotency_key=f"experiment_run:{attempt_id}:{idempotency_key}",
    ))

    # 关联 task_id 到 run（便于后续查询）
    run.task_id = task_view.task_id
    session.add(run)
    session.commit()
    session.refresh(run)

    # 触发 worker 异步执行
    try:
        from app.platform.tasks.worker import local_task_worker
        from app.models.database import session_factory as _session_factory
        if local_task_worker.has_handler("experiment_run"):
            local_task_worker.submit(
                _session_factory,
                task_view.task_id,
                {
                    "course_id": course_id,
                    "run_id": run.run_id,
                    "attempt_id": attempt_id,
                    "student_id": user_id,
                },
            )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to submit experiment_run task %s to worker; task stays pending",
            task_view.task_id,
            exc_info=True,
        )

    return unified_response(
        code=202,
        message="代码运行任务已创建",
        data={
            "run_id": run.run_id,
            "task_id": task_view.task_id,
            "status": run.outcome.value if hasattr(run.outcome, "value") else str(run.outcome),
        },
    )


@experiment_router.get("/attempts/{attempt_id}/runs")
async def list_runs(
    attempt_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出尝试的运行记录。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    student_filter = None
    if context.role is not None and context.role.value == "student":
        student_filter = int(current_user["user_id"])
    runs = run_service.list_runs(
        session, course_id=course_id, attempt_id=attempt_id, student_id=student_filter,
    )
    return unified_response(
        code=200,
        message="获取运行列表成功",
        data={
            "course_id": course_id,
            "attempt_id": attempt_id,
            "items": [_serialize_run(r) for r in runs],
            "total": len(runs),
        },
    )


@experiment_router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Read one formal run without exposing source or hidden-test artifacts."""
    context = _require_experiment_platform(session, current_user, course_id, "experiment.view")
    run = run_service.get_run(
        session,
        course_id=course_id,
        run_id=run_id,
        student_id=int(current_user["user_id"]) if context.role is not None and context.role.value == "student" else None,
    )
    return unified_response(code=200, message="获取运行结果成功", data=_serialize_run(run))


# ---------------------------------------------------------------------------
# CodingAgent 分层提示
# ---------------------------------------------------------------------------


@experiment_router.post("/attempts/{attempt_id}/agent-hints")
async def request_hint(
    attempt_id: str,
    payload: HintRequest,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """CodingAgent 受控分层提示，不能执行任意前端代码。"""
    require_course_permission(session, current_user, course_id, "experiment.run")
    user_id = int(current_user["user_id"])
    hint = coding_hint_service.request_hint(
        session,
        course_id=course_id,
        attempt_id=attempt_id,
        student_id=user_id,
        hint_level=payload.hint_level,
        reason_codes=payload.reason_codes,
        hint_text=payload.hint_text,
        hint_metadata=payload.hint_metadata,
    )
    session.commit()
    session.refresh(hint)
    return unified_response(
        code=201,
        message="提示已请求",
        data=_serialize_hint(hint),
    )


@experiment_router.get("/attempts/{attempt_id}/agent-hints")
async def list_hints(
    attempt_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出尝试的提示记录（学生只能看自己的）。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    student_filter = None
    if context.role is not None and context.role.value == "student":
        student_filter = int(current_user["user_id"])
    hints = coding_hint_service.list_hints(
        session, course_id=course_id, attempt_id=attempt_id, student_id=student_filter,
    )
    return unified_response(
        code=200,
        message="获取提示列表成功",
        data={
            "course_id": course_id,
            "attempt_id": attempt_id,
            "items": [_serialize_hint(h) for h in hints],
            "total": len(hints),
        },
    )


@experiment_router.post("/agent-hints/{hint_id}/review")
async def review_hint(
    hint_id: str,
    payload: HintReviewRequest,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师审核 CodingAgent 提示。"""
    require_course_permission(session, current_user, course_id, "experiment.configure")
    user_id = int(current_user["user_id"])
    hint = coding_hint_service.review_hint(
        session,
        course_id=course_id,
        hint_id=hint_id,
        decision=payload.decision,
        reviewer_id=user_id,
        note=payload.note,
    )
    session.commit()
    session.refresh(hint)
    return unified_response(
        code=200,
        message="提示已审核",
        data=_serialize_hint(hint),
    )


# ---------------------------------------------------------------------------
# CodingEduAgent 诊断
# ---------------------------------------------------------------------------


@experiment_router.post("/runs/{run_id}/diagnosis")
async def create_run_diagnosis(
    run_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """根据服务器已保存的 ExperimentRun 生成受限 CodingDiagnosis。

    学生只能诊断自己的运行；教师可通过课程权限查看结果，但不能把
    客户端提交的文本伪装成诊断或正式评分。
    """
    context = require_course_permission(session, current_user, course_id, "experiment.run")
    user_id = int(current_user["user_id"])
    run = run_service.get_run(
        session, course_id=course_id, run_id=run_id,
        student_id=user_id if context.role is not None and context.role.value == "student" else None,
    )
    if str(getattr(run.outcome, "value", run.outcome)) in {"pending", "processing"}:
        return unified_response(
            code=409,
            message="运行尚未完成，暂不能生成诊断",
            data={"run_id": run_id, "status": "pending"},
        )
    diagnosis = coding_eduagent.diagnose_run(
        session, course_id=course_id, student_id=run.student_id, run_id=run_id,
    )
    session.commit()
    return unified_response(code=201, message="代码诊断已生成", data=serialize_diagnosis(diagnosis))


@experiment_router.get("/runs/{run_id}/diagnosis")
async def get_run_diagnosis(
    run_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """读取受限 CodingDiagnosis；不返回源码或完整沙箱日志。"""
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    user_id = int(current_user["user_id"])
    run = run_service.get_run(
        session, course_id=course_id, run_id=run_id,
        student_id=user_id if context.role is not None and context.role.value == "student" else None,
    )
    diagnosis = session.exec(
        select(CodingDiagnosisRecord).where(
            CodingDiagnosisRecord.run_id == run_id,
            CodingDiagnosisRecord.course_id == course_id,
            CodingDiagnosisRecord.student_id == run.student_id,
        )
    ).first()
    if diagnosis is None:
        return unified_response(code=200, message="尚未生成代码诊断", data={"run_id": run_id, "diagnosis": None})
    return unified_response(code=200, message="获取代码诊断成功", data=serialize_diagnosis(diagnosis))


@experiment_router.get("/runs/{run_id}/feedback")
async def get_run_feedback(
    run_id: str,
    course_id: int = Query(...),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return a CodingAgent-safe explanation with a deterministic fallback.

    The payload is assembled from the server-owned diagnosis record only.  It
    intentionally excludes source, stdin/stdout, hidden tests, artifacts and
    Judge0 configuration, so future LLM enrichment has the same boundary.
    """
    context = require_course_permission(session, current_user, course_id, "experiment.view")
    user_id = int(current_user["user_id"])
    run = run_service.get_run(
        session,
        course_id=course_id,
        run_id=run_id,
        student_id=user_id if context.role is not None and context.role.value == "student" else None,
    )
    diagnosis = session.exec(select(CodingDiagnosisRecord).where(
        CodingDiagnosisRecord.run_id == run_id,
        CodingDiagnosisRecord.course_id == course_id,
        CodingDiagnosisRecord.student_id == run.student_id,
    )).first()
    if diagnosis is None and run.outcome != RunOutcome.PENDING:
        diagnosis = coding_eduagent.diagnose_run(
            session, course_id=course_id, student_id=run.student_id, run_id=run_id,
        )
        session.commit()
    if diagnosis is None:
        return unified_response(
            code=200,
            message="运行尚未终结",
            data={"run_id": run_id, "status": "pending", "feedback": None},
        )
    return unified_response(
        code=200,
        message="获取本次运行讲解成功",
        data={
            "run_id": run_id,
            "feedback_source": "coding-rules",
            "summary": diagnosis.summary,
            "next_steps": list(diagnosis.debug_steps or []),
            "reason_codes": list(diagnosis.reason_codes or []),
            "line": diagnosis.line,
            "result": {
                "outcome": diagnosis.outcome,
                "passed_count": run.passed_count,
                "total_count": run.total_count,
                "cpu_time_ms": run.cpu_time_ms,
                "wall_time_ms": run.wall_time_ms,
                "memory_kb": run.memory_kb,
            },
        },
    )
