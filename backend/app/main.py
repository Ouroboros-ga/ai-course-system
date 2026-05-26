# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.signature_middleware import SignatureMiddleware
from app.core.exceptions import global_exception_handler, unified_response
from app.models.database import create_tables


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
)
from app.schemas import UnifiedResponse

# 创建数据库表
create_tables()

# 创建FastAPI实例
app = FastAPI(
    title="超星AI互动智课系统",
    description="符合超星开放API设计规范的后端服务",
    version="v1",
)

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

# F1-F7 功能模块路由（2026-05-26 补全）
app.include_router(asset.router, prefix="/api/v1/asset", tags=["F1-素材管理"])
app.include_router(mapping.router, prefix="/api/v1/mapping", tags=["F2/F5-映射引擎"])
app.include_router(player.router, prefix="/api/v1/player", tags=["F6-分屏播放器"])
app.include_router(ppt_generation.router, prefix="/api/v1/ppt", tags=["F3-PPT生成"])
app.include_router(video_generation.router, prefix="/api/v1/video-gen", tags=["F4/F5-视频生成"])
app.include_router(video.router, prefix="/api/v1/video", tags=["视频功能"])
app.include_router(platform.router, prefix="/api/v1/platform", tags=["平台管理"])

# 按照接口文档规范，/chat/file/upload 也映射到文档上传处理
app.include_router(document.router, prefix="/api/v1/chat/file", tags=["聊天模块"])


# 根路径健康检查
@app.get("/", tags=["健康检查"], response_model=UnifiedResponse)
async def health_check():
    return unified_response(200, "服务运行正常", {"version": "v1"})
