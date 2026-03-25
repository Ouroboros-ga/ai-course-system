from pydantic_settings import BaseSettings, SettingsConfigDict
from enum import Enum
from typing import List, Optional


class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class LLMProvider(str, Enum):
    DOUBAO = "doubao"
    QWEN = "qwen"
    WENXIN = "wenxin"
    OPENAI = "openai"


class TTSProvider(str, Enum):
    ALIYUN = "aliyun"
    TENCENT = "tencent"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

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
    # 大模型API配置
    # --------------------------
    LLM_PROVIDER: str = "doubao"
    LLM_API_KEY: str = ""
    LLM_API_BASE: str = ""
    LLM_MODEL_NAME: str = ""
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT: int = 60

    # 豆包配置
    DOUBAO_API_KEY: str = ""
    DOUBAO_ENDPOINT_ID: str = ""

    # 通义千问配置
    QWEN_API_KEY: str = ""
    QWEN_MODEL_NAME: str = "qwen-turbo"

    # 文心一言配置
    WENXIN_API_KEY: str = ""
    WENXIN_SECRET_KEY: str = ""

    # --------------------------
    # 语音合成API配置
    # --------------------------
    TTS_PROVIDER: str = "aliyun"
    TTS_API_KEY: str = ""
    TTS_API_SECRET: str = ""
    TTS_APP_ID: str = ""
    TTS_VOICE: str = ""
    TTS_SAMPLE_RATE: int = 16000
    TTS_FORMAT: str = "mp3"

    # 阿里云TTS配置
    ALIYUN_TTS_ACCESS_KEY_ID: str = ""
    ALIYUN_TTS_ACCESS_KEY_SECRET: str = ""
    ALIYUN_TTS_APP_KEY: str = ""

    # 腾讯云TTS配置
    TENCENT_TTS_SECRET_ID: str = ""
    TENCENT_TTS_SECRET_KEY: str = ""
    TENCENT_TTS_APP_ID: str = ""

    # --------------------------
    # 安全白名单
    # --------------------------
    NO_AUTH_WHITELIST: List[str] = [
        "/api/v1/platform/syncCourse",
        "/api/v1/platform/syncUser",
        "/api/v1/user/login",
        "/docs",
        "/openapi.json",
        "/",
    ]


settings = Settings()
