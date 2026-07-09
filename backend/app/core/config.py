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
    VOLCENGINE = "volcengine"


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
    LLM_MAX_TOKENS: int = 8192
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT: int = 180

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

    # 火山引擎TTS配置
    VOLCENGINE_TTS_APP_ID: str = ""
    VOLCENGINE_TTS_ACCESS_TOKEN: str = ""
    VOLCENGINE_TTS_SECRET_KEY: str = ""

    # 火山引擎声音复刻配置（豆包语音声音复刻API）
    VOLCENGINE_VOICE_CLONE_API_KEY: str = ""  # x-api-key，用于声音复刻合成
    VOLCENGINE_VOICE_CLONE_MODEL_TYPE: int = 4  # 1=ICL1.0, 2=DiT标准, 3=DiT还原, 4=ICL2.0(默认)

    # --------------------------
    # 数字人视频生成API配置（Gradio）
    # --------------------------
    DIGITAL_HUMAN_API_URL: str = "http://localhost:7860/"  # 数字人Gradio服务地址
    DIGITAL_HUMAN_PROVIDER: str = "digital_human"  # digital_human | duix
    DUIX_BASE_URL: str = "http://127.0.0.1:8383"
    DIGITAL_HUMAN_MIN_RESOLUTION: int = 2  # 原比例缩小倍数
    DIGITAL_HUMAN_IF_RES: bool = False  # 是否强制缩小分辨率
    DIGITAL_HUMAN_STEPS: int = 4  # 处理批次，越大越快但可能爆显存

    # --------------------------
    # 安全白名单
    # --------------------------
    NO_AUTH_WHITELIST: List[str] = [
        "/api/v1/platform/syncCourse",
        "/api/v1/platform/syncUser",
        "/api/v1/user/login",
        "/api/v1/user/register",
        "/docs",
        "/openapi.json",
        "/",
    ]

    # --------------------------
    # 媒体资源白名单（跳过签名验证，但仍需JWT认证）
    # 用于 <img> / <audio> 等浏览器直接发起的请求
    # --------------------------
    MEDIA_RESOURCE_PATHS: List[str] = [
        "/api/v1/document/course/",
        "/api/v1/document/audio/",
    ]

    # --------------------------
    # 视频文件存储路径配置
    # --------------------------
    VIDEO_STORAGE_PATH: str = "./videos"
    TEMP_VIDEO_STORAGE_PATH: str = "./temp_videos"

    # --------------------------
    # 老师素材存储路径配置
    # --------------------------
    ASSET_STORAGE_PATH: str = "./teacher_assets"
    MAX_VIDEO_ASSET_SIZE_MB: int = 200
    MAX_AUDIO_ASSET_SIZE_MB: int = 50

    # --------------------------
    # 科大讯飞PPT生成API配置
    # --------------------------
    XFYUN_PPT_APP_ID: str = ""
    XFYUN_PPT_API_SECRET: str = ""
    XFYUN_PPT_DEFAULT_TEMPLATE_ID: str = ""


settings = Settings()
