# app/main.py
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.signature_middleware import SignatureMiddleware
from app.core.exceptions import global_exception_handler, unified_response
from app.models.database import create_tables
from app.common.db_migrator import run_migrations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.common.dependency_checker import run_dependency_check


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def _startup_side_effects_disabled() -> bool:
    return _env_flag("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS")


def run_startup_side_effects():
    dep_report = run_dependency_check(auto_install=True)
    if not dep_report["python_ok"]:
        logger.error("必需的Python依赖缺失，请手动安装后重启服务")
    if dep_report["python_installed"]:
        logger.info(f"自动安装的Python包: {', '.join(dep_report['python_installed'])}")

    create_tables()
    run_migrations()
    return dep_report


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
    note,               # 笔记模块
    dashboard,          # 首页与课程概览聚合
    confirmation,       # 教师确认持久化
    citation,           # 引用稳定定位
    feedback,           # 向教师反馈通道
    course_access,
    question_bank,      # Phase B 题库管理
    question_source_mapping,  # Phase B 题源映射
)
from app.schemas import UnifiedResponse

if startup_side_effects_skipped:
    logger.info("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS enabled; startup dependency checks, table creation and migrations are skipped.")
else:
    startup_dependency_report = run_startup_side_effects()

# 创建FastAPI实例
app = FastAPI(
    title="超星AI互动智课系统",
    description="符合超星开放API设计规范的后端服务",
    version="v1",
)
app.state.startup_side_effects_skipped = startup_side_effects_skipped
app.state.startup_dependency_report = startup_dependency_report

# P1: opt-in TeachingAgent runtime injection. Default TEACHING_AGENT_MODE=
# disabled -> no injection -> /api/v1/teaching-agent/respond stays 503. Only
# injects when enabled AND an approved KG-MEST Shadow report is present AND
# LLM is configured. Never blocks startup; see bootstrap.py.
from app.platform.agents.bootstrap import bootstrap_teaching_agent
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

# 注册全局异常处理
app.add_exception_handler(HTTPException, global_exception_handler)

# 注册路由
app.include_router(user.router, prefix="/api/v1/user", tags=["用户模块"])
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


# 根路径健康检查
@app.get("/", tags=["健康检查"], response_model=UnifiedResponse)
async def health_check():
    return unified_response(200, "服务运行正常", {"version": "v1"})


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(path: str):
    if path.startswith("@vite/") or path.startswith("src/") or path.endswith((".js", ".css", ".html", ".ico", ".png", ".svg")):
        return unified_response(404, "前端资源请通过 Vite 开发服务器访问 (localhost:5173)", None)
    return unified_response(404, f"接口不存在: /{path}", None)
