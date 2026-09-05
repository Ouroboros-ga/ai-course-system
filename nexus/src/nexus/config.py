from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEXUS_", extra="ignore")

    # LLM（DeepSeek，OpenAI 兼容端点）
    deepseek_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"
    # 模型选择（模型网关 P0）：除默认模型外的可选模型 id，逗号分隔。
    # 前端下拉选项即此清单；新增模型只改此处（+ 重启），前端零改动。
    # 同一 OpenAI 兼容端点下的模型 id；跨供应商端点属后续扩展，不在本批。
    llm_models: str = ""

    # Web Search 主通道（SearXNG，部署于 47.99.97.154，服务器侧 127.0.0.1:8888）
    searxng_url: str = ""
    ddgs_enabled: bool = True

    # Quick Reproduction Worker（未配置时 fail-closed）
    repro_worker_url: str = ""
    # Worker 的 Bearer 令牌（REPRO_WORKER_TOKEN 对应项；双方都配置才启用认证）
    repro_worker_token: str = ""

    # NX-G2 执行审批：提案有效期（秒）。过期票据一律失效，需重新提案。
    approval_ttl_s: int = 900

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

    # NX-G3：依赖健康探针 TTL（秒）。/health 返回的 checks 为"带检查时间+
    # 有效期"的探测快照，不是实时断言；过期由消费方判 unknown。
    health_probe_ttl_s: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


def llm_default_model(settings: Settings | None = None) -> str:
    """默认模型（请求缺 model 字段时的安全默认）。"""
    settings = settings or get_settings()
    return (settings.llm_model or "").strip() or "deepseek-chat"


def llm_available_models(settings: Settings | None = None) -> list[str]:
    """服务端模型 allowlist（唯一真相源）：默认模型打头，去重保序。"""
    settings = settings or get_settings()
    seen: list[str] = []
    candidates = [llm_default_model(settings)]
    candidates.extend(m.strip() for m in (settings.llm_models or "").split(","))
    for raw in candidates:
        if raw and raw not in seen:
            seen.append(raw)
    return seen


def llm_models_manifest(settings: Settings | None = None) -> dict:
    """前端模型下拉的数据源：[{id, label, default}]。label 暂与 id 相同，
    后续多供应商时再扩展 provider/备注字段，不改契约形状。"""
    settings = settings or get_settings()
    default = llm_default_model(settings)
    return {
        "default": default,
        "available": [
            {"id": mid, "label": mid, "default": mid == default}
            for mid in llm_available_models(settings)
        ],
    }
