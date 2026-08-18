"""resolve_concepts 回归测试：当前学习位置（resource_id）优先于纯文本解析。

背景（2026-08-18）：学生问"请问这里涉及到的数学模型是什么？"时，
此前实现完全忽略 resource_id，纯文本匹配失败后回退语义检索，把当前学习
位置解析到噪声节点（如名称为"的"的节点），导致智能体不知道自己正在讲解
的知识点，也无法基于当前节点给出前置知识跳转。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from sqlmodel import Session

from app.models.course_outline_model import CourseOutlineNode
from app.platform.agents.providers.retrieval.active_bundle import (
    ActiveBundleKnowledgeGraphPort,
)


class _FakeGraph:
    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self.nodes = nodes
        self.bundle = SimpleNamespace(bundle_id="bundle-1", graph_snapshot_id="gs-1")


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.bundle = SimpleNamespace(bundle_id="bundle-1", graph_snapshot_id="gs-1")


class _FakeProvider:
    def __init__(self, graph: _FakeGraph, search_hits: list[str] | None = None) -> None:
        self._graph = graph
        self._search_hits = search_hits or []
        self.search_called = False

    def get_graph(self, course: int) -> _FakeGraph:
        return self._graph

    def search_evidence(self, course: int, message: str, top_k: int) -> _FakeResult | None:
        self.search_called = True
        if not self._search_hits:
            return None
        return _FakeResult([SimpleNamespace(node_key=key) for key in self._search_hits])


def _add_outline(
    session: Session,
    course_id: int,
    outline_version_id: str,
    outline_node_id: str,
    node_key: str,
    title: str,
) -> None:
    session.add(CourseOutlineNode(
        outline_node_id=outline_node_id,
        outline_version_id=outline_version_id,
        course_id=course_id,
        knowledge_graph_node_id=node_key,
        title=title,
    ))
    # SQLite 文件库：提交后 session_factory 的新连接才能读到（避免 database is locked）
    session.commit()


def test_resource_id_grounds_the_current_concept(session: Session) -> None:
    """resource_id（on_xxx）解析为当前学习位置，文本检索噪声不再命中。"""
    course_id = 901
    _add_outline(session, course_id, "ov-1", "on_current_901", "kn_current", "控制系统的数学建模")
    _add_outline(session, course_id, "ov-1", "on_noise_901", "kn_noise", "的")

    graph = _FakeGraph([
        {"id": "kn_current", "title": "控制系统的数学建模"},
        {"id": "kn_noise", "title": "的"},
    ])
    provider = _FakeProvider(graph)
    port = ActiveBundleKnowledgeGraphPort(provider=provider)

    async def run() -> list[dict[str, Any]]:
        return await port.resolve_concepts(
            course_id=str(course_id),
            message="请问这里涉及到的数学模型是什么？",
            candidates=[],
            resource_id="on_current_901",
        )

    matches = asyncio.run(run())
    assert matches
    assert matches[0]["concept_id"] == "kn_current"
    assert matches[0]["name"] == "控制系统的数学建模"
    assert not provider.search_called


def test_named_concept_wins_over_resource(session: Session) -> None:
    """学生明确点名某知识点时，该节点优先于当前学习位置。"""
    course_id = 902
    _add_outline(session, course_id, "ov-1", "on_current_902", "kn_current", "微分方程的建立步骤")
    _add_outline(session, course_id, "ov-1", "on_transfer_902", "kn_transfer", "传递函数的定义与性质")

    graph = _FakeGraph([
        {"id": "kn_current", "title": "微分方程的建立步骤"},
        {"id": "kn_transfer", "title": "传递函数的定义与性质"},
    ])
    port = ActiveBundleKnowledgeGraphPort(provider=_FakeProvider(graph))

    async def run() -> list[dict[str, Any]]:
        return await port.resolve_concepts(
            course_id=str(course_id),
            message="我想先学传递函数的定义与性质，帮我看看",
            candidates=[],
            resource_id="on_current_902",
        )

    matches = asyncio.run(run())
    assert matches
    assert matches[0]["concept_id"] == "kn_transfer"


def test_resource_fallback_when_no_text_match_and_no_search_hit(session: Session) -> None:
    """无点名、无候选命中时默认停留在当前学习位置，不再回退到噪声检索。"""
    course_id = 903
    _add_outline(session, course_id, "ov-1", "on_current_903", "kn_current", "拉普拉斯变换")

    graph = _FakeGraph([{"id": "kn_current", "title": "拉普拉斯变换"}])
    provider = _FakeProvider(graph, search_hits=["kn_noise"])
    port = ActiveBundleKnowledgeGraphPort(provider=provider)

    async def run() -> list[dict[str, Any]]:
        return await port.resolve_concepts(
            course_id=str(course_id),
            message="这里面的核心公式推导我没看懂",
            candidates=[],
            resource_id="on_current_903",
        )

    matches = asyncio.run(run())
    assert matches
    assert matches[0]["concept_id"] == "kn_current"
    assert not provider.search_called


def test_no_resource_uses_message_and_candidate_matching(session: Session) -> None:
    """无 resource_id 时保持原有文本/候选匹配行为。"""
    course_id = 904
    _add_outline(session, course_id, "ov-1", "on_b_904", "kn_b", "方框图化简")

    graph = _FakeGraph([
        {"id": "kn_a", "title": "信号流图"},
        {"id": "kn_b", "title": "方框图化简"},
    ])
    port = ActiveBundleKnowledgeGraphPort(provider=_FakeProvider(graph))

    async def run() -> list[dict[str, Any]]:
        return await port.resolve_concepts(
            course_id=str(course_id),
            message="方框图化简的步骤是什么？",
            candidates=[{"name": "方框图化简"}],
            resource_id=None,
        )

    matches = asyncio.run(run())
    assert matches
    assert matches[0]["concept_id"] == "kn_b"


def test_outline_title_keyword_fallback_without_mapping(session: Session) -> None:
    """outline 无 knowledge_graph_node_id 映射时，用标题关键词回退定位当前节点。

    课程5 的 outline 映射为空（数据缺口），on_xxx 无法直接解析；标题
    "数学模型的定义与建模方法" 与图谱节点 "控制系统数学模型" 共享
    "数学模型" 关键词，应命中而非回退到噪声检索（2026-08-18）。
    """
    course_id = 905
    # 故意不写 knowledge_graph_node_id（模拟课程5 的映射缺失）
    _add_outline(session, course_id, "ov-1", "on_current_905", None, "数学模型的定义与建模方法")

    graph = _FakeGraph([
        {"id": "kn_model", "title": "控制系统数学模型"},
        {"id": "kn_noise", "title": "的"},
    ])
    provider = _FakeProvider(graph, search_hits=["kn_noise"])
    port = ActiveBundleKnowledgeGraphPort(provider=provider)

    async def run() -> list[dict[str, Any]]:
        return await port.resolve_concepts(
            course_id=str(course_id),
            message="请问这里涉及到的公式是什么？",
            candidates=[],
            resource_id="on_current_905",
        )

    matches = asyncio.run(run())
    assert matches
    assert matches[0]["concept_id"] == "kn_model"
    assert not provider.search_called


def test_candidate_substring_match_with_prefix_title(session: Session) -> None:
    """候选名是图谱节点标题的子串即命中（"传递函数" ⊂ "一、 传递函数的定义和主要性质"）。"""
    course_id = 906
    _add_outline(session, course_id, "ov-1", "on_c_906", "kn_c", "传递函数")

    graph = _FakeGraph([
        {"id": "kn_prefixed", "title": "一、 传递函数的定义和主要性质"},
        {"id": "kn_plain", "title": "传递函数"},
    ])
    port = ActiveBundleKnowledgeGraphPort(provider=_FakeProvider(graph))

    async def run() -> list[dict[str, Any]]:
        return await port.resolve_concepts(
            course_id=str(course_id),
            message="我想先学一下传递函数",
            candidates=[{"name": "传递函数", "confidence": 1.0}],
            resource_id=None,
        )

    matches = asyncio.run(run())
    assert matches
    # named 优先命中精确标题"传递函数"；candidate 子串命中带前缀的同名节点
    assert matches[0]["concept_id"] == "kn_plain"
    assert any(m["concept_id"] == "kn_prefixed" for m in matches)
