# app/api/v1/__init__.py
"""
API v1 版本路由
导出所有 v1 版本的子路由，供 main.py 统一注册
"""

from fastapi import APIRouter
from .endpoints import (
    user,
    # smart_course,
    # qa,
    # progress,
    # common,
    # platform
)

# 创建 v1 主路由
api_router = APIRouter(prefix="/api/v1")

# 注册子路由
api_router.include_router(user.router, prefix="/user", tags=["用户模块"])
# api_router.include_router(smart_course.router, prefix="/lesson", tags=["智课智能生成模块"])
# api_router.include_router(qa.router, prefix="/qa", tags=["多模态实时问答模块"])
# api_router.include_router(progress.router, prefix="/progress", tags=["学习进度智能适配模块"])
# api_router.include_router(common.router, prefix="/common", tags=["通用接口"])
# api_router.include_router(platform.router, prefix="/platform", tags=["平台对接预留接口"])

__all__ = ["api_router"]
