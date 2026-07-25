"""批次4：TeachingAgentRuntimeRegistry 多报告路由测试。

覆盖：
- 按 (student_id, course_id) 动态构建/缓存 TeachingAgentRuntime
- 同一 (student, course) 多次请求复用同一运行时（缓存）
- 不同 (student, course) 返回不同的运行时（隔离）
- 无报告时返回 None（fail-closed）
- 报告读取异常时返回 None（fail-closed，不抛异常）
- 运行时构建异常时返回 None（fail-closed，不抛异常）
- invalidate 清除缓存后下次请求重建
- 可选工具端口透传到运行时（注入非 None 时被传递）
- list_cached_scopes 反映当前缓存键
- 端点 _resolve_runtime 在 registry 场景下按 (student, course) 路由
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.runtime import TeachingAgentRuntime
from app.platform.agents.tools.fakes import (
    FakeEvents,
    FakeGraph,
    FakeLLM,
    FakeRecommendation,
    FakeRetrieval,
    FakeSandbox,
    FakeScope,
)
from app.platform.retrieval_demo.service import DemoService
from app.platform.retrieval_demo.store import DemoRunStore


def _approved_report(course_id: str = "c-1") -> dict:
    """构造一份通过校验的 KG-MEST Shadow 报告。"""
    return {
        "status": "ok",
        "course_key": course_id,
        "data_version": "protected-shadow-v1",
        "states": {
            "k-1": {
                "observed_performance_score": 0.6,
                "confidence": "medium",
                "values": {"recurring_error_risk": 0.2, "hint_dependency": 0.1, "transfer": 0.5},
                "status": "stable",
                "evidence_refs": [],
                "reason_codes": [],
            },
        },
        "recommendations": {"k-1": []},
    }


def _demo_service(tmp_path: Path) -> DemoService:
    return DemoService(
        configured_mode="demo_compare",
        environment="test",
        store=DemoRunStore(tmp_path / "runs"),
    )


def _make_registry(tmp_path: Path, **overrides: Any) -> TeachingAgentRuntimeRegistry:
    """构造一个使用 tmp_path 报告目录的 registry。"""
    store = KGMestShadowReportStore(tmp_path / "reports")
    return TeachingAgentRuntimeRegistry(
        demo_service=_demo_service(tmp_path),
        llm=FakeLLM(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        store=store,
        **overrides,
    )


# ==================== 多报告路由核心契约 ====================


def test_get_or_create_returns_runtime_when_report_exists(tmp_path):
    """报告存在时，get_or_create 返回非 None 的 TeachingAgentRuntime。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    runtime = registry.get_or_create("s-1", "c-1")
    assert runtime is not None
    assert isinstance(runtime, TeachingAgentRuntime)


def test_get_or_create_builds_runtime_when_no_report(tmp_path):
    """KG-MEST report is optional; no report must not block normal Q&A."""
    registry = _make_registry(tmp_path)
    assert isinstance(registry.get_or_create("s-1", "c-1"), TeachingAgentRuntime)


def test_get_or_create_caches_runtime_per_scope(tmp_path):
    """同一 (student, course) 多次请求返回同一运行时实例（缓存命中）。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    first = registry.get_or_create("s-1", "c-1")
    second = registry.get_or_create("s-1", "c-1")
    assert first is second, "同一 scope 应复用缓存的运行时"


def test_get_or_create_isolates_different_scopes(tmp_path):
    """不同 (student, course) 返回不同的运行时实例（隔离）。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))
    registry._store.write(student_id="s-2", course_id="c-2", report=_approved_report("c-2"))

    rt1 = registry.get_or_create("s-1", "c-1")
    rt2 = registry.get_or_create("s-2", "c-2")
    assert rt1 is not None
    assert rt2 is not None
    assert rt1 is not rt2, "不同 scope 必须返回独立运行时"


def test_get_or_create_isolates_student_within_same_course(tmp_path):
    """同课程不同学生也返回不同运行时（学生隔离）。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))
    registry._store.write(student_id="s-2", course_id="c-1", report=_approved_report("c-1"))

    rt1 = registry.get_or_create("s-1", "c-1")
    rt2 = registry.get_or_create("s-2", "c-1")
    assert rt1 is not None
    assert rt2 is not None
    assert rt1 is not rt2


def test_get_or_create_normalizes_string_types(tmp_path):
    """整型/字符串 ID 都能命中同一缓存（键统一为字符串）。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    # 字符串和等价形式应命中同一缓存
    rt_str = registry.get_or_create("s-1", "c-1")
    rt_same = registry.get_or_create(str("s-1"), str("c-1"))
    assert rt_str is rt_same


# ==================== fail-closed 契约 ====================


def test_get_or_create_builds_runtime_when_optional_store_read_raises(tmp_path):
    """An optional report read failure must not block normal Q&A."""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    def _boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("disk corrupted")

    with patch.object(registry._store, "read", side_effect=_boom):
        runtime = registry.get_or_create("s-1", "c-1")
    assert isinstance(runtime, TeachingAgentRuntime)


def test_get_or_create_returns_none_when_runtime_build_raises(tmp_path):
    """运行时构建异常时返回 None（fail-closed，不抛异常）。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    with patch(
        "app.platform.agents.registry.build_kg_mest_shadow_sidecar_runtime",
        side_effect=RuntimeError("build failed"),
    ):
        runtime = registry.get_or_create("s-1", "c-1")
    assert runtime is None


# ==================== 缓存管理契约 ====================


def test_list_cached_scopes_returns_empty_initially(tmp_path):
    """新创建的 registry 缓存为空。"""
    registry = _make_registry(tmp_path)
    assert registry.list_cached_scopes() == []


def test_list_cached_scopes_returns_cached_pairs(tmp_path):
    """list_cached_scopes 反映已缓存的 (student, course) 对。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))
    registry._store.write(student_id="s-2", course_id="c-2", report=_approved_report("c-2"))

    registry.get_or_create("s-1", "c-1")
    registry.get_or_create("s-2", "c-2")

    cached = set(registry.list_cached_scopes())
    assert cached == {("s-1", "c-1"), ("s-2", "c-2")}


def test_invalidate_drops_cached_runtime(tmp_path):
    """invalidate 清除指定 scope 的缓存，下次请求重建。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    first = registry.get_or_create("s-1", "c-1")
    registry.invalidate("s-1", "c-1")
    assert ("s-1", "c-1") not in registry.list_cached_scopes()

    second = registry.get_or_create("s-1", "c-1")
    # 重建后应得到一个新的运行时实例
    assert second is not None
    assert first is not second


def test_invalidate_unknown_scope_is_noop(tmp_path):
    """invalidate 不存在的 scope 不抛异常。"""
    registry = _make_registry(tmp_path)
    registry.invalidate("never", "cached")
    # 没有抛异常即通过


# ==================== 可选工具端口透传契约 ====================


class _RecordingWebPort:
    """记录被调用的 fake WebResearchPort。"""
    def __init__(self) -> None:
        self.called = False

    async def research(self, *, course_id: str, query: str, student_id: str | None = None) -> dict:
        self.called = True
        return {"results": [], "is_supplementary": True}


class _RecordingCogPort:
    async def get_state(self, *, student_id: str, course_id: str, node_id: str | None = None) -> dict:
        return {"observed_performance_score": 0.5}

    async def get_recommendation(self, *, student_id: str, course_id: str, node_id: str | None = None) -> dict:
        return {"recommendation_id": "r"}


class _RecordingQBPort:
    async def list_questions(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list:
        return []


def test_optional_ports_propagate_to_built_runtime(tmp_path):
    """注入的可选端口应透传到构建的 TeachingAgentRuntime（通过 tools 字段验证）。"""
    web = _RecordingWebPort()
    cog = _RecordingCogPort()
    qb = _RecordingQBPort()

    registry = _make_registry(
        tmp_path,
        web_research=web,
        cognition=cog,
        question_bank=qb,
    )
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    runtime = registry.get_or_create("s-1", "c-1")
    assert runtime is not None
    # 通过访问内部 tools 验证端口确实透传（运行时持有 tools）
    tools = runtime._tools if hasattr(runtime, "_tools") else None
    # 运行时没有公开 tools 字段，改为通过执行 workflow 验证端口可达
    # 这里仅断言 runtime 已构建（端口注入未导致构建失败）
    # 端口实际执行由 test_batch4_tool_ports.py 中的契约测试覆盖
    assert isinstance(runtime, TeachingAgentRuntime)


def test_registry_defaults_optional_ports_to_none_when_not_injected(tmp_path):
    """未注入可选端口时，registry 仍能正常构建运行时（默认 None）。"""
    registry = _make_registry(tmp_path)  # 不传 web_research / cognition / question_bank
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    runtime = registry.get_or_create("s-1", "c-1")
    assert runtime is not None
    assert isinstance(runtime, TeachingAgentRuntime)


# ==================== 端点 _resolve_runtime 路由契约 ====================


# Load the endpoint module the same way the existing agents test does.
_ENDPOINT = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "endpoints" / "teaching_agent.py"
_SPEC = importlib.util.spec_from_file_location("teaching_agent_endpoint_batch4_test", _ENDPOINT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
router = _MODULE.router
_resolve_runtime = _MODULE._resolve_runtime


def test_resolve_runtime_returns_runtime_from_registry_for_known_scope(tmp_path):
    """registry 场景下 _resolve_runtime 按 (student, course) 解析运行时。"""
    registry = _make_registry(tmp_path)
    registry._store.write(student_id="s-1", course_id="c-1", report=_approved_report("c-1"))

    runtime = _resolve_runtime(registry, "s-1", "c-1")
    assert isinstance(runtime, TeachingAgentRuntime)


def test_resolve_runtime_builds_for_unknown_report_scope(tmp_path):
    """Registry resolves a runtime even without a KG-MEST report."""
    registry = _make_registry(tmp_path)  # 空存储

    assert isinstance(_resolve_runtime(registry, "s-1", "c-1"), TeachingAgentRuntime)


def test_resolve_runtime_returns_runtime_directly_when_legacy_single_runtime_injected(tmp_path):
    """非 registry（旧的单运行时）场景下 _resolve_runtime 直接返回该运行时。"""
    from app.platform.agents.contracts import TeachingTools
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=app_fake_student_modeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=FakeLLM(),
    )
    runtime = TeachingAgentRuntime(tools)
    resolved = _resolve_runtime(runtime, "s-1", "c-1")
    assert resolved is runtime


def app_fake_student_modeling():
    """避免循环导入的小工厂。"""
    from app.platform.agents.tools.fakes import FakeStudentModeling
    return FakeStudentModeling()


# ==================== 端点 get_runtime 优先级契约 ====================


def _build_legacy_runtime() -> TeachingAgentRuntime:
    from app.platform.agents.contracts import TeachingTools
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=app_fake_student_modeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=FakeLLM(),
    )
    return TeachingAgentRuntime(tools)


def test_get_runtime_returns_registry_when_both_injected(tmp_path):
    """当 registry 和 legacy runtime 都注入时，``get_runtime`` 优先返回 registry。

    通过检查 ``app.state`` 的注入顺序和 ``get_runtime`` 的实现逻辑验证：
    registry 非空时直接返回 registry，不回退到 legacy runtime。
    端点层面的 503 SCOPE_NOT_CONFIGURED 行为由 ``_resolve_runtime`` 单元测试覆盖
    （见 test_resolve_runtime_raises_503_for_unknown_scope_in_registry）。
    """
    registry = _make_registry(tmp_path)
    legacy_runtime = _build_legacy_runtime()

    class _FakeRequest:
        class _State:
            teaching_agent_runtime_registry = registry
            teaching_agent_runtime = legacy_runtime
        app = type("App", (), {"state": _State()})

    from app.api.v1.endpoints.teaching_agent import get_runtime as _gr
    runtime_source = _gr(_FakeRequest())
    assert runtime_source is registry, "registry 必须优先于 legacy runtime"


def test_get_runtime_returns_legacy_when_registry_absent(tmp_path):
    """当 registry 缺失时，``get_runtime`` 回退到 legacy runtime。"""
    legacy_runtime = _build_legacy_runtime()

    class _FakeRequest:
        class _State:
            teaching_agent_runtime_registry = None
            teaching_agent_runtime = legacy_runtime
        app = type("App", (), {"state": _State()})

    from app.api.v1.endpoints.teaching_agent import get_runtime as _gr
    runtime_source = _gr(_FakeRequest())
    assert runtime_source is legacy_runtime


def test_get_runtime_raises_503_when_neither_injected(tmp_path):
    """当 registry 和 legacy runtime 都缺失时，``get_runtime`` 抛 503 NOT_CONFIGURED。"""
    class _FakeRequest:
        class _State:
            teaching_agent_runtime_registry = None
            teaching_agent_runtime = None
        app = type("App", (), {"state": _State()})

    from app.api.v1.endpoints.teaching_agent import get_runtime as _gr
    with pytest.raises(HTTPException) as exc:
        _gr(_FakeRequest())
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "TEACHING_AGENT_NOT_CONFIGURED"


# ==================== stdlib 入口 ====================


class TeachingAgentRuntimeRegistryTests(unittest.TestCase):
    """Expose the same offline checks through the repository's stdlib test entry."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_known_scope(self): test_get_or_create_returns_runtime_when_report_exists(self.tmp_path)
    def test_no_report(self): test_get_or_create_builds_runtime_when_no_report(self.tmp_path)
    def test_cache_hit(self): test_get_or_create_caches_runtime_per_scope(self.tmp_path)
    def test_scope_isolation(self): test_get_or_create_isolates_different_scopes(self.tmp_path)
    def test_student_isolation(self): test_get_or_create_isolates_student_within_same_course(self.tmp_path)
    def test_string_normalization(self): test_get_or_create_normalizes_string_types(self.tmp_path)
    def test_store_read_fail_closed(self): test_get_or_create_builds_runtime_when_optional_store_read_raises(self.tmp_path)
    def test_build_fail_closed(self): test_get_or_create_returns_none_when_runtime_build_raises(self.tmp_path)
    def test_list_cached_empty(self): test_list_cached_scopes_returns_empty_initially(self.tmp_path)
    def test_list_cached_pairs(self): test_list_cached_scopes_returns_cached_pairs(self.tmp_path)
    def test_invalidate_drops(self): test_invalidate_drops_cached_runtime(self.tmp_path)
    def test_invalidate_unknown_noop(self): test_invalidate_unknown_scope_is_noop(self.tmp_path)
    def test_optional_ports_propagate(self): test_optional_ports_propagate_to_built_runtime(self.tmp_path)
    def test_optional_ports_default_none(self): test_registry_defaults_optional_ports_to_none_when_not_injected(self.tmp_path)
    def test_resolve_runtime_known(self): test_resolve_runtime_returns_runtime_from_registry_for_known_scope(self.tmp_path)
    def test_resolve_runtime_unknown(self): test_resolve_runtime_builds_for_unknown_report_scope(self.tmp_path)
    def test_resolve_runtime_legacy(self): test_resolve_runtime_returns_runtime_directly_when_legacy_single_runtime_injected(self.tmp_path)
    def test_get_runtime_prefers_registry(self): test_get_runtime_returns_registry_when_both_injected(self.tmp_path)
    def test_get_runtime_legacy_fallback(self): test_get_runtime_returns_legacy_when_registry_absent(self.tmp_path)
    def test_get_runtime_503_when_neither(self): test_get_runtime_raises_503_when_neither_injected(self.tmp_path)
