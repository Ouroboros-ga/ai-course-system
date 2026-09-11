from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEXUS_", extra="ignore")

    # LLM（DeepSeek，OpenAI 兼容端点）
    deepseek_api_key: str = ""
    # 官方 model 可选值：[deepseek-flash, deepseek-v4-pro]（2026-09-11 官方文档）。
    # 旧 ID deepseek-chat / deepseek-reasoner 已于北京时间 2026-07-24 23:59 弃用，
    # 二者分别对应 deepseek-v4-flash 的非思考与思考模式。
    llm_model: str = "deepseek-flash"
    llm_base_url: str = "https://api.deepseek.com/v1"
    # 单次生成上限（token）。官方范围 1~384K（393216）；未设置时非思考模式默认 8K、
    # 思考模式默认 64K（effort=max 时 128K）。显式写出，避免依赖随版本漂移的隐式默认。
    # 取值 <= 0 表示不发送该字段（回落服务端默认）。
    llm_max_tokens: int = 65536
    # 思考模式（官方默认开启，effort 默认 high）。取值 "enabled" / "disabled"。
    # 此处为**默认值**；单次请求可由前端思考开关覆盖（ChatRequest.thinking →
    # build_agent(thinking=...) → apply_thinking_mode 改写 extra_body）。
    #
    # 为什么可以开启（2026-09-11 已修，见 docs/phase1/2026-09-11_Nexus研究模式
    # 输出字数偏少_诊断与修复建议.md）：官方要求携带 tools 的请求必须在后续所有
    # 轮次完整回传 reasoning_content，否则 400；而 langchain_openai.ChatOpenAI
    # 明示「不提取也不保留」该字段。已改用 langchain-deepseek 的 ChatDeepSeek，
    # 并由 agent._NexusChatDeepSeek._get_request_payload 补齐发送侧回传，
    # 多轮工具链不再 400（实测：第二轮的 assistant 消息带 reasoning_content）。
    #
    # 另注：思考模式下 temperature 不生效（官方明示），reasoning_effort 为
    # 顶层参数，仅 enabled 时发送。
    llm_thinking: str = "enabled"
    # 思考强度（仅 llm_thinking="enabled" 时发送）：low / high / max。
    llm_reasoning_effort: str = "high"
    # 研究报告最小篇幅门禁（字符数；0 = 不校验）。
    # 在 write_research_report 的**写入点**校验：过短返回可修复错误
    # REPORT_TOO_SHORT（模型按 NX-Report 六节结构补足后重试），而不是等到交付核对。
    # 为什么不放 delivery_checklist：task 记录里只有 report_artifact_id，没有正文长度，
    # 加列需 DB 迁移；写入点能直接拿到 body，且能更早拦住。
    report_min_chars: int = 1500
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

    # T4 自主实验执行控制服务（deploy/repro-runtime；独立内网服务）。
    # 未配置时自主执行核 fail-closed（run 落 failed，不静默 running）。
    repro_control_url: str = ""
    repro_control_token: str = ""

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
    # token/message 阈值。V4 上下文为 1M，故取 20% 处触发（原注释按 ~64k
    # 窗口写 78%，属 V3.2 时代的过时口径，已于 2026-09-11 更正）。
    summary_trigger_tokens: int = 200000
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
    return (settings.llm_model or "").strip() or "deepseek-flash"


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
