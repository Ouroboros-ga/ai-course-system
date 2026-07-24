from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from enum import Enum
from typing import List, Optional

from app.core.feature_flags import LEGAL_VALUES, ALL_FLAGS, TEACHING_AGENT_MODES
from app.platform.retrieval_demo.mode import DEMO_RETRIEVAL_MODES


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

    # --------------------------
    # Product 1 V2 Shadow Feature Flags (G3A, ADR-0006)
    # --------------------------
    # All flags default to V1/disabled. G3 accepts ONLY v1_only/v2_shadow
    # (pipeline flags) or disabled/shadow (toggle flags). Any other value
    # (including G6-reserved v2_preferred_with_v1_fallback / v2_only, and
    # typos like v2_shdaow) is a CONFIGURATION ERROR and fails fast at
    # Settings construction (startup fail-fast) via _validate_feature_flags.
    # Shadow RUNTIME errors (valid config, V2 execution fails) are handled
    # separately as business-level fail-closed in app.core.feature_flags.
    DOCUMENT_PIPELINE_VERSION: str = "v1_only"
    KNOWLEDGE_GRAPH_PIPELINE_VERSION: str = "v1_only"
    DOCUMENT_KG_RUNTIME_MODE: str = "v1_only"
    EVIDENCE_CITATION_MODE: str = "v1_only"
    LEARNING_EVENT_MODE: str = "v1_only"
    STUDENT_MEMORY_MODE: str = "disabled"
    SAFETY_GOVERNANCE_MODE: str = "disabled"

    # Shadow-1 user-visible retrieval demonstration.  This is intentionally
    # separate from all Product-1 V1/V2 pipeline flags: it never promotes or
    # reroutes the V1 request path.  Visible modes are additionally restricted
    # at runtime to development/demo/test environments by DemoModeState.
    DEMO_RETRIEVAL_MODE: str = "v1_only"

    # TeachingAgent enable flag (independent of the 7-flag Product 1 DAG;
    # see feature_flags.TEACHING_AGENT_MODES). Default disabled = the
    # /api/v1/teaching-agent/respond endpoint stays 503 (runtime not injected).
    TEACHING_AGENT_MODE: str = "disabled"
    DEMO_RETRIEVAL_ENVIRONMENT: str = "development"

    # --------------------------
    # G3: Judge0 代码沙箱配置
    # --------------------------
    JUDGE0_ENABLED: bool = False
    JUDGE0_API_URL: str = "http://127.0.0.1:2358"
    JUDGE0_AUTHN_TOKEN: str = ""
    JUDGE0_DEFAULT_CPU_TIME_LIMIT: int = 5
    JUDGE0_DEFAULT_MEMORY_LIMIT: int = 128000
    JUDGE0_DEFAULT_WALL_TIME_LIMIT: int = 10
    JUDGE0_DEFAULT_MAX_PROCESSES: int = 30
    JUDGE0_DEFAULT_MAX_FILE_SIZE: int = 1024
    JUDGE0_QUEUE_TIMEOUT: int = 30

    @model_validator(mode="after")
    def _validate_feature_flags(self):
        """Startup fail-fast: every Product 1 flag must be a legal G3 value.

        Raises ValueError (-> pydantic ValidationError -> Settings() raises)
        for any illegal value, so the application refuses to start. This
        intentionally does NOT silently fall back, so misconfiguration is
        surfaced immediately rather than masked as a running-but-no-shadow
        state.
        """
        for flag in ALL_FLAGS:
            legal = LEGAL_VALUES[flag]
            value = getattr(self, flag)
            if value not in legal:
                raise ValueError(
                    f"Invalid {flag}={value!r}; legal G3 values: {list(legal)}. "
                    f"v2_preferred_with_v1_fallback and v2_only are reserved for G6 "
                    f"and not legal in G3."
                )
        if self.DEMO_RETRIEVAL_MODE not in DEMO_RETRIEVAL_MODES:
            raise ValueError(
                f"Invalid DEMO_RETRIEVAL_MODE={self.DEMO_RETRIEVAL_MODE!r}; "
                f"legal values: {list(DEMO_RETRIEVAL_MODES)}"
            )
        if self.TEACHING_AGENT_MODE not in TEACHING_AGENT_MODES:
            raise ValueError(
                f"Invalid TEACHING_AGENT_MODE={self.TEACHING_AGENT_MODE!r}; "
                f"legal values: {list(TEACHING_AGENT_MODES)}"
            )
        return self


settings = Settings()
