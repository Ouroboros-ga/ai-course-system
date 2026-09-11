"""PR-02：Judge0 出口单一化布局契约。

PR-02 把 Judge0 客户端从 ``services/sandbox_client.py`` 搬进
``domain/oj/judging/providers/judge0.py``（ADR-0001 决定 3）。

**为什么最后没有保留兼容 shim**（这条值得记住）
------------------------------------------------
最初做的是「搬家 + 旧路径留纯再导出 shim」。但一跑测试就发现：既有测试用
**模块路径字符串**做 monkeypatch，例如
``patch("app.services.sandbox_client.httpx.Client")``。

shim 对这类 patch **无能为力**：
- shim 只再导出公共 API，不含 ``httpx`` / ``time`` / ``settings``，patch 直接报
  ``AttributeError: <module 'app.services.sandbox_client'> does not have the attribute 'httpx'``；
- 就算把 ``httpx`` 塞进 shim，patch 也只会改 **shim 命名空间里的名字**，
  真实模块里 ``submit_code`` 用的仍是原对象 ——
  于是测试**照样通过**，但实际没打到任何东西，**静默失去覆盖**。

所以改成了彻底切换：4 个生产调用点与全部测试引用都指向新路径，shim 删除。
现在「Judge0 只有一个出口」是字面事实，不存在两个可 patch 的位置。

本文件守四件事：

1. **旧路径不存在** —— 防止有人把 shim 加回来制造第二个可 patch 的位置。
2. **没有别处再定义 Judge0 语义** —— 例如别处又冒出 ``SubmissionStatus``。
3. **providers 是唯一持有 Judge0 传输细节的地方**。
4. **provider 声明了 ``__all__``** —— 导出面显式，便于日后加第二个 provider。
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
PROVIDER_REL = "app/domain/oj/judging/providers/judge0.py"

PROVIDER = importlib.import_module("app.domain.oj.judging.providers.judge0")

#: 4 个生产调用点实际用到的符号。
_CALL_SITE_SYMBOLS = (
    "ALLOWED_LANGUAGES",
    "SandboxClient",
    "SandboxResourceLimits",
    "SandboxResult",
    "SubmissionStatus",
    "sandbox_client",
)


class TestLegacyPathIsGone:
    def test_old_module_cannot_be_imported(self) -> None:
        """旧路径必须彻底消失 —— 留着它就是第二个可 patch 的位置。"""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("app.services.sandbox_client")

    def test_no_shim_file_on_disk(self) -> None:
        assert not (APP_ROOT / "services" / "sandbox_client.py").exists()

    def test_no_source_still_imports_the_old_path(self) -> None:
        """任何 ``from app.services.sandbox_client import ...`` 都必须消失。

        跳过本文件自身：断言里的那个字符串本身就是一次匹配，
        不排除就会恒红（这是写「扫源码」型测试最容易踩的坑）。
        """
        self_path = Path(__file__).resolve()
        offenders: list[str] = []
        for root in (APP_ROOT, BACKEND_ROOT / "tests"):
            for path in root.rglob("*.py"):
                if path.resolve() == self_path:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                # 只查真正的 import 语句，忽略文档里提到旧路径的说明文字
                if "from app.services.sandbox_client import" in text:
                    offenders.append(path.relative_to(BACKEND_ROOT).as_posix())
        assert offenders == [], f"仍在 import 旧路径：{offenders}"


class TestSingleProvider:
    def test_provider_is_importable_and_complete(self) -> None:
        for name in _CALL_SITE_SYMBOLS:
            assert hasattr(PROVIDER, name), f"provider 缺少 {name}"

    def test_provider_declares_all(self) -> None:
        assert isinstance(PROVIDER.__all__, list) and PROVIDER.__all__
        for name in _CALL_SITE_SYMBOLS:
            assert name in PROVIDER.__all__

    def test_singleton_is_a_client(self) -> None:
        assert isinstance(PROVIDER.sandbox_client, PROVIDER.SandboxClient)

    def test_verdict_vocabulary_is_not_redefined_elsewhere(self) -> None:
        """``SubmissionStatus`` 只允许有一个定义（provider 内）。

        它对应 PR-01 的 ``RunVerdict``，两套判定词汇并存会让排名算错。
        """
        definitions: list[str] = []
        for path in APP_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "class SubmissionStatus" in text:
                definitions.append(path.relative_to(BACKEND_ROOT).as_posix())
        assert definitions == [PROVIDER_REL], f"判定枚举被重复定义：{definitions}"


class TestJudge0DetailsStayInsideProviders:
    def test_transport_details_live_only_in_the_provider(self) -> None:
        """ADR-0001 决定 3：Judge0 的鉴权头与 payload 形状只允许出现在 providers/ 内。"""
        offenders: list[str] = []
        for path in APP_ROOT.rglob("*.py"):
            posix = path.as_posix()
            if "domain/oj/judging/providers" in posix:
                continue
            if path.name == "config.py" and "core" in posix:
                continue  # 配置项本身合法
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "X-Auth-Token" in text or '"base64_encoded"' in text:
                offenders.append(path.relative_to(BACKEND_ROOT).as_posix())
        assert offenders == [], f"Judge0 细节泄漏到 providers/ 之外：{offenders}"
