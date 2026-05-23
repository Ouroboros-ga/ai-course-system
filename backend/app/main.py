# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.signature_middleware import SignatureMiddleware
from app.core.exceptions import global_exception_handler, unified_response
from app.models.database import create_tables


# 导入路由
from app.api.v1.endpoints import user, document, chat, progress, video, asset, mapping, ppt_generation, video_generation
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
app.include_router(video.router, prefix="/api/v1/video", tags=["视频服务"])
app.include_router(asset.router, prefix="/api/v1/assets", tags=["素材管理"])
app.include_router(mapping.router, prefix="/api/v1/mapping", tags=["知识点映射"])
app.include_router(ppt_generation.router, prefix="/api/v1/ppt-generation", tags=["AI生成PPT"])
app.include_router(video_generation.router, prefix="/api/v1/video-generation", tags=["视频生成"])
# 按照接口文档规范，/chat/file/upload 也映射到文档上传处理
app.include_router(document.router, prefix="/api/v1/chat/file", tags=["聊天模块"])


# 根路径健康检查
@app.get("/", tags=["健康检查"], response_model=UnifiedResponse)
async def health_check():
    return unified_response(200, "服务运行正常", {"version": "v1"})
