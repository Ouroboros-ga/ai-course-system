
from pydantic_settings import BaseSettings, SettingsConfigDict
from enum import Enum
from typing import List

# 规范要求的角色枚举（RBAC权限核心）
class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"

# 全局配置类
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --------------------------
    # 签名校验核心配置（规范强制要求）
    # --------------------------
    STATIC_KEY: str = "dev-static-key-change-in-prod"
    SIGN_TIMEOUT_MINUTES: int = 5
    SIGN_ALGORITHM: str = "MD5"
    TIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # --------------------------
    # JWT身份认证配置
    # --------------------------
    JWT_SECRET_KEY: str = "dev-jwt-secret-key-change-in-prod-very-long"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # --------------------------
    # 安全白名单
    # --------------------------
    NO_AUTH_WHITELIST: List[str] = [
        "/api/v1/platform/syncCourse",
        "/api/v1/platform/syncUser",
        "/api/v1/user/login",
        "/docs",
        "/openapi.json",
        "/"
    ]

# 全局单例配置
settings = Settings()