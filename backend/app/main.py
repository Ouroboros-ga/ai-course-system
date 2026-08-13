# app/main.py
import logging
import os
from importlib.util import find_spec

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.signature_middleware import SignatureMiddleware
from app.core.error_monitoring import ErrorMonitoringMiddleware, monitor as error_monitor
from app.core.exceptions import global_exception_handler, unified_response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.common.dependency_checker import run_dependency_check


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def _startup_side_effects_disabled() -> bool:
    return _env_flag("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS")


def _mount_optional_fanya_chaoxing_ai_compat(application: FastAPI) -> None:
    """Mount the removable external compatibility package when it exists.

    The core app intentionally has no hard import of this optional package.
    Removing ``app/external_apis/fanya_chaoxing_ai`` therefore only removes
    ``/api/v1/compat/*``; all internal APIs still start normally.
    """
    module_name = "app.external_apis.fanya_chaoxing_ai"
    try:
        available = find_spec(module_name) is not None
    except ModuleNotFoundError:
        available = False
    if not available:
        logger.info("Optional Fanya/Chaoxing AI compatibility package is absent; not mounting it")
        return
    from app.external_apis.fanya_chaoxing_ai import router as compat_router

    compat_prefix = "/api/v1/compat"
    owned_prefixes = set(getattr(application.state, "signature_owned_path_prefixes", ()))
    owned_prefixes.add(f"{compat_prefix}/")
    # The global middleware reads this state for every request.  It is set only
    # while an optional adapter is mounted, so removing the adapter directory
    # does not leave a permanently unauthenticated path behind.
    application.state.signature_owned_path_prefixes = tuple(sorted(owned_prefixes))
    application.include_router(
        compat_router,
        prefix=compat_prefix,
        tags=["泛雅·超星 AI 开放 API 参考兼容层"],
    )


def run_startup_side_effects():
    """启动时执行依赖检查与任务 handler 注册。

    数据库结构变更由部署流程显式执行 `alembic upgrade head`，
    不再在应用启动时隐式 create_all 或 run_migrations。
    见 alembic.ini 与 app/scripts/migration_ops.py。

    任务中心 handler 注册：确保 LocalTaskWorker 能消费业务任务
    （document_parse / experiment_run / media.* 等），避免任务停留在 pending
    或被标记为 DEPENDENCY_UNAVAILABLE。
    """
    dep_report = run_dependency_check(auto_install=True)
    if not dep_report["python_ok"]:
        logger.error("必需的Python依赖缺失，请手动安装后重启服务")
    if dep_report["python_installed"]:
        logger.info(f"自动安装的Python包: {', '.join(dep_report['python_installed'])}")

    # 启动任务扫尾：把上一进程遗留的 pending/running 任务标为 interrupted。
    # LocalTaskWorker 用 asyncio.create_task 执行，进程重启后这些任务既不会
    # 成功也不会失败，会永远停在 running。此处把它们转为 interrupted，
    # 使其从"处理中"视图中移除并给出"重新解析"操作；不自动恢复。
    # Step 0 of 统一课程建设九步实施计划。
    try:
        from app.models.database import session_factory
        from app.services.task_service import task_service
        with session_factory() as session:
            report = task_service.sweep_stale_running(session, grace_seconds=0)
        logger.info("Startup task sweep: %d stale task(s) marked interrupted",
                    report.get("swept", 0))
    except Exception:
        logger.exception("Startup task sweep failed; stale running tasks may persist")

    return dep_report


def register_task_handlers() -> None:
    """Register durable local task handlers even in no-side-effect mode.

    ``AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS`` skips dependency installation and
    database maintenance for tests and controlled local starts. It must not
    turn a running API into an upload-only service that leaves parse tasks in
    ``pending`` forever.
    """
    try:
        from app.platform.tasks.handlers import register_all_handlers
        register_all_handlers()
        logger.info("Task worker handlers registered (self_check + business)")
    except Exception:
        logger.exception("Failed to register task worker handlers; tasks will stay pending")


startup_side_effects_skipped = _startup_side_effects_disabled()
startup_dependency_report = None


# 导入路由
from app.api.v1.endpoints import (
    user, document, chat, progress, knowledge,
    asset,              # F1 老师素材管理
    mapping,            # F2/F5 知识点↔PPT映射引擎
    player,             # F6 分屏视频播放器
    ppt_generation,     # F3 AI生成PPT课件
    video_generation,   # F4/F5 数字人视频生成管线
    video,              # 视频相关功能
    platform,           # 平台管理功能
    prerequisite,       # 前置知识智能跳转
    document_v2,        # P1-09 G3B V2 shadow (independent router, ADR-0006)
    evidence_v2,        # P1-09 G4A V2 Evidence API DTO (internal-evidence-api/1.0, ADR-0006)
    canary_v2,          # P1-09 G5A V2 Canary quality-gate (no real services, ADR-0006)
    retrieval_demo,     # Shadow-1 local retrieval demo (isolated from V1)
    teaching_agent,     # Controlled LangGraph single-agent workflow; runtime injected explicitly
    learning_adjustments,  # Learner-confirmed review and manual return transitions
    note,               # 笔记模块
    dashboard,          # 首页与课程概览聚合
    confirmation,       # 教师确认持久化
    citation,           # 引用稳定定位
    feedback,           # 向教师反馈通道
    course_access,
    question_bank,      # Phase B 题库管理
    question_source_mapping,  # Phase B 题源映射
    cognitive_recommendation,  # G2 六维认知与推荐
    sandbox,            # G3 代码沙箱
    visualization,      # G4 算法可视化
    facade,             # Phase A 门面层
    safety,             # G6 安全围栏与沙箱治理
    web_research,       # G7 WebResearchTool
    research_agent,     # ResearchAgent evidence-first scholarly research
    media_timeline,     # G8 媒体时间轴
    graph_production,   # G9 Evidence与图谱
    graphrag,           # GraphRAG + immutable CourseKnowledgeBundle
    tasks,              # 阶段0 统一任务中心
    course_lifecycle,   # 阶段2 成员/设置/加入申请/泛雅同步
    course_creation,    # P0 空课程创建与统一材料上传
    course_build,       # 阶段3 课程建设工作流
    course_build_editor, # Step 5-8 课程树/讲稿/提案/发布
    course_outline,
    document_parse,     # 阶段4 课程材料解析、Evidence、Citation与图谱治理
    practice_recommendation,  # 阶段5 题库、练习推荐、正式学习证据
    experiments,        # 阶段6 课程实验、Judge0 与 CodingAgent
    resources,          # 阶段7 资源库
    labs,               # 阶段7 平台实验室目录
    agent_governance,   # 阶段9 Agent 工具治理与教师安全阀
    historical_rebuild, # 阶段10 历史课程补建清单编排
    storage_admin,      # G5 对象存储运维（refs/GC/回读校验）
    admin_platform,     # 平台 Provider 配置与用户管理
)
from app.schemas import UnifiedResponse

register_task_handlers()

if startup_side_effects_skipped:
    logger.info("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS enabled; startup dependency checks, table creation and migrations are skipped.")
else:
    startup_dependency_report = run_startup_side_effects()

# G6: 自定义 operation ID 生成函数，确保全局唯一。
# FastAPI 默认用端点函数名作为 operation_id；当多个路由模块存在同名函数
# （如 list_evidence / submit_attempt / create_release）时会产生冲突，
# 破坏 OpenAPI 客户端代码生成。此处用「路由路径 + 函数名」保证唯一性。
from fastapi.routing import APIRoute


def _generate_unique_operation_id(route: APIRoute) -> str:
    """生成全局唯一的 OpenAPI operation_id。

    格式：``{path}_{name}``，其中 path 替换非字母数字字符为下划线。
    例如 ``/api/v1/graph/course/{course_id}/evidence`` + ``list_evidence``
    → ``api_v1_graph_course_course_id_evidence_list_evidence``。
    """
    safe_path = route.path.replace("/", "_").replace("{", "").replace("}", "")
    safe_path = safe_path.replace("-", "_").replace(".", "_")
    # 去除开头多余的下划线
    safe_path = safe_path.lstrip("_")
    return f"{safe_path}_{route.name}"


# 创建FastAPI实例
app = FastAPI(
    title="超星AI互动智课系统",
    description="符合超星开放API设计规范的后端服务",
    version="v1",
    generate_unique_id_function=_generate_unique_operation_id,
)
app.state.startup_side_effects_skipped = startup_side_effects_skipped
app.state.startup_dependency_report = startup_dependency_report


@app.on_event("startup")
async def recover_durable_task_queues() -> None:
    """Recover durable work that is safe to resume after a local restart."""
    try:
        from app.models.database import session_factory
        from app.platform.tasks.document_parse_queue import document_parse_queue
        from app.platform.tasks.worker import local_task_worker
        await document_parse_queue.recover(session_factory, local_task_worker)
    except Exception:
        logger.exception("Document parse queue recovery failed")
    try:
        from app.models.database import session_factory
        from app.platform.tasks.course_draft_build_queue import recover_course_draft_build_queue
        from app.platform.tasks.worker import local_task_worker

        await recover_course_draft_build_queue(session_factory, local_task_worker)
    except Exception:
        logger.exception("Course draft build queue recovery failed")
    try:
        from app.models.database import session_factory
        from app.platform.tasks.knowledge_build_queue import knowledge_build_queue
        from app.platform.tasks.worker import local_task_worker

        await knowledge_build_queue.recover(session_factory, local_task_worker)
    except Exception:
        logger.exception("Knowledge Bundle build queue recovery failed")
    try:
        from app.models.database import session_factory
        from app.platform.tasks.media_manifest_queue import recover_media_manifest_tasks
        from app.platform.tasks.worker import local_task_worker

        await recover_media_manifest_tasks(session_factory, local_task_worker)
    except Exception:
        logger.exception("PPT manifest task recovery failed")
    try:
        from app.models.database import session_factory
        from app.platform.tasks.experiment_run_queue import recover_experiment_run_tasks
        from app.platform.tasks.worker import local_task_worker

        await recover_experiment_run_tasks(session_factory, local_task_worker)
    except Exception:
        logger.exception("Formal experiment run recovery failed")
    try:
        from app.services.learning_projection_outbox_service import (
            recover_learning_projection_outbox,
        )

        await recover_learning_projection_outbox()
    except Exception:
        logger.exception("Learning projection outbox recovery failed")

# P1: opt-in TeachingAgent runtime injection. Default TEACHING_AGENT_MODE=
# disabled -> no injection -> the endpoint stays 503. KG-MEST reports and
# course sidecars are optional enrichments; only runtime/LLM configuration
# controls injection. Never blocks startup; see bootstrap.py.
from app.platform.agents.bootstrap import (
    bootstrap_coding_agent,
    bootstrap_prep_agent,
    bootstrap_research_agent,
    bootstrap_teaching_agent,
)
bootstrap_prep_agent(app)
bootstrap_research_agent(app)
bootstrap_coding_agent(app)
bootstrap_teaching_agent(app)

# 注册签名验证中间件（必须在CORS之后，路由之前）
app.add_middleware(SignatureMiddleware)

# CORS跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 错误监控中间件（最外层，观测所有 >= 400 响应；批次0上线底座）
app.add_middleware(ErrorMonitoringMiddleware)
# 暴露错误计数快照供运维读取
app.state.error_monitor = error_monitor

# 注册全局异常处理
app.add_exception_handler(HTTPException, global_exception_handler)
_mount_optional_fanya_chaoxing_ai_compat(app)

# 注册路由
app.include_router(user.router, prefix="/api/v1/user", tags=["用户模块"])
app.include_router(admin_platform.router, prefix="/api/v1/admin", tags=["平台管理员"])
app.include_router(document.router, prefix="/api/v1/document", tags=["文档处理"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["聊天模块"])
app.include_router(progress.router, prefix="/api/v1/progress", tags=["进度续接"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["知识库管理"])
app.include_router(prerequisite.router, tags=["前置知识智能跳转"])

# F1-F7 功能模块路由（2026-05-26 补全）
app.include_router(asset.router, prefix="/api/v1/asset", tags=["F1-素材管理"])
app.include_router(mapping.router, prefix="/api/v1/mapping", tags=["F2/F5-映射引擎"])
app.include_router(player.router, prefix="/api/v1/player", tags=["F6-分屏播放器"])
app.include_router(ppt_generation.router, prefix="/api/v1/ppt", tags=["F3-PPT生成"])
app.include_router(video_generation.router, prefix="/api/v1/video-gen", tags=["F4/F5-视频生成"])
app.include_router(video.router, prefix="/api/v1/video", tags=["视频功能"])
app.include_router(platform.router, prefix="/api/v1/platform", tags=["平台管理"])

# P0 新增功能模块路由
app.include_router(note.router, prefix="/api/v1/notes", tags=["笔记模块"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["仪表盘"])
app.include_router(confirmation.router, prefix="/api/v1/confirmations", tags=["教师确认"])
app.include_router(citation.router, prefix="/api/v1/citations", tags=["引用定位"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["学生反馈"])

# 按照接口文档规范，/chat/file/upload 也映射到文档上传处理
app.include_router(course_access.router, prefix="/api/v1/course-access", tags=["课程权限"])
app.include_router(document.router, prefix="/api/v1/chat/file", tags=["聊天模块"])

# Phase B: 题库管理与题源映射
app.include_router(question_bank.router, prefix="/api/v1/question-bank", tags=["Phase B 题库管理"])
app.include_router(question_source_mapping.router, prefix="/api/v1/question-mapping", tags=["Phase B 题源映射"])

# G2: 六维认知与推荐
app.include_router(cognitive_recommendation.router, prefix="/api/v1/cognitive", tags=["G2 六维认知与推荐"])

# G3: 代码沙箱
app.include_router(sandbox.router, prefix="/api/v1/sandbox", tags=["G3 代码沙箱"])

# G4: 算法可视化
app.include_router(visualization.router, prefix="/api/v1/visualization", tags=["G4 算法可视化"])

# Phase A: 前后端契约对齐门面层
app.include_router(facade.router, prefix="/api/v1/facade", tags=["Phase A 门面层"])

# G6: 安全围栏与沙箱治理
app.include_router(safety.router, prefix="/api/v1/safety", tags=["G6 安全围栏与沙箱治理"])

# G7: WebResearchTool 受控研究
app.include_router(web_research.router, prefix="/api/v1/web-research", tags=["G7 WebResearchTool"])
app.include_router(research_agent.router, prefix="/api/v1/research-agent", tags=["ResearchAgent"])

# G8: 媒体时间轴与数字人
app.include_router(media_timeline.router, prefix="/api/v1/media", tags=["G8 媒体时间轴"])

# G9: Evidence与课程知识图谱生产化
app.include_router(graph_production.router, prefix="/api/v1/graph", tags=["G9 Evidence与图谱"])
app.include_router(graphrag.router, prefix="/api/v1/graph", tags=["GraphRAG Knowledge Bundle"])

# P1-09 G3B: V2 shadow query router (independent, ADR-0006 §9). Admin/internal
# only; 503 SHADOW_FEATURE_DISABLED when flag not v2_shadow. Does NOT touch V1
# document.py routes. Default flag v1_only -> endpoints return 503.
app.include_router(document_v2.router, prefix="/api/v1/document-v2", tags=["Product1-V2-shadow"])

# P1-09 G4A: independent V2 Evidence API router (internal-evidence-api/1.0).
# Admin-only (Depends(admin_only)); 503 SHADOW_FEATURE_DISABLED when
# EVIDENCE_CITATION_MODE not v2_shadow. Serves the frozen Evidence API DTO
# to the P1-04 Evidence Viewer. Does NOT touch V1 routes.
app.include_router(evidence_v2.router, prefix="/api/v1/evidence-v2", tags=["Product1-V2-shadow"])

# P1-09 G5A: independent V2 Canary quality-gate router. Admin-only; 503
# SHADOW_FEATURE_DISABLED when EVIDENCE_CITATION_MODE not v2_shadow. Runs
# end-to-end shadow canary WITHOUT real services (no LLM/Docling/OCR/vector);
# real-provider canary (G5B) deferred. Does NOT touch V1 routes.
app.include_router(canary_v2.router, prefix="/api/v1/canary-v2", tags=["Product1-V2-shadow"])

# Shadow-1: local-only, admin-visible R2 retrieval demonstration.  Default
# mode is v1_only; this independent router never touches chat.py/document.py.
app.include_router(retrieval_demo.router, prefix="/api/v1/retrieval-demo", tags=["Shadow-1-retrieval-demo"])

# TeachingAgent is intentionally independent from V1 chat. It returns 503 until
# an application composition root injects scope-checked domain Ports.
app.include_router(teaching_agent.router, prefix="/api/v1/teaching-agent", tags=["TeachingAgent"])
app.include_router(learning_adjustments.router, prefix="/api/v1/learning-adjustments", tags=["Learning adjustments"])

# 阶段0：统一任务中心（OCR/解析/图谱/媒体/实验/同步等长任务的持久化与状态机）
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["任务中心"])

# 阶段2：成员、设置、加入申请与课程生命周期
app.include_router(
    course_lifecycle.join_requests_router,
    prefix="/api/v1/course-access",
    tags=["阶段2 加入申请"],
)
app.include_router(
    course_lifecycle.course_groups_router,
    prefix="/api/v1/course-groups",
    tags=["阶段2 课程分组"],
)
app.include_router(
    course_lifecycle.course_settings_router,
    prefix="/api/v1/course-settings",
    tags=["阶段2 课程设置"],
)
app.include_router(
    course_lifecycle.integrations_router,
    prefix="/api/v1/integrations",
    tags=["阶段2 平台集成同步"],
)
app.include_router(
    course_lifecycle.audit_router,
    prefix="/api/v1/audit",
    tags=["阶段2 课程审计"],
)
app.include_router(
    course_creation.course_creation_router,
    prefix="/api/v1/courses",
    tags=["课程创建"],
)
app.include_router(
    course_creation.course_materials_router,
    prefix="/api/v1/courses",
    tags=["课程材料"],
)

# 阶段3：统一任务中心与教师课程建设工作流
app.include_router(
    course_build.course_build_router,
    prefix="/api/v1/course-build",
    tags=["阶段3 课程建设工作流"],
)
app.include_router(
    course_build_editor.router,
    prefix="/api/v1/course-editor",
    tags=["课程树、讲稿与备课提案"],
)
app.include_router(
    course_outline.course_outline_router,
    prefix="/api/v1/course-outline",
    tags=["课程版本化结构与讲稿"],
)

# 阶段4：课程材料解析、Evidence、Citation 与图谱治理
# - 解析流水线、候选证据审核、学生可读 Citation、图谱候选批次 路由挂载到 /api/v1/graph 下，
#   与已有 graph_production 路由共享前缀，但路由路径不冲突。
app.include_router(
    document_parse.document_parse_router,
    prefix="/api/v1/graph",
    tags=["阶段4 材料解析与证据治理"],
)
# - facade: 知识空间首屏与课程健康度 路由挂载到 /api/v1/facade 下
app.include_router(
    document_parse.facade_knowledge_router,
    prefix="/api/v1/facade",
    tags=["阶段4 知识空间与健康度门面"],
)

# 阶段5：题库、练习推荐、正式学习证据
app.include_router(
    practice_recommendation.practice_router,
    prefix="/api/v1/practice",
    tags=["阶段5 题库与练习推荐"],
)
app.include_router(
    practice_recommendation.facade_learning_actions_router,
    prefix="/api/v1/facade",
    tags=["阶段5 学习动作门面"],
)

# 阶段6：课程实验、Judge0 与 CodingAgent
app.include_router(
    experiments.experiment_router,
    prefix="/api/v1/experiments",
    tags=["阶段6 课程实验与 CodingAgent"],
)

# 阶段7：资源库
app.include_router(
    resources.resource_router,
    prefix="/api/v1/resources",
    tags=["阶段7 资源库"],
)

# 阶段7：平台实验室目录
app.include_router(
    labs.lab_router,
    prefix="/api/v1/lab",
    tags=["阶段7 平台实验室"],
)

# 阶段8：媒体生成与发布（挂在 /api/v1/media 前缀下，与现有 media_timeline 共用）
from app.api.v1.endpoints import media_release as media_release_endpoints  # noqa: E402
app.include_router(
    media_release_endpoints.media_release_router,
    prefix="/api/v1/media",
    tags=["阶段8 媒体生成与发布"],
)

# 阶段8：教师数字人资产中心
from app.api.v1.endpoints import avatar as avatar_endpoints  # noqa: E402
app.include_router(
    avatar_endpoints.avatar_router,
    prefix="/api/v1",
    tags=["阶段8 教师数字人资产中心"],
)
app.include_router(
    avatar_endpoints.course_avatar_router,
    prefix="/api/v1",
    tags=["阶段8 课程数字人绑定"],
)

# 阶段9：Agent 工具治理与教师安全阀
app.include_router(
    agent_governance.agent_governance_router,
    prefix="/api/v1/agent-governance",
    tags=["阶段9 Agent治理与教师安全阀"],
)

# 阶段10：历史课程补建清单编排
app.include_router(
    historical_rebuild.historical_rebuild_router,
    prefix="/api/v1/historical-rebuild",
    tags=["阶段10 历史课程补建清单"],
)

# G5：对象存储运维（refs/GC/回读校验/迁移对账）
app.include_router(
    storage_admin.storage_admin_router,
    prefix="/api/v1/admin/storage",
    tags=["G5 对象存储运维"],
)


# 根路径健康检查
@app.get("/", tags=["健康检查"], response_model=UnifiedResponse)
async def health_check():
    return unified_response(200, "服务运行正常", {"version": "v1"})


# 错误监控快照（批次0上线底座）：暴露 403/503/5xx/跨课程拒绝/任务失败计数
@app.get("/api/v1/health/error-monitor", tags=["健康检查"], response_model=UnifiedResponse)
async def error_monitor_snapshot():
    return unified_response(200, "错误监控快照", error_monitor.snapshot())


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
async def catch_all(path: str):
    if path.startswith("@vite/") or path.startswith("src/") or path.endswith((".js", ".css", ".html", ".ico", ".png", ".svg")):
        return JSONResponse(
            status_code=404,
            content=unified_response(404, "前端资源请通过 Vite 开发服务器访问 (localhost:5173)", None),
        )
    return JSONResponse(
        status_code=404,
        content=unified_response(404, f"接口不存在: /{path}", None),
    )
