"""M0-B2 回归：`.env.example` 与 Settings（env_prefix="NEXUS_"）契约对齐（D3）。

example 里每个非注释变量必须能映射到 Settings 的真实字段——pydantic-settings
对未知变量（extra="ignore"）会静默丢弃，配置写了不生效是最隐蔽的故障，
这里用契约测试把它锁死。
"""

import re
from pathlib import Path

from nexus.config import Settings

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _example_vars() -> list[str]:
    text = EXAMPLE.read_text(encoding="utf-8")
    names = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        names.append(stripped.split("=", 1)[0].strip())
    assert names, ".env.example 中应存在至少一个变量"
    return names


def test_example_vars_all_recognized_by_settings():
    fields = Settings.model_fields
    recognized = {("NEXUS_" + name).upper() for name in fields}
    unknown = [v for v in _example_vars() if v not in recognized]
    assert unknown == [], f"example 中存在 Settings 不识别的变量（会被静默丢弃）: {unknown}"


def test_settings_critical_fields_have_example_entries():
    """关键部署变量必须在 example 中有占位，避免部署时遗漏。"""
    example_vars = set(_example_vars())
    for field in (
        "deepseek_api_key",
        "searxng_url",
        "repro_worker_url",
        "repro_worker_token",
        "postgres_dsn",
        "api_key",
    ):
        assert ("NEXUS_" + field).upper() in example_vars, f"example 缺少 NEXUS_{field.upper()}"


def test_no_unprefixed_vars_left():
    """D3 根因回归：不得再出现缺 NEXUS_ 前缀的变量（如裸 DEEPSEEK_API_KEY）。"""
    for var in _example_vars():
        assert var.startswith("NEXUS_"), f"变量缺 NEXUS_ 前缀: {var}"
    # 正则兜底：任何形如行首 VAR= 的赋值都必须带前缀（防止后面新增漏网）。
    text = EXAMPLE.read_text(encoding="utf-8")
    bare = re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.M)
    assert all(v.startswith("NEXUS_") for v in bare)
