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

import asyncio
import logging
import threading
from datetime import timezone
from typing import Any, Optional

from app.platform.tasks.worker import (
    LocalTaskWorker,
    TaskExecutionError,
    TaskHandlerContext,
    local_task_worker,
    register_builtin_handlers,
)

logger = logging.getLogger(__name__)


_tts_provider_semaphores: dict[str, threading.BoundedSemaphore] = {}
_tts_provider_semaphores_lock = threading.Lock()


def _tts_provider_semaphore(provider_key: str, limit: int) -> threading.BoundedSemaphore:
    """Return a process-local semaphore for live provider sessions.

    The worker runs synchronous provider SDK calls in threads.  A thread-safe
    semaphore therefore enforces the configured per-provider ceiling without
    changing the API request's event loop semantics.
    """
    key = provider_key or "default"
    with _tts_provider_semaphores_lock:
        current = _tts_provider_semaphores.get(key)
        if current is None:
            current = threading.BoundedSemaphore(limit)
            _tts_provider_semaphores[key] = current
        return current


def _course_build_failure_message(error: BaseException) -> str:
    """Return a safe, actionable message for a failed intelligent-prep task."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if getattr(current, "reason_code", "") == "PREP_EVIDENCE_BUDGET_EXCEEDED":
            return (
                "材料证据整理已达到系统设定的分段与重试预算，系统未写入课程草稿；"
                "请减少材料数量或拆分课程后重试。"
            )
        if getattr(current, "reason_code", "") == "input_length_exceeded":
            return "输入内容超过模型上下文上限，系统未写入课程草稿；请减少上传材料页数或拆分课程后重新智能备课"
        if getattr(current, "reason_code", "") == "MODEL_OUTPUT_TRUNCATED":
            return "模型输出达到长度上限，系统已自动分段生成；若仍失败请减少材料数量或拆分课程后重新智能备课"
        if getattr(current, "reason_code", "") == "response_format_unsupported":
            return "模型网关不支持结构化输出，系统已尝试兼容模式但仍未完成；请检查模型网关兼容性后重新智能备课"
        if getattr(current, "status_code", None) == 400:
            return "模型服务拒绝了智能备课请求（HTTP 400）；请检查模型名称、网关兼容性和请求限制后重新智能备课"
        current = current.__cause__ or current.__context__
    current = error
    visited.clear()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if getattr(current, "reason_code", "") == "structured_output_invalid":
            stage = getattr(current, "stage", "") or ""
            stage_label = {
                "segment_evidence_reduce": "材料证据整理",
                "segment_evidence": "材料证据整理",
                "plan_outline": "课程结构规划",
                "write_script": "讲授脚本生成",
                "write_scripts_batch": "批量讲授脚本生成",
                "verify_script": "讲授脚本核验",
            }.get(stage, stage or "未知阶段")
            return f"模型返回内容不符合格式，系统已重试 1 次；失败阶段：{stage_label}。原课程草稿未覆盖，请重新智能备课。"
        current = current.__cause__ or current.__context__
    if "PREP_STRUCTURED_PORT_UNAVAILABLE" in str(error):
        return "智能备课结构化服务未就绪；请检查后端 LLM 配置后重新智能备课"
    return str(error)[:500]


def _initial_runtime_failure(result: Any) -> BaseException | None:
    """Turn an Initial runtime's fail-closed error state into a task error."""
    errors = result.get("errors") if isinstance(result, dict) else None
    if not errors:
        if isinstance(result, dict) and result.get("status") in {"timeout", "runtime_error"}:
            return TaskExecutionError(
                "COURSE_BUILD_RUNTIME_FAILED",
                "备课智能体运行失败，请稍后重试。",
                retryable=True,
            )
        return None
    detail = errors[-1]
    if isinstance(detail, dict):
        error_type = str(detail.get("error_type") or "")
        if error_type == "CourseBuildCancelled":
            from app.services.controlled_prep_workflow import CourseBuildCancelled
            return CourseBuildCancelled(str(detail.get("message") or "课程材料已变化，旧备课任务已取消"))
        if error_type == "CourseBuildStageTimeout":
            from app.services.controlled_prep_workflow import CourseBuildStageTimeout
            return CourseBuildStageTimeout(str(detail.get("message") or "备课阶段超时"))
        code = str(detail.get("code") or "COURSE_DRAFT_BUILD_FAILED")
        stage = str(detail.get("stage") or "")
        reason_code = str(detail.get("reason_code") or "")
        if reason_code == "structured_output_invalid":
            stage_label = {
                "segment_evidence_reduce": "材料证据整理",
                "segment_evidence": "材料证据整理",
                "plan_outline": "课程结构规划",
                "write_script": "讲授脚本生成",
                "write_scripts_batch": "批量讲授脚本生成",
                "verify_script": "讲授脚本核验",
            }.get(stage, stage or "未知阶段")
            message = f"模型返回内容不符合格式，系统已重试 1 次；失败阶段：{stage_label}。原课程草稿未覆盖，请重新智能备课。"
        else:
            message = str(detail.get("message") or "备课智能体未能完成本次整理")[:500]
        return TaskExecutionError(code, message, retryable=True)
    return TaskExecutionError(
        "COURSE_DRAFT_BUILD_FAILED",
        str(detail)[:500],
        retryable=True,
    )


def _course_build_checkpoint_payload(value: Any) -> dict[str, Any]:
    """Persist stage progress metadata without course/model content."""
    if value is None:
        return {}
    payload: dict[str, Any] = {"result_type": type(value).__name__}
    if isinstance(value, list):
        payload["item_count"] = len(value)
        return payload
    for field in ("segments", "candidates", "prerequisites", "scripts", "findings"):
        items = getattr(value, field, None)
        if isinstance(items, list):
            payload[f"{field}_count"] = len(items)
    verdict = getattr(value, "verdict", None)
    if verdict:
        payload["verdict"] = str(verdict)
    return payload


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

    def mark_material_failed(error_code: str, error_message: str) -> None:
        """Keep the material list truthful when its durable parse run fails."""
        from sqlmodel import select
        from app.models.course_build_model import MaterialStatus, SourceMaterial, SourceMaterialVersion

        with ctx.session_factory() as failure_session:
            version = failure_session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.version_id == payload.get("material_version_id"),
                SourceMaterialVersion.course_id == int(course_id),
            )).first()
            if version is not None:
                version.parse_status = MaterialStatus.FAILED
                version.parse_error = f"{error_code}: {error_message}"[:500]
                failure_session.add(version)
            material = failure_session.exec(select(SourceMaterial).where(
                SourceMaterial.material_id == payload.get("material_id"),
                SourceMaterial.course_id == int(course_id),
            )).first()
            if material is not None:
                material.status = MaterialStatus.FAILED
                failure_session.add(material)
            failure_session.commit()

    # 1. 标记 running（task + parse_run）
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="parse")
        try:
            document_parse_service.mark_running(
                session, run_id=run_id, course_id=int(course_id),
            )
            # A material remains `uploaded` while its durable task is queued.
            # Move the list projection to `parsing` only once this worker owns
            # the run, so the construction workspace reflects real progress.
            from sqlmodel import select
            from app.models.course_build_model import MaterialStatus, SourceMaterial, SourceMaterialVersion

            version = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.version_id == payload.get("material_version_id"),
                SourceMaterialVersion.course_id == int(course_id),
            )).first()
            if version is not None:
                version.parse_status = MaterialStatus.PARSING
                session.add(version)
            material = session.exec(select(SourceMaterial).where(
                SourceMaterial.material_id == payload.get("material_id"),
                SourceMaterial.course_id == int(course_id),
            )).first()
            if material is not None:
                material.status = MaterialStatus.PARSING
                session.add(material)
            session.commit()
        except Exception as exc:
            session.rollback()
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
    # Material parse intentionally stops at material-level facts. Course-wide
    # drafts are scheduled only after the complete material set is ready.
    _draft_progress: dict = {}
    _draft_warnings: list = []
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
                        pipeline=str(payload.get("pipeline") or "full"),
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
                mark_material_failed(exc.error_code, exc.message)
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
        mark_material_failed("UNEXPECTED_ERROR", f"{type(exc).__name__}: {exc}")
        raise TaskExecutionError(
            "UNEXPECTED_ERROR",
            f"document_parse_handler unexpected failure: {exc}",
            retryable=False,
        )

    # 3. 标记 succeeded（task + parse_run）
    with ctx.session_factory() as session:
        try:
            parse_run = document_parse_service.mark_succeeded(
                session,
                run_id=run_id,
                course_id=int(course_id),
                block_count=block_count,
                evidence_span_count=evidence_span_count,
                graph_candidate_count=graph_candidate_count,
            )
            document_parse_service.activate_initial_retrieval_snapshot(
                session,
                course_id=int(course_id),
                run_id=run_id,
            )
        except Exception as exc:
            raise TaskExecutionError(
                "PARSE_RUN_STATE_CONFLICT",
                f"无法标记 parse_run 为 succeeded: {exc}",
                retryable=False,
            )
        result_data = {
            "run_id": run_id,
            "course_id": course_id,
            "parse_run_status": parse_run.status.value,
            "block_count": block_count,
            "evidence_span_count": evidence_span_count,
            "graph_candidate_count": graph_candidate_count,
            "draft_assets": _draft_progress,
            "draft_warnings": _draft_warnings,
        }
        if parse_run.status == ParseRunStatus.PARTIAL_SUCCESS:
            ctx.service.mark_partial_success(
                session,
                ctx.task_id,
                result_ref=f"parse_run://{run_id}",
                result_data=result_data,
            )
        else:
            ctx.service.mark_succeeded(
                session,
                ctx.task_id,
                result_ref=f"parse_run://{run_id}",
                result_data=result_data,
            )
        # Keep the teacher-facing material list aligned with the durable task
        # result.  A course import creates this version as PARSING; without
        # this transition the UI would show a permanently pending material
        # even though its parse run has completed.
        try:
            from sqlmodel import select
            from app.models.course_build_model import MaterialStatus, SourceMaterial, SourceMaterialVersion

            version_id = payload.get("material_version_id")
            material_id = payload.get("material_id")
            version = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.version_id == version_id,
                SourceMaterialVersion.course_id == int(course_id),
            )).first()
            if version is not None:
                version.parse_status = (
                    MaterialStatus.NEEDS_REVIEW
                    if parse_run.status == ParseRunStatus.PARTIAL_SUCCESS
                    else MaterialStatus.PARSED
                )
                version.parse_output_ref = f"parse_run://{run_id}"
                version.parse_error = ""
                session.add(version)
            material = session.exec(select(SourceMaterial).where(
                SourceMaterial.material_id == material_id,
                SourceMaterial.course_id == int(course_id),
            )).first()
            if material is not None:
                material.status = (
                    MaterialStatus.NEEDS_REVIEW
                    if parse_run.status == ParseRunStatus.PARTIAL_SUCCESS
                    else MaterialStatus.PARSED
                )
                session.add(material)
            session.commit()
            # A parse run is about one material. Once every current material
            # has completed, create one frozen corpus and queue one separate
            # course-wide build task instead of rebuilding after each upload.
            from app.services.course_corpus_service import course_corpus_service
            corpus = course_corpus_service.create_ready_snapshot(
                session, course_id=int(course_id), owner_user_id=int(payload.get("initiated_by") or 0),
            )
            if corpus is not None:
                build, build_task_id = course_corpus_service.create_build_task(
                    session, corpus=corpus, owner_user_id=int(payload.get("initiated_by") or 0),
                )
                session.commit()
                _draft_progress = {
                    "corpus_snapshot_id": corpus.corpus_snapshot_id,
                    "course_draft_build_task_id": build.build_task_id,
                    "task_id": build_task_id,
                }
                try:
                    local_task_worker.submit(
                        ctx.session_factory, build_task_id,
                        {"course_id": int(course_id), "corpus_snapshot_id": corpus.corpus_snapshot_id, "build_task_id": build.build_task_id},
                    )
                except Exception:
                    logger.exception("Could not submit course draft build task %s", build_task_id)
        except Exception:
            # Task itself is already correctly marked succeeded.  Preserve that
            # truth and log this non-critical projection repair for retry.
            session.rollback()
            logger.exception("Could not update material parse projection for run %s", run_id)


async def _invoke_document_parser(payload: dict[str, Any]) -> tuple[int, int, int]:
    """[已废弃] 旧式占位解析器。

    P0-4 后改为直接调用 document_parse_pipeline.run_parse_pipeline。
    本函数保留仅为兼容旧 import，不应再被调用。
    """
    return 0, 0, 0


async def course_draft_build_handler(ctx: TaskHandlerContext) -> None:
    """Build a course draft from one frozen multi-material corpus snapshot."""
    from sqlmodel import select

    payload = ctx.input_payload or {}
    course_id = int(payload.get("course_id") or 0)
    corpus_snapshot_id = str(payload.get("corpus_snapshot_id") or "")
    build_task_id = str(payload.get("build_task_id") or "")
    if not course_id or not corpus_snapshot_id or not build_task_id:
        raise TaskExecutionError("VALIDATION_FAILED", "course_draft_build 缺少课程或语料快照", retryable=False)

    from app.core.time_utils import utcnow_aware
    from app.models.course_build_model import (
        CourseCorpusSnapshot,
        CourseDraftBuildStatus,
        CourseDraftBuildTask,
    )
    from app.services.course_corpus_service import course_corpus_service
    from app.services.course_initial_prep_service import initial_course_prep_service
    from app.services.controlled_prep_workflow import (
        CourseBuildCancelled,
        CourseBuildStageTimeout,
    )
    from app.core.config import settings
    from app.models.course_build_model import CourseDraftBuildCheckpoint

    # Keep the durable task pending through a short quiet window. This stops a
    # teacher who is uploading several files from getting a draft after the
    # first one happens to parse quickly.
    with ctx.session_factory() as session:
        build = session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.course_id == course_id,
            CourseDraftBuildTask.build_task_id == build_task_id,
            CourseDraftBuildTask.corpus_snapshot_id == corpus_snapshot_id,
        )).first()
        if build is None:
            raise TaskExecutionError("RESOURCE_NOT_FOUND", "课程草稿构建任务不存在", retryable=False)
        if build.not_before_at:
            not_before_at = build.not_before_at
            if not_before_at.tzinfo is None:
                not_before_at = not_before_at.replace(tzinfo=timezone.utc)
            delay_seconds = max(0.0, (not_before_at - utcnow_aware()).total_seconds())
        else:
            delay_seconds = 0.0
    if delay_seconds:
        await asyncio.sleep(delay_seconds)

    with ctx.session_factory() as session:
        build = session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.course_id == course_id,
            CourseDraftBuildTask.build_task_id == build_task_id,
            CourseDraftBuildTask.corpus_snapshot_id == corpus_snapshot_id,
        )).first()
        if build is None or build.status == CourseDraftBuildStatus.CANCELLED:
            return
        corpus = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.corpus_snapshot_id == corpus_snapshot_id,
            CourseCorpusSnapshot.course_id == course_id,
        )).first()
        if corpus is None or not course_corpus_service.is_snapshot_current(session, corpus=corpus):
            build.status = CourseDraftBuildStatus.CANCELLED
            build.error_code = "CORPUS_CHANGED"
            build.error_message = "静默窗口内课程材料发生变化，已等待新的课程语料快照"
            session.add(build)
            session.commit()
            try:
                ctx.service.cancel(session, ctx.task_id, reason=build.error_message)
            except ValueError:
                pass
            return

        ctx.service.mark_running(session, ctx.task_id, stage="course_corpus")
        build.status = CourseDraftBuildStatus.RUNNING
        build.started_at = utcnow_aware()
        session.add(build)
        session.commit()

    async def on_stage(stage: str, progress: int, value: Any) -> None:
        """Persist progress/checkpoint and revalidate the course build lease."""
        with ctx.session_factory() as stage_session:
            current_build = stage_session.exec(select(CourseDraftBuildTask).where(
                CourseDraftBuildTask.course_id == course_id,
                CourseDraftBuildTask.build_task_id == build_task_id,
            )).first()
            current_corpus = stage_session.exec(select(CourseCorpusSnapshot).where(
                CourseCorpusSnapshot.course_id == course_id,
                CourseCorpusSnapshot.corpus_snapshot_id == corpus_snapshot_id,
            )).first()
            if (
                current_build is None
                or current_build.status != CourseDraftBuildStatus.RUNNING
                or current_corpus is None
                or not course_corpus_service.is_snapshot_current(stage_session, corpus=current_corpus)
            ):
                raise CourseBuildCancelled("课程语料已更新，旧备课任务已取消")
            ctx.service.mark_progress(
                stage_session,
                ctx.task_id,
                progress=progress,
                stage=stage,
                message={
                    "evidence": "正在整理材料证据",
                    "outline": "正在规划课程结构",
                    "scripts": "正在生成基础讲授脚本",
                    "verification": "正在核验讲授脚本证据",
                }.get(stage, stage),
            )
            checkpoint_stage = stage if stage != "verification" else f"verification_{progress}"
            checkpoint = stage_session.exec(select(CourseDraftBuildCheckpoint).where(
                CourseDraftBuildCheckpoint.build_task_id == build_task_id,
                CourseDraftBuildCheckpoint.stage == checkpoint_stage,
            )).first()
            payload_data = _course_build_checkpoint_payload(value)
            if checkpoint is None:
                checkpoint = CourseDraftBuildCheckpoint(
                    course_id=course_id,
                    build_task_id=build_task_id,
                    corpus_snapshot_id=corpus_snapshot_id,
                    stage=checkpoint_stage,
                    progress=progress,
                    payload=payload_data,
                )
            else:
                checkpoint.progress = progress
                checkpoint.payload = payload_data
                checkpoint.created_at = utcnow_aware()
            stage_session.add(checkpoint)
            stage_session.commit()

    try:
        with ctx.session_factory() as session:
            build = session.exec(select(CourseDraftBuildTask).where(
                CourseDraftBuildTask.build_task_id == build_task_id,
                CourseDraftBuildTask.course_id == course_id,
            )).first()
            corpus = session.exec(select(CourseCorpusSnapshot).where(
                CourseCorpusSnapshot.corpus_snapshot_id == corpus_snapshot_id,
                CourseCorpusSnapshot.course_id == course_id,
            )).first()
            if corpus is None:
                raise ValueError("课程语料快照不存在")
            if build.generation_mode == "proposal":
                # Later agent executions never overwrite a teacher's draft.
                retrieval = course_corpus_service.ensure_retrieval_snapshot(session, corpus=corpus)
                proposal = course_corpus_service.create_update_proposal(
                    session,
                    corpus=corpus,
                    created_by=build.owner_user_id,
                )
                result_data = {"proposal_id": proposal.proposal_id, "corpus_snapshot_id": corpus_snapshot_id}
            else:
                # Parsing has already produced DocumentIR/DocumentBlock facts.
                # The first teacher-visible draft must be organized by the
                # controlled preparation agent; never expose the legacy raw
                # block-to-node fallback as a completed course structure.
                # Release this read-only transaction before the runtime opens
                # its own provider session. Otherwise SQLite can hold a lock
                # across the LLM wait and make the course build look flaky.
                session.commit()
                result = None
                platform = ctx.agent_platform
                if platform is not None:
                    from app.platform.agents.prep.enums import PrepGraphKind
                    from app.platform.agents.runtime.base import AgentRunContext
                    from app.platform.agents.runtime.profile import AgentType
                    from app.platform.agents.runtime.registry import AgentDefinitionKey

                    try:
                        runtime = await platform.runtime_registry.get_or_create(
                            AgentDefinitionKey(
                                agent_type=AgentType.PREP.value,
                                agent_version=PrepGraphKind.INITIAL.value,
                            )
                        )
                        runtime_result = await asyncio.wait_for(
                            runtime.run(
                                context=AgentRunContext(
                                    agent_type=AgentType.PREP.value,
                                    scope=(str(course_id),),
                                    course_id=str(course_id),
                                    teacher_id=str(build.owner_user_id or ""),
                                    extras={
                                        "corpus_snapshot_id": corpus_snapshot_id,
                                        "build_task_id": build.build_task_id,
                                        "replace_unreviewed_initial": build.trigger == "teacher_restart_unreviewed_initial",
                                        "stage_callback": on_stage,
                                    },
                                    run_id=f"prep_initial_{build.build_task_id}",
                                )
                            ),
                            timeout=max(1, int(settings.COURSE_BUILD_TOTAL_TIMEOUT_SECONDS)),
                        )
                        failure = _initial_runtime_failure(runtime_result)
                        if failure is not None:
                            raise failure
                        result_payload = runtime_result.get("result") or {}
                        from app.services.document_draft_builders import DraftAssetResult
                        result = DraftAssetResult(
                            course_id=course_id,
                            run_id=f"prep_initial_{build.build_task_id}",
                            material_version_id=None,
                            corpus_snapshot_id=corpus_snapshot_id,
                            outline_version_id=result_payload.get("outline_version_id") or None,
                            script_version_id=result_payload.get("script_version_id") or None,
                            graph_candidate_batch_id=result_payload.get("graph_candidate_batch_id") or None,
                            warnings=list(result_payload.get("warnings") or []),
                            rag_indexed_chunks=int(result_payload.get("rag_indexed_chunks") or 0),
                            graph_node_candidates=int(result_payload.get("graph_node_candidates") or 0),
                            graph_relation_candidates=int(result_payload.get("graph_relation_candidates") or 0),
                            outline_node_count=int(result_payload.get("outline_node_count") or 0),
                            script_node_count=int(result_payload.get("script_node_count") or 0),
                            markdown_resource_id=result_payload.get("markdown_resource_id") or None,
                            markdown_resource_version_id=result_payload.get("markdown_resource_version_id") or None,
                        )
                    except Exception as runtime_error:
                        # Keep the old direct call as a controlled compatibility
                        # fallback only when the registered Initial runtime is
                        # unavailable, not when the runtime reports a build
                        # failure (which must remain visible to the teacher).
                        from app.platform.agents.runtime.errors import AgentNotAvailableError
                        if isinstance(runtime_error, AgentNotAvailableError):
                            logger.warning("Initial Prep runtime unavailable; using service compatibility path: %s", runtime_error)
                        else:
                            raise
                if result is None:
                    result = await asyncio.wait_for(
                        initial_course_prep_service.build(
                            session,
                            course_id=course_id,
                            created_by=build.owner_user_id,
                            corpus_snapshot_id=corpus_snapshot_id,
                            build_task_id=build.build_task_id,
                            replace_unreviewed_initial=(build.trigger == "teacher_restart_unreviewed_initial"),
                            on_stage=on_stage,
                        ),
                        timeout=max(1, int(settings.COURSE_BUILD_TOTAL_TIMEOUT_SECONDS)),
                    )
                retrieval = course_corpus_service.ensure_retrieval_snapshot(session, corpus=corpus)
                build.result_outline_version_id = result.outline_version_id
                build.result_script_version_id = result.script_version_id
                result_data = result.to_progress_data()
            build.result_retrieval_snapshot_id = retrieval.retrieval_snapshot_id
            if not course_corpus_service.is_snapshot_current(session, corpus=corpus):
                raise CourseBuildCancelled("课程语料已更新，未提交旧版本草稿")
            ctx.service.mark_progress(
                session,
                ctx.task_id,
                progress=100,
                stage="persisting",
                message="课程结构、讲授脚本及关联映射已完成持久化",
            )
            checkpoint = session.exec(select(CourseDraftBuildCheckpoint).where(
                CourseDraftBuildCheckpoint.build_task_id == build_task_id,
                CourseDraftBuildCheckpoint.stage == "persisting",
            )).first()
            if checkpoint is not None:
                checkpoint.progress = 100
                checkpoint.payload = result_data
                checkpoint.created_at = utcnow_aware()
                session.add(checkpoint)
            build.status = CourseDraftBuildStatus.SUCCEEDED
            build.finished_at = utcnow_aware()
            session.add(build)
            session.commit()
    except CourseBuildCancelled as exc:
        with ctx.session_factory() as session:
            build = session.exec(select(CourseDraftBuildTask).where(
                CourseDraftBuildTask.build_task_id == build_task_id,
                CourseDraftBuildTask.course_id == course_id,
            )).first()
            if build is not None:
                build.status = CourseDraftBuildStatus.CANCELLED
                build.error_code = "CORPUS_CHANGED"
                build.error_message = str(exc)[:500]
                build.finished_at = utcnow_aware()
                session.add(build)
            try:
                task = ctx.service.get_task(session, ctx.task_id)
                if task.status in {"pending", "running"}:
                    ctx.service.cancel(session, ctx.task_id, reason=str(exc))
                else:
                    session.commit()
            except ValueError:
                session.commit()
        return
    except asyncio.TimeoutError as exc:
        with ctx.session_factory() as session:
            build = session.exec(select(CourseDraftBuildTask).where(
                CourseDraftBuildTask.build_task_id == build_task_id,
                CourseDraftBuildTask.course_id == course_id,
            )).first()
            if build:
                build.status = CourseDraftBuildStatus.FAILED
                build.error_code = "COURSE_BUILD_TIMEOUT"
                build.error_message = f"课程备课超过 {settings.COURSE_BUILD_TOTAL_TIMEOUT_SECONDS} 秒"
                build.finished_at = utcnow_aware()
                session.add(build)
                session.commit()
        raise TaskExecutionError("COURSE_BUILD_TIMEOUT", str(exc), retryable=True) from exc
    except CourseBuildStageTimeout as exc:
        with ctx.session_factory() as session:
            build = session.exec(select(CourseDraftBuildTask).where(
                CourseDraftBuildTask.build_task_id == build_task_id,
                CourseDraftBuildTask.course_id == course_id,
            )).first()
            if build:
                build.status = CourseDraftBuildStatus.FAILED
                build.error_code = "COURSE_BUILD_STAGE_TIMEOUT"
                build.error_message = str(exc)[:500]
                build.finished_at = utcnow_aware()
                session.add(build)
                session.commit()
        raise TaskExecutionError("COURSE_BUILD_STAGE_TIMEOUT", str(exc), retryable=True) from exc
    except Exception as exc:
        failure_message = _course_build_failure_message(exc)
        with ctx.session_factory() as session:
            build = session.exec(select(CourseDraftBuildTask).where(
                CourseDraftBuildTask.build_task_id == build_task_id,
                CourseDraftBuildTask.course_id == course_id,
            )).first()
            if build:
                build.status = CourseDraftBuildStatus.FAILED
                build.error_code = "COURSE_DRAFT_BUILD_FAILED"
                build.error_message = failure_message
                build.finished_at = utcnow_aware()
                session.add(build)
                session.commit()
        raise TaskExecutionError("COURSE_DRAFT_BUILD_FAILED", failure_message, retryable=True) from exc

    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session, ctx.task_id,
            result_ref=f"course_corpus://{corpus_snapshot_id}",
            result_data={"build_task_id": build_task_id, **result_data},
        )


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
    student_id = payload.get("student_id")
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
        # 验证学生归属：payload 中的 student_id 必须与 ExperimentRun 记录一致，
        # 防止伪造 run_id/attempt_id 访问他人数据
        if student_id is not None and run.student_id != int(student_id):
            raise TaskExecutionError(
                "STUDENT_MISMATCH",
                f"Student ID mismatch: expected {student_id}, got {run.student_id}",
                retryable=False,
            )
        # 使用 run 记录中的 student_id 校验 attempt 归属（权威来源）
        attempt = attempt_service.get_attempt(
            session, course_id=int(course_id), attempt_id=attempt_id,
            student_id=run.student_id,
        )
        version = version_service.get_version(
            session, course_id=int(course_id), version_id=attempt.version_id,
        )
        try:
            await run_service._execute_run(
                session, run=run, attempt=attempt, version=version,
            )
            # Persist the bounded diagnosis in the same worker transaction as
            # the verified run result.  This keeps the normal path usable by
            # EduAgent without requiring a second client request.
            run_service._ensure_coding_diagnosis(session, run)
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


async def media_tts_handler(ctx: TaskHandlerContext) -> None:
    """Consume a paid TTS task outside the FastAPI request event loop.

    The real Provider has a synchronous public contract, so the blocking v3
    WebSocket session runs in a worker thread with its own database session.
    Fake/Mock providers remain available through the legacy synchronous test
    endpoint and never cause a paid network request in automated tests.
    """
    payload = ctx.input_payload or {}
    course_id = int(payload.get("course_id") or 0)
    job_id = str(payload.get("job_id") or "")
    script_text = str(payload.get("script_text") or "")
    if not course_id or not job_id or not script_text:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "media.tts handler 缺少 course_id/job_id/script_text",
            retryable=False,
        )

    provider_key = str(payload.get("provider_key") or "")

    def run_in_worker_thread() -> tuple[str | None, str | None]:
        from sqlmodel import select
        from app.models.media_release_model import MediaGenerationJob
        from app.services.media_release_service import tts_execution_service

        with ctx.session_factory() as session:
            job = session.exec(select(MediaGenerationJob).where(
                MediaGenerationJob.job_id == job_id,
                MediaGenerationJob.course_id == course_id,
                MediaGenerationJob.task_id == ctx.task_id,
            )).first()
            if job is None:
                raise TaskExecutionError(
                    "RESOURCE_NOT_FOUND",
                    "media.tts 任务与课程或统一任务记录不匹配",
                    retryable=False,
                )
            tts_execution_service.execute_tts_job(
                session,
                course_id=course_id,
                job_id=job_id,
                script_text=script_text,
                voice_id=str(payload.get("voice_id") or "default"),
                resource_version=str(payload.get("resource_version") or "v1"),
                provider_key=str(payload.get("provider_key") or job.provider_key or ""),
                max_retries=payload.get("max_retries"),
            )
            session.commit()
            session.refresh(job)
            return job.media_release_id, job.job_id

    # Provider calls are bounded independently from request concurrency.  A
    # batch may queue many nodes, but at most the configured number can hold a
    # live paid WebSocket for the same provider.
    from app.core.config import settings
    from app.services.media_batch_service import enqueue_batch_cue, project_tts_result_to_batch_item
    limit = max(1, int(getattr(settings, "MEDIA_TTS_MAX_CONCURRENT_PER_PROVIDER", 2) or 2))
    semaphore = _tts_provider_semaphore(provider_key, limit)
    await asyncio.to_thread(semaphore.acquire)
    try:
        release_id, completed_job_id = await asyncio.to_thread(run_in_worker_thread)
    finally:
        semaphore.release()

    if not release_id or not completed_job_id:
        return
    with ctx.session_factory() as session:
        source = media_generation_job_service.get_job(session, course_id=course_id, job_id=completed_job_id)
        if source.status != MediaGenerationStatus.SUCCEEDED:
            project_tts_result_to_batch_item(session, job=source)
            session.commit()
            return
        project_tts_result_to_batch_item(session, job=source)
        cue_job, cue_task_id = enqueue_batch_cue(
            session, course_id=course_id, release_id=release_id,
            source_tts_job=source, created_by=source.created_by,
        )
        session.commit()
    if cue_job.status == MediaGenerationStatus.PENDING:
        if not local_task_worker.has_handler("media.timeline_publish"):
            with ctx.session_factory() as session:
                source = media_generation_job_service.get_job(session, course_id=course_id, job_id=completed_job_id)
                from app.services.media_batch_service import project_cue_result_to_batch_item
                project_cue_result_to_batch_item(
                    session, course_id=course_id, release_id=release_id,
                    source_tts_job=source, error_code="DEPENDENCY_UNAVAILABLE",
                    error_message_safe="Cue Worker 未注册，未冻结字幕与数字人时间轴",
                )
                session.commit()
            return
        local_task_worker.submit(ctx.session_factory, cue_task_id, {
            **(cue_job.input_payload or {}), "job_id": cue_job.job_id,
        })


# ---------------------------------------------------------------------------
# media.timeline_publish handler (P2 cue manifest freeze)
# ---------------------------------------------------------------------------


async def media_timeline_publish_handler(ctx: TaskHandlerContext) -> None:
    """Build release-scoped subtitle and avatar cue manifests.

    This is intentionally a separate worker task from TTS: a successful audio
    file can be inspected/reused without ever asking the Provider to speak
    again, while a failed cue build remains auditable as its own media job.
    """
    payload = ctx.input_payload or {}
    course_id = int(payload.get("course_id") or 0)
    release_id = str(payload.get("release_id") or "")
    source_tts_job_id = str(payload.get("source_tts_job_id") or "")
    if not course_id or not release_id or not source_tts_job_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED",
            "media.timeline_publish handler 缺少 course_id/release_id/source_tts_job_id",
            retryable=False,
        )

    from sqlmodel import select
    from app.models.media_release_model import MediaGenerationJob, MediaGenerationStatus
    from app.services.avatar_cue_service import AvatarCueBuildError, build_avatar_cues_from_tts_job
    from app.services.media_release_service import media_generation_job_service

    with ctx.session_factory() as session:
        job = session.exec(select(MediaGenerationJob).where(
            MediaGenerationJob.course_id == course_id,
            MediaGenerationJob.task_id == ctx.task_id,
        )).first()
        if job is None:
            raise TaskExecutionError(
                "RESOURCE_NOT_FOUND",
                "Cue Worker 任务与课程或统一任务记录不匹配",
                retryable=False,
            )
        job_id = job.job_id
        if job.status == MediaGenerationStatus.SUCCEEDED:
            return
        media_generation_job_service.mark_running(
            session, course_id=course_id, job_id=job_id, stage="freeze_avatar_cues",
        )
        try:
            result = build_avatar_cues_from_tts_job(
                session,
                course_id=course_id,
                release_id=release_id,
                tts_job_id=source_tts_job_id,
                outline_node_id=payload.get("outline_node_id") or None,
            )
        except AvatarCueBuildError as exc:
            media_generation_job_service.mark_failed(
                session,
                course_id=course_id,
                job_id=job_id,
                error_code=exc.error_code,
                error_message_safe=exc.safe_message,
                retryable=False,
            )
            source_tts = media_generation_job_service.get_job(
                session, course_id=course_id, job_id=source_tts_job_id,
            )
            from app.services.media_batch_service import project_cue_result_to_batch_item
            project_cue_result_to_batch_item(
                session, course_id=course_id, release_id=release_id,
                source_tts_job=source_tts, error_code=exc.error_code,
                error_message_safe=exc.safe_message,
            )
            session.commit()
            return
        media_generation_job_service.mark_succeeded(
            session,
            course_id=course_id,
            job_id=job_id,
            output_object_key=result.avatar_cues_object_key,
            output_metadata={
                "avatar_cues_schema": "avatar-cues/v1",
                "avatar_cues_object_key": result.avatar_cues_object_key,
                "subtitle_manifest_object_key": result.subtitle_manifest_object_key,
                "audio_object_key": result.audio_object_key,
                "audio_sha256": result.audio_sha256,
                "duration_ms": result.duration_ms,
                "cue_count": result.cue_count,
                "viseme_count": result.viseme_count,
                "timing_source": result.timing_source,
                "content_hash": result.content_hash,
                "warnings": result.warnings,
            },
        )
        source_tts = media_generation_job_service.get_job(
            session, course_id=course_id, job_id=source_tts_job_id,
        )
        from app.services.media_batch_service import project_cue_result_to_batch_item
        project_cue_result_to_batch_item(
            session, course_id=course_id, release_id=release_id,
            source_tts_job=source_tts, result=result,
        )
        session.commit()


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
    worker.register("course_draft_build", course_draft_build_handler)
    worker.register("experiment_run", experiment_run_handler)
    worker.register("media.avatar_preprocess", media_avatar_preprocess_handler)
    worker.register("agent_action_execute", agent_action_execute_handler)
    worker.register("question_bank.import", question_bank_import_handler)
    from app.platform.tasks.knowledge_handlers import (
        knowledge_graphrag_build_handler,
        knowledge_vector_index_handler,
    )
    worker.register("knowledge.graphrag_build", knowledge_graphrag_build_handler)
    worker.register("knowledge.vector_index", knowledge_vector_index_handler)

    # Paid TTS and P2 cue freezing have real worker handlers.  Other media
    # generation task types stay on their existing generic compatibility path.
    worker.register("media.tts", media_tts_handler)
    worker.register("media.timeline_publish", media_timeline_publish_handler)
    for job_type in ("subtitle", "avatar_preprocess", "dh_render", "video_package"):
        task_type = f"media.{job_type}"
        if not worker.has_handler(task_type):
            worker.register(task_type, media_generic_handler)


def register_all_handlers(worker: LocalTaskWorker = local_task_worker) -> None:
    """注册全部 handler（自检 + 业务）。

    在 main.py startup 调用一次，保证 worker 能消费所有已注册 task_type。
    """
    register_builtin_handlers(worker)
    register_business_handlers(worker)
