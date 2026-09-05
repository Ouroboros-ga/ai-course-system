from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEXUS_", extra="ignore")

    # LLM（DeepSeek，OpenAI 兼容端点）
    deepseek_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"

    # Web Search 主通道（SearXNG，部署于 47.99.97.154，服务器侧 127.0.0.1:8888）
    searxng_url: str = ""
    ddgs_enabled: bool = True

    # Quick Reproduction Worker（未配置时 fail-closed）
    repro_worker_url: str = ""
    # Worker 的 Bearer 令牌（REPRO_WORKER_TOKEN 对应项；双方都配置才启用认证）
    repro_worker_token: str = ""

    # M2 知识接入：Runtime → Backend 内部检索端点（课程资料 / CS 知识库）。
    # 未配置时两工具 fail-closed 返回 UNAVAILABLE，不假造检索结果。
    backend_internal_url: str = ""
    backend_internal_token: str = ""

    # 会话持久化（P1-C）：PostgresSaver，独立 schema，不混入业务表。
    # 留空则回退 InMemorySaver（本地开发/测试，无需本地启动 PG）。
    postgres_dsn: str = ""
    postgres_schema: str = "nexus_checkpoints"
    # Retention：未活跃会话 TTL（天），由服务器 cron 清理，本地不执行。
    retention_days: int = 30

    # Compact（P1-C）：DeepAgents 原生 SummarizationMiddleware。
    # DeepSeek 无 max_input_tokens profile，fraction 触发不可靠，故用显式
    # token/message 阈值（默认 ~64k 窗口的 78% 触发，保留近期 20 条）。
    summary_trigger_tokens: int = 50000
    summary_keep_messages: int = 20

    # 服务
    host: str = "127.0.0.1"
    port: int = 8300
    api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
