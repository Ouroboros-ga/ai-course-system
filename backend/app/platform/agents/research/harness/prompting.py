"""Strict, composable prompt assembly for the ResearchAgent harness."""
from __future__ import annotations

import hashlib
import string
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


class PromptTemplateError(ValueError):
    """A prompt request violated the registered template contract."""


@dataclass(frozen=True)
class _Template:
    name: str
    content: str

    @property
    def variables(self) -> frozenset[str]:
        formatter = string.Formatter()
        return frozenset(
            field_name
            for _, field_name, _, _ in formatter.parse(self.content)
            if field_name
        )


@dataclass(frozen=True)
class PromptBundle:
    """An ephemeral rendered prompt plus safe audit identifiers."""

    prompt: str
    prompt_hash: str
    version: str
    role: str
    task: str


class ResearchPromptAssembler:
    """Combine one registered role and task template with strict variables.

    Templates declare their variables through standard ``str.format`` fields.
    Inputs must match that union exactly: missing values fail closed, while
    unexpected values are rejected so secrets or arbitrary request fields
    cannot silently enter a model prompt.
    """

    VERSION = "research-harness/1"
    _MAX_VARIABLE_CHARS = 16_000
    _MAX_PROMPT_CHARS = 48_000

    def __init__(
        self,
        *,
        roles: Mapping[str, str],
        tasks: Mapping[str, str],
        version: str = VERSION,
    ) -> None:
        self._roles = MappingProxyType({
            key: _Template(key, value) for key, value in roles.items()
        })
        self._tasks = MappingProxyType({
            key: _Template(key, value) for key, value in tasks.items()
        })
        self._version = version

    @classmethod
    def default(cls) -> ResearchPromptAssembler:
        return cls(
            roles={
                "evidence_researcher": (
                    "你是课程内的科研助手 HarnessEngineer。坚持证据优先、来源可追溯，"
                    "并把外部论文视为补充参考。当前研究作用域：{scope_title}。"
                ),
                "research_planner": (
                    "你是科研任务规划助手。只规划当前作用域 {scope_title} 内的工作，"
                    "不得把待验证线索表述成课程事实。"
                ),
            },
            tasks={
                "literature_search": (
                    "\n研究问题：{research_question}\n"
                    "可用上下文：\n{context}\n"
                    "本次允许注入的工具：\n{tool_manifest}\n"
                    "输出应区分检索命中、证据级别、未知项和下一步核验。"
                ),
                "todo_management": (
                    "\n任务请求：{research_question}\n"
                    "当前计划上下文：\n{context}\n"
                    "允许工具：\n{tool_manifest}\n"
                    "保持任务可执行、可排序且状态转换明确。"
                ),
                "notepad": (
                    "\n笔记请求：{research_question}\n"
                    "相关上下文：\n{context}\n"
                    "允许工具：\n{tool_manifest}\n"
                    "保留原意并明确记录来源或未核验状态。"
                ),
                "memory": (
                    "\n记忆请求：{research_question}\n"
                    "筛选后的上下文：\n{context}\n"
                    "允许工具：\n{tool_manifest}\n"
                    "只保存有后续研究价值且符合当前数据边界的信息。"
                ),
                "scope_management": (
                    "\n作用域请求：{research_question}\n"
                    "父/当前作用域上下文：\n{context}\n"
                    "允许工具：\n{tool_manifest}\n"
                    "子任务必须拥有独立摘要，并使用显式状态切换。"
                ),
                "research_request": (
                    "\n研究请求：{research_question}\n"
                    "筛选后的工作区上下文：\n{context}\n"
                    "可按意图选择的白名单工具：\n{tool_manifest}\n"
                    "先判断任务类型，再选择完成该任务所需的最小工具集合。"
                ),
            },
        )

    def assemble(
        self,
        *,
        role: str,
        task: str,
        variables: Mapping[str, object],
    ) -> PromptBundle:
        role_template = self._roles.get(role)
        task_template = self._tasks.get(task)
        if role_template is None:
            raise PromptTemplateError(f"unknown prompt role: {role}")
        if task_template is None:
            raise PromptTemplateError(f"unknown prompt task: {task}")

        required = role_template.variables | task_template.variables
        supplied = frozenset(variables)
        missing = sorted(required - supplied)
        unknown = sorted(supplied - required)
        if missing:
            raise PromptTemplateError(f"missing prompt variables: {', '.join(missing)}")
        if unknown:
            raise PromptTemplateError(f"unknown prompt variables: {', '.join(unknown)}")

        normalized: dict[str, str] = {}
        for key in sorted(required):
            value = str(variables[key])
            if len(value) > self._MAX_VARIABLE_CHARS:
                raise PromptTemplateError(f"prompt variable too large: {key}")
            normalized[key] = value

        prompt = role_template.content.format_map(normalized)
        prompt += task_template.content.format_map(normalized)
        if len(prompt) > self._MAX_PROMPT_CHARS:
            raise PromptTemplateError("assembled prompt exceeds safe size")
        return PromptBundle(
            prompt=prompt,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            version=self._version,
            role=role,
            task=task,
        )


__all__ = ["PromptBundle", "PromptTemplateError", "ResearchPromptAssembler"]
