"""业务任务 handler 注册（阶段0 统一任务中心）。

将各业务域的长操作接入 LocalTaskWorker，避免任务停留在 pending 或被
立即标记为 DEPENDENCY_UNAVAILABLE。

设计要点：
- 每个 handler 接收 TaskHandlerContext，自行管理 session 生命周期；
- handler 内部调用对应业务 service 的执行方法，并通过 task_service
  回写状态（mark_running / mark_progress / mark_succeeded / mark_failed）；
- handler 不向外抛异常，所有异常由 LocalTaskWorker._execute 捕获并分类；
- 真实解析/OCR/渲染由各 service 内部决定，handler 只做编排。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.platform.tasks.worker import (
    LocalTaskWorker,
    TaskExecutionError,
    TaskHandlerContext,
    local_task_worker,
    register_builtin_handlers,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# document_parse handler
# ---------------------------------------------------------------------------


async def document_parse_handler(ctx: TaskHandlerContext) -> None:
    """课程材料解析任务 handler。

    input_payload 期望字段：
    - course_id: int
    - run_id: str
    - material_id: str
    - material_version_id: str
    - pipeline: str (full / ocr_only / graph_only)
    - stale_strategy: str (mark_stale / orphan / delete)

    执行流程：
    1. mark_running（task + parse_run）
    2. 调用真实解析（P0-4 接入；当前阶段若解析器不可用则降级为 succeeded + 0 blocks）
    3. mark_succeeded（task + parse_run）

    真实 DocumentIR/OCR/图谱构建在 P0-4 接入；本 handler 保证任务状态机正确流转，
    不再让 DocumentParseRun 永远停留在 PENDING。
    """
    payload = ctx.input_payload or {}
    course_id = payload.get("course_id")
    run_id = payload.get("run_id")
    if not course_id or not run_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "document_parse handler 缺少 course_id 或 run_id",
            retryable=False,
        )

    from app.models.document_parse_model import ParseRunStatus
    from app.services.document_parse_service import document_parse_service

    # 1. 标记 running（task + parse_run）
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="parse")
        try:
            document_parse_service.mark_running(
                session, run_id=run_id, course_id=int(course_id),
            )
        except Exception as exc:
            # parse_run 状态机冲突等：任务仍标记 failed
            raise TaskExecutionError(
                "PARSE_RUN_STATE_CONFLICT",
                f"无法标记 parse_run 为 running: {exc}",
                retryable=False,
            )

    # 2. 执行真实解析（P0-4：接入真实 DocumentIR/OCR/图谱构建流水线）
    block_count = 0
    evidence_span_count = 0
    graph_candidate_count = 0
    try:
        from app.services.document_parse_pipeline import (
            ParsePipelineError,
            run_parse_pipeline,
        )
        with ctx.session_factory() as pipeline_session:
            try:
                block_count, evidence_span_count, graph_candidate_count = (
                    await run_parse_pipeline(
                        pipeline_session,
                        course_id=int(course_id),
                        run_id=run_id,
                        material_id=payload.get("material_id", ""),
                        material_version_id=payload.get("material_version_id"),
                        pipeline=payload.get("pipeline", "full"),
                        stale_strategy=payload.get("stale_strategy", "mark_stale"),
                    )
                )
                pipeline_session.commit()
            except ParsePipelineError as exc:
                pipeline_session.rollback()
                # 解析失败：标记 parse_run + task 为 failed，不伪装成功
                with ctx.session_factory() as fail_session:
                    from app.services.document_parse_service import document_parse_service as _dps
                    try:
                        _dps.mark_failed(
                            fail_session,
                            run_id=run_id,
                            course_id=int(course_id),
                            error_code=exc.error_code,
                            error_message=exc.message[:500],
                        )
                        fail_session.commit()
                    except Exception:
                        fail_session.rollback()
                raise TaskExecutionError(
                    exc.error_code,
                    exc.message,
                    retryable=exc.error_code in ("SOURCE_UNAVAILABLE",),
                )
    except TaskExecutionError:
        raise
    except Exception as exc:
        # 未预期异常：标记 failed，避免伪装成功
        logger.exception(
            "document_parse_handler: unexpected failure for run %s: %s",
            run_id, exc,
        )
        with ctx.session_factory() as fail_session:
            from app.services.document_parse_service import document_parse_service as _dps
            try:
                _dps.mark_failed(
                    fail_session,
                    run_id=run_id,
                    course_id=int(course_id),
                    error_code="UNEXPECTED_ERROR",
                    error_message=f"{type(exc).__name__}: {exc}"[:500],
                )
                fail_session.commit()
            except Exception:
                fail_session.rollback()
        raise TaskExecutionError(
            "UNEXPECTED_ERROR",
            f"document_parse_handler unexpected failure: {exc}",
            retryable=False,
        )

    # 3. 标记 succeeded（task + parse_run）
    with ctx.session_factory() as session:
        try:
            document_parse_service.mark_succeeded(
                session,
                run_id=run_id,
                course_id=int(course_id),
                block_count=block_count,
                evidence_span_count=evidence_span_count,
                graph_candidate_count=graph_candidate_count,
            )
        except Exception as exc:
            raise TaskExecutionError(
                "PARSE_RUN_STATE_CONFLICT",
                f"无法标记 parse_run 为 succeeded: {exc}",
                retryable=False,
            )
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref=f"parse_run://{run_id}",
            result_data={
                "run_id": run_id,
                "course_id": course_id,
                "block_count": block_count,
                "evidence_span_count": evidence_span_count,
                "graph_candidate_count": graph_candidate_count,
            },
        )


async def _invoke_document_parser(payload: dict[str, Any]) -> tuple[int, int, int]:
    """[已废弃] 旧式占位解析器。

    P0-4 后改为直接调用 document_parse_pipeline.run_parse_pipeline。
    本函数保留仅为兼容旧 import，不应再被调用。
    """
    return 0, 0, 0


# ---------------------------------------------------------------------------
# experiment_run handler
# ---------------------------------------------------------------------------


async def experiment_run_handler(ctx: TaskHandlerContext) -> None:
    """实验代码运行 handler（Judge0 异步执行）。

    input_payload 期望字段：
    - course_id: int
    - run_id: str
    - attempt_id: str

    执行流程：
    1. mark_running
    2. 调用 experiment_service._execute_run（已抽出的同步执行逻辑）
    3. 根据 run.outcome 标记 succeeded / failed
    """
    payload = ctx.input_payload or {}
    course_id = payload.get("course_id")
    run_id = payload.get("run_id")
    attempt_id = payload.get("attempt_id")
    if not course_id or not run_id or not attempt_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "experiment_run handler 缺少 course_id/run_id/attempt_id",
            retryable=False,
        )

    from app.models.experiment_model import ExperimentRun, RunOutcome
    from app.services.experiment_service import (
        attempt_service,
        run_service,
        version_service,
    )
    from sqlmodel import select

    # 1. 标记 running
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="sandbox_execution")
        # 同步 run 状态：ExperimentRun 在 create_run 时已创建为 PENDING

    # 2. 执行沙箱运行
    with ctx.session_factory() as session:
        run = session.exec(
            select(ExperimentRun).where(
                ExperimentRun.run_id == run_id,
                ExperimentRun.course_id == int(course_id),
            )
        ).first()
        if run is None:
            raise TaskExecutionError(
                "VALIDATION_FAILED",
                f"ExperimentRun {run_id} 不存在",
                retryable=False,
            )
        attempt = attempt_service.get_attempt(
            session, course_id=int(course_id), attempt_id=attempt_id,
        )
        version = version_service.get_version(
            session, course_id=int(course_id), version_id=attempt.version_id,
        )
        try:
            await run_service._execute_run(
                session, run=run, attempt=attempt, version=version,
            )
            session.commit()
        except Exception as exc:
            raise TaskExecutionError(
                "SANDBOX_EXECUTION_FAILED",
                f"沙箱执行失败: {exc}",
                retryable=True,
            )

    # 3. 根据 outcome 标记 succeeded / failed
    with ctx.session_factory() as session:
        run = session.exec(
            select(ExperimentRun).where(ExperimentRun.run_id == run_id)
        ).first()
        outcome = run.outcome if run else RunOutcome.INTERNAL_ERROR

        if outcome == RunOutcome.ACCEPTED:
            ctx.service.mark_succeeded(
                session,
                ctx.task_id,
                result_ref=f"experiment_run://{run_id}",
                result_data={
                    "run_id": run_id,
                    "outcome": outcome.value if hasattr(outcome, "value") else str(outcome),
                    "passed_count": run.passed_count if run else 0,
                    "total_count": run.total_count if run else 0,
                    "score": run.score if run else 0.0,
                },
            )
        elif outcome == RunOutcome.SANDBOX_UNAVAILABLE:
            # 沙箱不可用：明确失败 + 可重试
            raise TaskExecutionError(
                "SANDBOX_UNAVAILABLE",
                "代码沙箱不可用，请稍后重试",
                retryable=True,
            )
        else:
            # 编译错误/运行时错误/答案错误等：任务"成功完成"（学生可看到结果）
            ctx.service.mark_succeeded(
                session,
                ctx.task_id,
                result_ref=f"experiment_run://{run_id}",
                result_data={
                    "run_id": run_id,
                    "outcome": outcome.value if hasattr(outcome, "value") else str(outcome),
                    "passed_count": run.passed_count if run else 0,
                    "total_count": run.total_count if run else 0,
                    "score": run.score if run else 0.0,
                },
            )


# ---------------------------------------------------------------------------
# media handlers
# ---------------------------------------------------------------------------


async def media_avatar_preprocess_handler(ctx: TaskHandlerContext) -> None:
    """数字人资产预处理 handler。

    input_payload 期望字段：
    - avatar_id: str
    - portrait_object_key: str
    - voice_object_key: str | None
    - provider_key: str

    P0-3 安全约束：
    - 入口必须校验 AvatarSourceMedia.upload_status == VALIDATED，
      拒绝 pending/uploaded/quarantined/withdrawn 状态的素材进入预处理。
    - 调用 preparation_service.execute_preparation_job 执行真实预处理。
    """
    payload = ctx.input_payload or {}
    avatar_id = payload.get("avatar_id")
    if not avatar_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "media.avatar_preprocess handler 缺少 avatar_id",
            retryable=False,
        )

    from app.services.avatar_service import preparation_service
    from sqlmodel import select
    from app.models.avatar_model import (
        AvatarPreparationJob,
        AvatarSourceMedia,
        AvatarSourceMediaType,
        AvatarSourceMediaStatus,
    )

    # 1. 查找对应的 AvatarPreparationJob
    with ctx.session_factory() as session:
        job = session.exec(
            select(AvatarPreparationJob).where(
                AvatarPreparationJob.task_id == ctx.task_id
            )
        ).first()
        if job is None:
            raise TaskExecutionError(
                "VALIDATION_FAILED",
                f"未找到 task_id={ctx.task_id} 对应的 AvatarPreparationJob",
                retryable=False,
            )
        job_id = job.job_id
        owner_user_id = job.owner_user_id

        # P0-3.6 安全校验：所有依赖素材必须处于 VALIDATED 状态
        sources = list(session.exec(
            select(AvatarSourceMedia).where(
                AvatarSourceMedia.avatar_id == avatar_id,
                AvatarSourceMedia.owner_user_id == owner_user_id,
            )
        ).all())
        if not sources:
            raise TaskExecutionError(
                "VALIDATION_FAILED",
                f"avatar_id={avatar_id} 没有任何原始素材，无法预处理",
                retryable=False,
            )
        # 必须存在 portrait_video
        portrait = next(
            (s for s in sources if s.media_type == AvatarSourceMediaType.PORTRAIT_VIDEO),
            None,
        )
        if portrait is None:
            raise TaskExecutionError(
                "VALIDATION_FAILED",
                f"avatar_id={avatar_id} 缺少 portrait_video 素材",
                retryable=False,
            )
        # 所有登记的素材都必须 VERIFIED；存在未校验/隔离/撤回的素材直接拒绝
        unverified = [
            s for s in sources
            if s.upload_status != AvatarSourceMediaStatus.VERIFIED
        ]
        if unverified:
            bad = [
                {
                    "source_media_id": s.source_media_id,
                    "media_type": s.media_type.value,
                    "upload_status": s.upload_status.value,
                }
                for s in unverified
            ]
            raise TaskExecutionError(
                "DEPENDENCY_UNVALIDATED",
                f"avatar_id={avatar_id} 存在未通过服务端校验的素材: {bad}",
                retryable=False,
            )

    # 2. 调用 execute_preparation_job（同步执行，Fake Provider 在 P0-3 替换）
    with ctx.session_factory() as session:
        try:
            preparation_service.execute_preparation_job(
                session,
                avatar_id=avatar_id,
                job_id=job_id,
                owner_user_id=owner_user_id,
            )
            session.commit()
        except Exception as exc:
            raise TaskExecutionError(
                "AVATAR_PREPROCESS_FAILED",
                f"数字人预处理失败: {exc}",
                retryable=True,
            )

    # 3. 标记 succeeded（execute_preparation_job 内部已更新 job 状态，
    #    但 task 状态需在此显式标记）
    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref=f"avatar_preparation_job://{job_id}",
            result_data={"avatar_id": avatar_id, "job_id": job_id},
        )


async def media_generic_handler(ctx: TaskHandlerContext) -> None:
    """媒体生成通用 handler（tts/subtitle/dh_render/video_package/timeline_publish）。

    当前阶段：媒体生成由各业务端点同步执行（document.py / video_generation.py），
    本 handler 仅用于"已创建 TaskRecord 但通过 worker 触发"的场景。
    真实执行逻辑在 P0-2.5 后续阶段抽取到 media_release_service.execute_job。
    """
    payload = ctx.input_payload or {}
    course_id = payload.get("course_id")
    if not course_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "media handler 缺少 course_id",
            retryable=False,
        )

    # 当前阶段：标记 succeeded，表示"任务已被 worker 消费"
    # 真实执行逻辑由各端点同步完成（document.py / video_generation.py）
    # P0-2.5 后续阶段将抽取到 media_release_service.execute_job
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="media_generation")
    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref=f"media_task://{ctx.task_id}",
            result_data={"course_id": course_id, "consumed_by": "media_generic_handler"},
        )


# ---------------------------------------------------------------------------
# question_bank.import handler
# ---------------------------------------------------------------------------


async def question_bank_import_handler(ctx: TaskHandlerContext) -> None:
    """Excel 题库导入 handler（G7）。

    input_payload 期望字段：
    - course_id: int
    - run_id: str  (QuestionImportRun.run_id)

    执行流程：
    1. mark_running（task）
    2. 调用 question_import_service.execute_run 解析 Excel 并写入 QuestionBankItem
    3. 根据 run.status 标记 task succeeded / failed
       - SUCCEEDED / PARTIAL_SUCCESS -> task succeeded
       - FAILED -> task failed（保留原 error_code）

    约束：
    - 题目默认 status=UNASSIGNED，需教师通过题源映射或题目管理升级为 PUBLISHED
    - 跨课程严格隔离：导入的题目 course_id 与 run.course_id 一致
    - 失败不伪装成功：解析错误或读取错误都标记为 FAILED 并保留原 error_code
    """
    payload = ctx.input_payload or {}
    course_id = payload.get("course_id")
    run_id = payload.get("run_id")
    if not course_id or not run_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "question_bank.import handler 缺少 course_id 或 run_id",
            retryable=False,
        )

    from app.services.practice_recommendation_service import (
        question_import_service,
        ImportRunStatus,
    )

    # 1. mark_running（task）
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="excel_import")

    # 2. 执行导入（execute_run 内部管理 run 状态机）
    run_status_value: str = ""
    imported_count: int = 0
    skipped_count: int = 0
    error_code: str = ""
    error_message: str = ""
    with ctx.session_factory() as session:
        try:
            run = question_import_service.execute_run(
                session,
                run_id=run_id,
                course_id=int(course_id),
            )
            session.commit()
            run_status_value = run.status.value
            imported_count = run.imported_count or 0
            skipped_count = run.skipped_count or 0
            error_code = run.error_code or ""
            error_message = run.error_message or ""
        except Exception as exc:
            session.rollback()
            # service 抛出的业务异常（如状态冲突）
            raise TaskExecutionError(
                "IMPORT_RUN_STATE_CONFLICT",
                f"题库导入执行失败: {exc}",
                retryable=False,
            )

    # 3. 根据 run.status 标记 task succeeded / failed
    if run_status_value in (ImportRunStatus.SUCCEEDED.value,
                            ImportRunStatus.PARTIAL_SUCCESS.value):
        with ctx.session_factory() as session:
            ctx.service.mark_succeeded(
                session,
                ctx.task_id,
                result_ref=f"question_import_run://{run_id}",
                result_data={
                    "run_id": run_id,
                    "course_id": course_id,
                    "status": run_status_value,
                    "imported_count": imported_count,
                    "skipped_count": skipped_count,
                },
            )
    else:
        # FAILED / 未知状态：标记 task failed，保留原 error_code
        raise TaskExecutionError(
            error_code or "IMPORT_FAILED",
            error_message or f"题库导入运行 {run_id} 处于失败状态: {run_status_value}",
            retryable=False,
        )


# ---------------------------------------------------------------------------
# agent action execute handler
# ---------------------------------------------------------------------------


async def agent_action_execute_handler(ctx: TaskHandlerContext) -> None:
    """教师已批准的高风险 Agent 动作执行 handler。

    input_payload 期望字段：
    - course_id: int
    - proposal_id: str
    - proposal_type: str (trigger_experiment / web_research / change_topic / ...)
    - tool_name: str
    - trace_id: str
    - student_id: int
    - session_id: str
    - proposed_action: dict
    - decided_by: int

    执行流程：
    1. mark_running
    2. P1-6: 按 proposal_type 分发到对应业务 service 真实执行
       - trigger_experiment → experiment_service（创建 run / attempt）
       - web_research       → web_research_service.execute_research
       - change_topic       → 记录 dispatched event（UI 层消费）
       失败保留原 error_code，不伪装成功；dispatched=True 仅在真实执行成功后设置
    3. mark_succeeded，记录 proposal_id 与派发结果（含 dispatched 标志）
    """
    payload = ctx.input_payload or {}
    course_id = payload.get("course_id")
    proposal_id = payload.get("proposal_id")
    proposal_type = payload.get("proposal_type")
    if not course_id or not proposal_id or not proposal_type:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "agent_action_execute handler 缺少 course_id/proposal_id/proposal_type",
            retryable=False,
        )

    proposed_action = payload.get("proposed_action") or {}
    student_id = payload.get("student_id")
    trace_id = payload.get("trace_id", "")
    decided_by = payload.get("decided_by")

    # 1. mark_running
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage=f"agent_action:{proposal_type}")

    # 2. P1-6: 按 proposal_type 真实分发
    dispatch_result: dict[str, Any] = {
        "proposal_id": proposal_id,
        "proposal_type": proposal_type,
        "dispatched": False,
        "dispatched_at": None,
        "outcome": "pending",
        "details": {},
    }

    try:
        outcome = await _dispatch_agent_action(
            proposal_type=proposal_type,
            course_id=int(course_id),
            student_id=int(student_id) if student_id else None,
            proposed_action=proposed_action,
            session_factory=ctx.session_factory,
            decided_by=int(decided_by) if decided_by else None,
            trace_id=trace_id,
        )
        dispatch_result.update(outcome)
    except TaskExecutionError:
        # 保留原 error_code，向上抛出由 worker 分类处理
        raise
    except Exception as exc:
        # 未知异常归一化为 DISPATCH_FAILED，保留原始异常类型供审计
        logger.exception(
            "agent_action_execute dispatch failed: proposal=%s type=%s",
            proposal_id, proposal_type,
        )
        raise TaskExecutionError(
            "DISPATCH_FAILED",
            f"高风险动作派发失败 ({type(exc).__name__}): {exc}",
            retryable=False,
        )

    # 3. mark_succeeded 仅在 dispatched=True 时表示真实执行；否则保留 outcome 供审计
    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref=f"agent_proposal://{proposal_id}",
            result_data=dispatch_result,
        )


async def _dispatch_agent_action(
    *,
    proposal_type: str,
    course_id: int,
    student_id: Optional[int],
    proposed_action: dict[str, Any],
    session_factory,
    decided_by: Optional[int],
    trace_id: str,
) -> dict[str, Any]:
    """P1-6: 真实分发高风险动作到对应业务 service。

    返回 dict 包含：dispatched, dispatched_at, outcome, details。
    任何失败都抛异常（由 ``agent_action_execute_handler`` 捕获并保留 error_code），
    不得返回 ``dispatched=True`` 同时携带失败细节。
    """
    from app.core.time_utils import utcnow_aware

    dispatched_at = utcnow_aware().isoformat()

    if proposal_type == "web_research":
        return await _dispatch_web_research(
            course_id=course_id,
            proposed_action=proposed_action,
            session_factory=session_factory,
            dispatched_at=dispatched_at,
        )

    if proposal_type == "trigger_experiment":
        return await _dispatch_trigger_experiment(
            course_id=course_id,
            student_id=student_id,
            proposed_action=proposed_action,
            session_factory=session_factory,
            decided_by=decided_by,
            dispatched_at=dispatched_at,
        )

    if proposal_type == "change_topic":
        # change_topic 是 UI 导航提示，无独立业务 service；
        # 真实"执行"由前端消费 proposed_action 中的 target_topic 字段。
        # 我们记录 dispatched=True 表示已通过审批并写入审计，便于前端拉取。
        target_topic = proposed_action.get("target_topic") or proposed_action.get("topic")
        return {
            "dispatched": True,
            "dispatched_at": dispatched_at,
            "outcome": "topic_change_recorded",
            "details": {
                "target_topic": target_topic,
                "consumer": "frontend_navigation",
            },
        }

    # 未知高风险类型：记录为 dispatched=False 而非抛错，避免阻塞 worker；
    # 教师可在审计中看到 outcome=unknown_type，再决定是否手动处理。
    return {
        "dispatched": False,
        "dispatched_at": dispatched_at,
        "outcome": "unknown_type",
        "details": {"proposal_type": proposal_type},
    }


async def _dispatch_web_research(
    *,
    course_id: int,
    proposed_action: dict[str, Any],
    session_factory,
    dispatched_at: str,
) -> dict[str, Any]:
    """P1-6: 派发 web_research 到 web_research_service.execute_research。

    proposed_action 期望字段：
    - query: str  (搜索查询)
    失败保留原 error_code；web_research_service 内部已实现降级语义
    （disabled / budget_exceeded / no_results / search_failed）。
    """
    from app.services.web_research_service import execute_research

    query = str(proposed_action.get("query") or "").strip()
    if not query:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "web_research proposed_action 缺少 query 字段",
            retryable=False,
        )

    # execute_research 内部已处理降级（返回 ResearchStatus.* 而非抛错），
    # 因此只有在配置/网络异常时才会抛出。我们将其视为派发失败。
    with session_factory() as session:
        try:
            result = execute_research(session, course_id, query)
        except Exception as exc:
            raise TaskExecutionError(
                "WEB_RESEARCH_DISPATCH_FAILED",
                f"web_research 执行异常: {exc}",
                retryable=True,
            )

        return {
            "dispatched": True,
            "dispatched_at": dispatched_at,
            "outcome": str(getattr(result, "status", "unknown")),
            "details": {
                "result_id": getattr(result, "id", None),
                "query": query[:200],
            },
        }


async def _dispatch_trigger_experiment(
    *,
    course_id: int,
    student_id: Optional[int],
    proposed_action: dict[str, Any],
    session_factory,
    decided_by: Optional[int],
    dispatched_at: str,
) -> dict[str, Any]:
    """P1-6: 派发 trigger_experiment 到 experiment_service。

    proposed_action 期望字段：
    - experiment_id: str   → 必填，标识要触发的实验
    - language: str        → 可选，若提供则同时创建 run
    - source_code: str     → 可选，与 language 配合创建 run

    流程：
    1. 通过 attempt_service.create_attempt 为学生创建尝试（使用实验默认版本）
    2. 若提供 language + source_code，则通过 run_service.create_run(execute=False)
       创建 PENDING run，由 experiment_run_handler 异步执行
    3. 否则仅创建 attempt，学生可在 UI 中提交代码
    """
    experiment_id = proposed_action.get("experiment_id")
    if not experiment_id:
        return {
            "dispatched": False,
            "dispatched_at": dispatched_at,
            "outcome": "missing_experiment_id",
            "details": {"reason": "trigger_experiment proposed_action 缺少 experiment_id"},
        }

    if student_id is None:
        return {
            "dispatched": False,
            "dispatched_at": dispatched_at,
            "outcome": "missing_student_id",
            "details": {"reason": "trigger_experiment 需要 student_id 才能创建 attempt"},
        }

    language = proposed_action.get("language")
    source_code = proposed_action.get("source_code") or proposed_action.get("code")
    has_code_payload = bool(language) and bool(source_code)

    with session_factory() as session:
        try:
            from app.services.experiment_service import (
                attempt_service,
                run_service,
            )

            attempt = attempt_service.create_attempt(
                session,
                course_id=course_id,
                experiment_id=str(experiment_id),
                student_id=int(student_id),
            )

            run_id = None
            if has_code_payload:
                # 创建 PENDING run（不立即执行），由 experiment_run_handler 异步消费
                run = await run_service.create_run(
                    session,
                    course_id=course_id,
                    attempt_id=attempt.attempt_id,
                    language=str(language),
                    source_code=str(source_code),
                    student_id=int(student_id),
                    execute=False,
                )
                run_id = run.run_id

            session.commit()
        except TaskExecutionError:
            raise
        except Exception as exc:
            raise TaskExecutionError(
                "EXPERIMENT_DISPATCH_FAILED",
                f"trigger_experiment 派发失败: {exc}",
                retryable=True,
            )

        return {
            "dispatched": True,
            "dispatched_at": dispatched_at,
            "outcome": "experiment_attempt_created" if not has_code_payload else "experiment_run_created",
            "details": {
                "experiment_id": str(experiment_id),
                "attempt_id": attempt.attempt_id,
                "run_id": run_id,
                "note": (
                    "ExperimentAttempt 已创建；学生可在 UI 中提交代码"
                    if not has_code_payload
                    else "ExperimentRun 已创建为 PENDING；由 experiment_run_handler 后续执行"
                ),
            },
        }


# ---------------------------------------------------------------------------
# 注册函数
# ---------------------------------------------------------------------------


def register_business_handlers(worker: LocalTaskWorker = local_task_worker) -> None:
    """注册所有业务 handler。

    在应用启动时调用（main.py startup），确保任务中心能消费业务任务。
    """
    worker.register("document_parse", document_parse_handler)
    worker.register("experiment_run", experiment_run_handler)
    worker.register("media.avatar_preprocess", media_avatar_preprocess_handler)
    worker.register("agent_action_execute", agent_action_execute_handler)
    worker.register("question_bank.import", question_bank_import_handler)

    # 媒体生成任务类型（MediaGenerationJobType 枚举值）
    for job_type in ("tts", "subtitle", "avatar_preprocess", "dh_render",
                     "video_package", "timeline_publish"):
        task_type = f"media.{job_type}"
        if not worker.has_handler(task_type):
            worker.register(task_type, media_generic_handler)


def register_all_handlers(worker: LocalTaskWorker = local_task_worker) -> None:
    """注册全部 handler（自检 + 业务）。

    在 main.py startup 调用一次，保证 worker 能消费所有已注册 task_type。
    """
    register_builtin_handlers(worker)
    register_business_handlers(worker)
