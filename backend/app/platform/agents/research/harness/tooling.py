"""Allowlisted, context-aware tool selection for ResearchAgent."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ResearchToolSpec:
    name: str
    description: str
    intents: frozenset[str]
    keywords: frozenset[str]
    required_permission: str
    timeout_seconds: float = 15.0
    max_retries: int = 1
    risk_level: str = "low"


@dataclass(frozen=True)
class ResearchToolSelection:
    primary_intent: str
    selected_tool_names: list[str]
    denied_tool_names: list[str]
    scores: Mapping[str, float]
    reason_code: str


class ResearchToolRegistry:
    """Immutable registry; presence here is the first tool security gate."""

    def __init__(self, specs: Iterable[ResearchToolSpec]) -> None:
        indexed: dict[str, ResearchToolSpec] = {}
        for spec in specs:
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", spec.name):
                raise ValueError(f"invalid research tool name: {spec.name}")
            if spec.name in indexed:
                raise ValueError(f"duplicate research tool: {spec.name}")
            indexed[spec.name] = spec
        self._specs = MappingProxyType(indexed)

    @classmethod
    def default(cls) -> ResearchToolRegistry:
        permission = "course.question.ask"
        return cls([
            ResearchToolSpec(
                name="paper_search",
                description="只读检索论文元数据与摘要",
                intents=frozenset({"literature_search"}),
                keywords=frozenset({"检索", "搜索", "查找", "论文", "文献", "paper", "search", "arxiv"}),
                required_permission=permission,
                timeout_seconds=18.0,
                max_retries=1,
            ),
            ResearchToolSpec(
                name="todo_manager",
                description="创建、更新、排序和跟踪研究任务",
                intents=frozenset({"todo_create", "todo_update", "todo_list"}),
                keywords=frozenset({"待办", "任务", "todo", "计划", "优先级", "完成"}),
                required_permission=permission,
                timeout_seconds=5.0,
                max_retries=0,
            ),
            ResearchToolSpec(
                name="notepad",
                description="持久化和读取当前研究作用域笔记",
                intents=frozenset({"notepad_write", "notepad_read"}),
                keywords=frozenset({"笔记", "记录", "notepad", "备忘", "摘录"}),
                required_permission=permission,
                timeout_seconds=5.0,
                max_retries=0,
            ),
            ResearchToolSpec(
                name="memory",
                description="写入或检索短期/长期研究记忆",
                intents=frozenset({"memory_store", "memory_search"}),
                keywords=frozenset({"记忆", "记住", "回忆", "memory", "检索记忆"}),
                required_permission=permission,
                timeout_seconds=10.0,
                max_retries=1,
            ),
            ResearchToolSpec(
                name="scope_manager",
                description="创建、切换、中断、恢复和完成子任务作用域",
                intents=frozenset({
                    "scope_create", "scope_switch", "scope_interrupt",
                    "scope_resume", "scope_complete",
                }),
                keywords=frozenset({"子任务", "作用域", "切换", "中断", "恢复", "scope"}),
                required_permission=permission,
                timeout_seconds=5.0,
                max_retries=0,
            ),
            ResearchToolSpec(
                name="writing_assist",
                description="基于工作区上下文与论文结果生成学术写作草稿（综述段落/论文框架/润色）",
                intents=frozenset({"writing_assist"}),
                keywords=frozenset({"写作", "综述", "润色", "起草", "大纲", "论文", "草稿", "draft", "writing", "polish", "outline"}),
                required_permission=permission,
                timeout_seconds=30.0,
                max_retries=0,
            ),
            ResearchToolSpec(
                name="trend_analysis",
                description="对论文元数据做前沿趋势分析（热点关键词/年份分布/趋势方向/主题分类）",
                intents=frozenset({"trend_analysis"}),
                keywords=frozenset({"趋势", "热点", "前沿", "方向", "追踪", "trend", "hot", "frontier", "direction"}),
                required_permission=permission,
                timeout_seconds=10.0,
                max_retries=0,
            ),
        ])

    def get(self, name: str) -> ResearchToolSpec | None:
        return self._specs.get(name)

    def list(self) -> tuple[ResearchToolSpec, ...]:
        return tuple(self._specs.values())


class DynamicResearchToolSelector:
    """Rank tools by explicit action, message intent and current context."""

    def __init__(self, registry: ResearchToolRegistry) -> None:
        self._registry = registry

    def select(
        self,
        *,
        message: str,
        requested_action: str = "auto",
        context_kinds: set[str] | None = None,
        allowed_tool_names: set[str] | frozenset[str] | None = None,
        granted_permissions: set[str] | frozenset[str] | None = None,
        max_tools: int = 3,
    ) -> ResearchToolSelection:
        normalized = str(message or "").casefold()
        explicit = requested_action if requested_action and requested_action != "auto" else ""
        allowed = set(allowed_tool_names or ())
        granted = set(granted_permissions or ())
        context = set(context_kinds or ())
        scores: dict[str, float] = {}

        for spec in self._registry.list():
            if explicit:
                score = 100.0 if explicit in spec.intents else 0.0
            else:
                score = float(sum(1 for keyword in spec.keywords if keyword.casefold() in normalized))
                if spec.name == "todo_manager" and "todo" in context:
                    score += 0.1
                if spec.name == "paper_search" and "paper" in context:
                    score += 0.1
            if score > 0:
                scores[spec.name] = score

        ranked = sorted(scores, key=lambda name: (-scores[name], name))
        selected: list[str] = []
        denied: list[str] = []
        for name in ranked:
            spec = self._registry.get(name)
            if spec is None or name not in allowed:
                continue
            if spec.required_permission not in granted:
                denied.append(name)
                continue
            if len(selected) < max(1, max_tools):
                selected.append(name)

        primary_intent = explicit or self._primary_intent(ranked)
        if denied and not selected:
            reason = "RESEARCH_TOOL_PERMISSION_DENIED"
        elif not selected:
            reason = "RESEARCH_TOOL_NO_MATCH"
        else:
            reason = "RESEARCH_TOOL_SELECTED"
        return ResearchToolSelection(
            primary_intent=primary_intent,
            selected_tool_names=selected,
            denied_tool_names=denied,
            scores=MappingProxyType(dict(scores)),
            reason_code=reason,
        )

    def _primary_intent(self, ranked_names: list[str]) -> str:
        if not ranked_names:
            return "clarify"
        spec = self._registry.get(ranked_names[0])
        if spec is None:
            return "clarify"
        preferred = (
            "literature_search", "todo_create", "notepad_write",
            "memory_search", "scope_create",
        )
        for intent in preferred:
            if intent in spec.intents:
                return intent
        return min(spec.intents)


__all__ = [
    "DynamicResearchToolSelector",
    "ResearchToolRegistry",
    "ResearchToolSelection",
    "ResearchToolSpec",
]
