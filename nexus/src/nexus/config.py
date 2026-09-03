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

    # 服务
    host: str = "127.0.0.1"
    port: int = 8300
    api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
