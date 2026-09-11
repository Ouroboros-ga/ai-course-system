import pytest

from nexus.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_SEARXNG_URL", raising=False)
    monkeypatch.delenv("NEXUS_DDGS_ENABLED", raising=False)
    monkeypatch.delenv("NEXUS_REPRO_WORKER_URL", raising=False)
    monkeypatch.delenv("NEXUS_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("NEXUS_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("NEXUS_POSTGRES_SCHEMA", raising=False)
    monkeypatch.delenv("NEXUS_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NEXUS_SUMMARY_TRIGGER_TOKENS", raising=False)
    monkeypatch.delenv("NEXUS_SUMMARY_KEEP_MESSAGES", raising=False)
    monkeypatch.delenv("NEXUS_LLM_MODEL", raising=False)
    monkeypatch.delenv("NEXUS_LLM_MODELS", raising=False)
    monkeypatch.delenv("NEXUS_LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("NEXUS_LLM_THINKING", raising=False)
    monkeypatch.delenv("NEXUS_LLM_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("NEXUS_APPROVAL_TTL_S", raising=False)
    monkeypatch.delenv("NEXUS_HEALTH_PROBE_TTL_S", raising=False)
    # 报告最小篇幅门禁（report_min_chars）在测试中默认关闭：多数用例的
    # body_markdown 是短样例，关注点是引用渲染 / 落盘 / fail-closed 语义，
    # 而非篇幅。需要验证门禁本身的用例自行 setenv 覆盖。
    monkeypatch.setenv("NEXUS_REPORT_MIN_CHARS", "0")
    # LLM 模型名钉住：大量用例以二元组键注入 `_agents`（如
    # {("research", "deepseek-chat"): agent}），而 get_agent 按
    # (mode, 默认模型, 执行模式) 查找 —— 默认模型一变这些桩就全部落空、
    # 退化为真实 build_agent 并因无 API key 返回 503。
    # 这里钉住桩使用的名字，使「改默认模型」不再连带击穿测试。
    # 模型清单本身的语义由 tests/test_models.py 用注入 settings 单独覆盖。
    monkeypatch.setenv("NEXUS_LLM_MODEL", "deepseek-chat")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
