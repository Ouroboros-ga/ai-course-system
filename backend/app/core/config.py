from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from enum import Enum
from typing import List

from app.core.feature_flags import LEGAL_VALUES, ALL_FLAGS, TEACHING_AGENT_MODES
from app.platform.retrieval_demo.mode import DEMO_RETRIEVAL_MODES


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    # Legacy read/code aliases. They serialize as the new `user` value and
    # must not be used for creating new records.
    STUDENT = "user"
    TEACHER = "user"


class LLMProvider(str, Enum):
    DOUBAO = "doubao"
    QWEN = "qwen"
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
    # Fernet key material for platform integration secrets. Set a dedicated
    # deployment secret in real environments; JWT_SECRET_KEY is only a
    # development fallback for backwards-compatible local prototypes.
    PLATFORM_CONFIG_ENCRYPTION_KEY: str = ""
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
    # Course preparation has a shorter, explicit stage budget than the
    # generic LLM client and a separate end-to-end budget for all stages.
    COURSE_BUILD_STAGE_TIMEOUT_SECONDS: int = 240
    COURSE_BUILD_TOTAL_TIMEOUT_SECONDS: int = 900
    PREP_SPARSE_STRUCTURE_PLAN: bool = True
    # A full-course structure pass can legitimately touch most titles.  Keep
    # enough completion room for the exceptional full plan while the sparse
    # schema/prompt keeps ordinary calls short.
    PREP_STRUCTURE_MAX_TOKENS: int = 12000
    PREP_SCRIPT_MAX_TOKENS: int = 4096
    PREP_SCRIPT_BATCH_SIZE: int = 5
    # Initial (first-draft) prep has its own bounded script budgets so it stays
    # independent from the incremental rewrite pipeline.  The initial pipeline
    # groups knowledge-point scripts into several requests (P0 chunking) and
    # uses a per-request completion budget; a single oversized knowledge point
    # falls back to its own larger budget instead of failing the whole draft.
    PREP_INITIAL_SCRIPT_BATCH_SIZE: int = 3
    PREP_INITIAL_SCRIPT_MAX_TOKENS: int = 4096
    PREP_INITIAL_SCRIPT_SINGLE_MAX_TOKENS: int = 12288
    # Initial evidence preparation is intentionally bounded independently of
    # the generic LLM settings. Parsed blocks are coalesced into stable units,
    # mapped in small requests, then reduced without resending the raw corpus.
    PREP_INITIAL_EVIDENCE_UNIT_TARGET_CHARS: int = 1500
    PREP_INITIAL_EVIDENCE_UNIT_MAX_CHARS: int = 2400
    PREP_INITIAL_EVIDENCE_TOTAL_MAX_CHARS: int = 600000
    PREP_INITIAL_EVIDENCE_MAX_UNITS: int = 1000
    PREP_INITIAL_EVIDENCE_MAP_TEXT_CHARS: int = 24000
    PREP_INITIAL_EVIDENCE_MAP_PAYLOAD_CHARS: int = 36000
    PREP_INITIAL_EVIDENCE_MAP_MAX_CHUNKS: int = 25
    PREP_INITIAL_EVIDENCE_CONCURRENCY: int = 2
    # Total Map+Reduce call budget for one course's evidence organization.
    # Intermediate Reduce levels now merge lean summaries (no examples/
    # exercises), which cut both per-call truncation and the number of calls;
    # 64 keeps headroom for a full-scale 25-chunk corpus without hiding
    # runaway loops behind an unbounded budget.
    PREP_INITIAL_EVIDENCE_MAX_ATTEMPTS: int = 64
    PREP_INITIAL_EVIDENCE_MAP_MAX_TOKENS: int = 4096
    PREP_INITIAL_EVIDENCE_MAP_RETRY_MAX_TOKENS: int = 8192
    PREP_INITIAL_EVIDENCE_REDUCE_MAX_TOKENS: int = 16384
    PREP_INITIAL_OUTLINE_MAX_TOKENS: int = 16384
    PREP_INITIAL_VERIFIER_MAX_TOKENS: int = 4096
    PREP_INITIAL_MAX_KNOWLEDGE_POINTS: int = 24
    PREP_INITIAL_MAX_OUTLINE_NODES: int = 64
    # Local-only, explicit debugging aid.  The per-course enable state and
    # captured prompts/responses are stored under this ignored directory; raw
    # model content never enters normal logs or durable diagnostics.
    PREP_LLM_DEBUG_CAPTURE_DIR: str = "./temp/prep-llm-debug"

    # --------------------------
    # Course Knowledge Bundle / GraphRAG / vector retrieval
    # --------------------------
    # GraphRAG is a durable teacher-side build pipeline.  It is never executed
    # on a learner request and a failed build never replaces the active bundle.
    KNOWLEDGE_BUNDLE_ENABLED: bool = True
    GRAPHRAG_ENABLED: bool = False
    GRAPHRAG_WORKER_PYTHON: str = ""
    GRAPHRAG_STORAGE_ROOT: str = "./media/knowledge_indexes"
    GRAPHRAG_COMPLETION_PROVIDER: str = ""
    GRAPHRAG_COMPLETION_MODEL: str = ""
    GRAPHRAG_COMPLETION_API_BASE: str = ""
    GRAPHRAG_COMPLETION_API_KEY: str = ""
    GRAPHRAG_EMBEDDING_PROVIDER: str = ""
    GRAPHRAG_EMBEDDING_MODEL: str = ""
    GRAPHRAG_EMBEDDING_API_BASE: str = ""
    GRAPHRAG_EMBEDDING_API_KEY: str = ""
    GRAPHRAG_EMBEDDING_DIMENSION: int = 0
    GRAPHRAG_EMBEDDING_BATCH_SIZE: int = 64
    GRAPHRAG_EMBEDDING_LOCAL_PATH: str = ""
    GRAPHRAG_EMBEDDING_MAX_LENGTH: int = 512
    GRAPHRAG_EMBEDDING_QUERY_INSTRUCTION: str = ""
    GRAPHRAG_PROMPT_POLICY: str = "edu-graph-graphrag/2.0-zh"
    GRAPHRAG_MAX_GLEANINGS: int = 1
    GRAPHRAG_MAX_RETRIES: int = 2
    GRAPHRAG_RUN_TIMEOUT_SECONDS: int = 1800
    GRAPHRAG_MAX_INPUT_TOKENS: int = 0
    # USD-based preflight estimate. This is not a provider-side billing cap.
    GRAPHRAG_ESTIMATED_INPUT_COST_USD_PER_MILLION_TOKENS: float = 30.0
    GRAPHRAG_MAX_ESTIMATED_COST_USD: float = 0.0
    # Backward-compatible alias for existing deployments. Prefer the explicit
    # *_USD setting above; when it is zero this legacy value remains effective.
    GRAPHRAG_MAX_ESTIMATED_COST: float = 0.0
    VECTOR_STORE_PROVIDER: str = "lancedb"
    VECTOR_STORE_ROOT: str = "./media/knowledge_indexes"
    VECTOR_SEARCH_TOP_K: int = 20
    VECTOR_RESULT_TOP_K: int = 6
    # Agent composition may opt into the production read-only bundle adapter
    # without changing the workflow graph under active refactoring.
    TEACHING_AGENT_KNOWLEDGE_PROVIDER: str = "demo"

    # 豆包配置
    DOUBAO_API_KEY: str = ""
    DOUBAO_ENDPOINT_ID: str = ""

    # 通义千问配置
    QWEN_API_KEY: str = ""
    QWEN_MODEL_NAME: str = "qwen-turbo"

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
    MEDIA_STORAGE_PATH: str = "./media"

    # --------------------------
    # 老师素材存储路径配置
    # --------------------------
    ASSET_STORAGE_PATH: str = "./teacher_assets"
    MAX_VIDEO_ASSET_SIZE_MB: int = 200
    MAX_AUDIO_ASSET_SIZE_MB: int = 50

    # --------------------------
    # 阶段8 对象存储抽象配置
    # 后端 local / oss；签名密钥用于受权限保护的媒体 URL
    # --------------------------
    OBJECT_STORAGE_BACKEND: str = "local"
    OBJECT_STORAGE_SIGN_KEY: str = ""
    # S3-compatible object storage (MinIO / cloud object-storage endpoint).
    # An endpoint is required when OBJECT_STORAGE_BACKEND is s3|minio|oss; the
    # application never silently falls back to the local filesystem.
    OBJECT_STORAGE_ENDPOINT: str = ""
    OBJECT_STORAGE_REGION: str = "us-east-1"
    OBJECT_STORAGE_BUCKET: str = ""
    OBJECT_STORAGE_ACCESS_KEY_ID: str = ""
    OBJECT_STORAGE_SECRET_ACCESS_KEY: str = ""
    OBJECT_STORAGE_SESSION_TOKEN: str = ""
    OBJECT_STORAGE_ADDRESSING_STYLE: str = "path"
    OBJECT_STORAGE_PRESIGN_EXPIRES_SECONDS: int = 900
    OBJECT_STORAGE_ALLOW_DEMO_LOCAL_FALLBACK: bool = False
    # 可恢复对象存储迁移账本持久化路径（M5）
    # 约束来源: "Object storage migration must implement resumable task ledger
    # with per-object migration status and byte SHA verification"
    OBJECT_STORAGE_MIGRATION_LEDGER_PATH: str = "./data/object_migration_ledger.json"
    # 单次迁移最大重试次数；超过则标记 failed 不再自动重试，需人工介入
    OBJECT_STORAGE_MIGRATION_MAX_ATTEMPTS: int = 3
    MEDIA_UPLOAD_MAX_SIZE_MB: int = 500
    AVATAR_PORTRAIT_VIDEO_MAX_MB: int = 200
    AVATAR_PORTRAIT_VIDEO_MAX_DURATION_MS: int = 60_000
    AVATAR_VOICE_SAMPLE_MAX_MB: int = 50

    # --------------------------
    # 阶段8 M2 讯飞在线 TTS 配置
    # 密钥只留在服务端；自动化测试不调用真实讯飞
    # --------------------------
    # Stage 8 is fail-closed by default.  Local demos must explicitly set
    # MEDIA_DEMO_MODE=true; formal operation must explicitly select doubao.
    MEDIA_DEMO_MODE: bool = False
    STAGE8_TTS_PROVIDER: str = ""
    ALLOW_DEMO_PROVIDERS: bool = False
    XFYUN_TTS_APP_ID: str = ""
    XFYUN_TTS_API_KEY: str = ""
    XFYUN_TTS_API_SECRET: str = ""
    XFYUN_TTS_DEFAULT_VCN: str = "xiaoyan"
    XFYUN_TTS_SPEED: int = 50
    XFYUN_TTS_VOLUME: int = 50
    XFYUN_TTS_PITCH: int = 50
    XFYUN_TTS_SAMPLE_RATE: int = 16000
    XFYUN_TTS_AUDIO_ENCODING: str = "lame"  # lame=mp3, speex-wb
    XFYUN_TTS_WS_URL: str = "wss://tts-api.xfyun.cn/v2/tts"
    XFYUN_TTS_CONNECT_TIMEOUT_MS: int = 10000
    XFYUN_TTS_READ_TIMEOUT_MS: int = 30000

    # 豆包语音合成 2.0（v3 双向 WebSocket）。仅由 Media Worker 使用，
    # API Key 绝不进入前端、日志、测试 fixture 或发布快照。
    VOLCENGINE_DOUBAO_TTS_WS_URL: str = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    VOLCENGINE_DOUBAO_TTS_API_KEY: str = ""
    VOLCENGINE_DOUBAO_TTS_RESOURCE_ID: str = ""
    VOLCENGINE_DOUBAO_TTS_SPEAKER: str = ""
    VOLCENGINE_DOUBAO_TTS_FORMAT: str = "mp3"
    VOLCENGINE_DOUBAO_TTS_SAMPLE_RATE: int = 24000
    VOLCENGINE_DOUBAO_TTS_ENABLE_SUBTITLE: bool = True
    VOLCENGINE_DOUBAO_TTS_CONNECT_TIMEOUT_SECONDS: int = 15
    VOLCENGINE_DOUBAO_TTS_READ_TIMEOUT_SECONDS: int = 90

    # --------------------------
    # 阶段8 M2 TTS 任务重试与限额
    # --------------------------
    TTS_MAX_RETRY_ATTEMPTS: int = 3
    TTS_RATE_LIMIT_PER_MINUTE: int = 30
    TTS_RATE_LIMIT_BURST: int = 5
    TTS_MAX_SCRIPT_BYTES: int = 8000

    # P4 批量媒体建设。前端只能展示计划，所有限制均由服务端重新计算。
    MEDIA_BATCH_MAX_NODES: int = 20
    MEDIA_BATCH_MAX_BILLABLE_CHARS: int = 10_000
    MEDIA_TTS_MAX_CONCURRENT_PER_PROVIDER: int = 2

    # --------------------------
    # 阶段8 M5 数字人 Provider 开关与健康检查
    # --------------------------
    STAGE8_DH_PROVIDER: str = "fake"
    DH_PROVIDER_FALLBACK_ON_FAILURE: bool = True
    DH_HEALTH_CHECK_INTERVAL_S: int = 60

    # --------------------------
    # 阶段8 M4 DH_live_mini 引擎配置
    # DH_live 离线视频合成在 Windows 上更完整；资产预处理由独立 Windows Worker 完成
    # 自动化测试不调用真实引擎，必须通过环境变量显式启用
    # --------------------------
    DHLIVE_ENGINE_BINARY: str = ""           # 引擎可执行文件绝对路径；空表示未配置
    DHLIVE_WORKER_HOST: str = "127.0.0.1"    # 独立 Worker 监听地址
    DHLIVE_WORKER_PORT: int = 0              # 0 表示未启用 Worker；非零则通过 HTTP 调用
    DHLIVE_WORKER_TIMEOUT_S: int = 120       # 单次预处理超时
    DHLIVE_DEFAULT_FPS: int = 25             # 默认帧率，必须以实际测试报告为准
    DHLIVE_DEFAULT_RESOLUTION: str = "512x512"
    DHLIVE_STRICT_REPORT: bool = True        # 严格模式：无实际测试报告时不返回 healthy=True

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
    # Formal student-answer promotion is independent from the legacy shadow
    # flag and must also pass the per-course Evidence capability gate.
    R2_STUDENT_ANSWER_ENABLED: bool = False

    # --------------------------
    # G3: Judge0 代码沙箱配置
    # --------------------------
    JUDGE0_ENABLED: bool = False
    JUDGE0_API_URL: str = "http://127.0.0.1:2358"
    JUDGE0_AUTHN_HEADER: str = "X-Auth-Token"
    JUDGE0_AUTHN_TOKEN: str = ""
    JUDGE0_AUTHZ_HEADER: str = "X-Auth-User"
    JUDGE0_AUTHZ_TOKEN: str = ""
    JUDGE0_DEFAULT_CPU_TIME_LIMIT: int = 5
    JUDGE0_DEFAULT_MEMORY_LIMIT: int = 128000
    JUDGE0_DEFAULT_WALL_TIME_LIMIT: int = 10
    JUDGE0_DEFAULT_MAX_PROCESSES: int = 30
    JUDGE0_DEFAULT_MAX_FILE_SIZE: int = 1024
    JUDGE0_QUEUE_TIMEOUT: int = 30

    # --------------------------
    # Step 2: 独立 PaddleOCR 服务配置
    # PaddleOCR 运行在独立容器（deploy/paddleocr/），主后端通过 DocumentOcrPort
    # (PaddleOcrHttpAdapter) 调用，不在主后端安装 paddle。
    # PADDLEOCR_URL 为空时 OCR 端口 fail-closed（UnavailableOcrPort），
    # OCR 相关任务以 OCR_SERVICE_UNAVAILABLE 失败并可重试，不伪造输出。
    # --------------------------
    PADDLEOCR_URL: str = "http://127.0.0.1:8090"
    PADDLEOCR_REQUIRED_FOR_PDF: bool = True
    PADDLEOCR_TIMEOUT_S: int = 300
    PADDLEOCR_MAX_PAGES: int = 50

    # --------------------------
    # 服务间鉴权（Quiz/Judge0/CodingAgent 写正式证据等内部调用）
    # --------------------------
    INTERNAL_SERVICE_TOKEN: str = ""
    # 允许写入正式学习证据的内部来源白名单
    FORMAL_EVIDENCE_SOURCES: str = "quiz,judge0,codingagent,teacher_manual"

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
        # SEC-02: 签名/JWT 密钥缺失时禁止静默回退到 dev 默认值，否则攻击者可用
        # 已知默认值伪造任意 JWT（任意 sub/role）并重算请求签名。缺失即拒绝启动。
        for name, default in {
            "STATIC_KEY": "dev-static-key-change-in-prod",
            "JWT_SECRET_KEY": "dev-jwt-secret-key-change-in-prod-very-long",
        }.items():
            if not getattr(self, name) or getattr(self, name) == default:
                raise ValueError(
                    f"{name} 未配置或仍在使用 dev 默认值，拒绝启动。"
                    f"请通过 .env 或环境变量注入强随机密钥"
                    f"（生成示例：python -c \"import secrets; print(secrets.token_urlsafe(48))\"）。"
                    f"注意：.env.example 中的 'your-*-here' 占位值同样不安全，部署前必须替换。"
                )
        return self


settings = Settings()
