from .config import settings, Settings, UserRole

# 导出安全工具与依赖
from .security import (
    # 全局签名校验依赖
    verify_request_signature,
    # 身份认证依赖
    get_current_user,
    # 预定义权限依赖
    teacher_only,
    student_only,
    teacher_student_allowed,
    admin_only,
    # 权限依赖工厂
    role_required,
    # 密码工具
    verify_password,
    get_password_hash,
    # JWT工具
    create_access_token,
)

# 导出异常处理与统一响应
from .exceptions import unified_response, BusinessException

# 明确导出列表（可选，用于规范 `from app.core import *` 的行为）
__all__ = [
    # 配置
    "settings",
    "Settings",
    "UserRole",
    # 安全
    "verify_request_signature",
    "get_current_user",
    "teacher_only",
    "student_only",
    "teacher_student_allowed",
    "admin_only",
    "role_required",
    "verify_password",
    "get_password_hash",
    "create_access_token",
    # 异常与响应
    "unified_response",
    "BusinessException",
]
