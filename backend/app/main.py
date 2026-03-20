# app/main.py
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.security import verify_request_signature
from app.core.exceptions import global_exception_handler, unified_response


# 导入示例路由TODO
from app.api.v1.endpoints import user
from app.schemas import UnifiedResponse

# 创建FastAPI实例（全局注册签名校验依赖）
app = FastAPI(
    title="超星AI互动智课系统",
    description="符合超星开放API设计规范的后端服务",
    version="v1",
    dependencies=[Depends(verify_request_signature)]
)

# 注册全局异常处理
app.add_exception_handler(HTTPException, global_exception_handler)

# CORS跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(user.router, prefix="/api/v1/user", tags=["用户模块"])

# 根路径健康检查
@app.get("/", tags=["健康检查"], response_model=UnifiedResponse)
async def health_check():
    return unified_response(200, "服务运行正常", {"version": "v1"})