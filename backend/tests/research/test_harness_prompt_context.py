"""Contract tests for ResearchAgent prompt and context engineering."""
from __future__ import annotations

import asyncio

import pytest

from app.platform.agents.research.harness.context import (
    ContextItem,
    ResearchContextManager,
)
from app.platform.agents.research.harness.prompting import (
    PromptTemplateError,
    ResearchPromptAssembler,
)


def test_prompt_assembler_combines_role_task_context_and_tool_manifest():
    assembler = ResearchPromptAssembler.default()

    bundle = assembler.assemble(
        role="evidence_researcher",
        task="literature_search",
        variables={
            "scope_title": "RAG 教育应用",
            "research_question": "RAG 是否改善编程课学习反馈？",
            "context": "课程范围：计算机课程；只使用补充证据。",
            "tool_manifest": "paper_search: 只读论文元数据检索",
        },
    )

    assert "证据优先" in bundle.prompt
    assert "RAG 是否改善编程课学习反馈" in bundle.prompt
    assert "paper_search" in bundle.prompt
    assert bundle.version == "research-harness/1"
    assert len(bundle.prompt_hash) == 64


def test_prompt_assembler_fails_closed_on_missing_or_unknown_variables():
    assembler = ResearchPromptAssembler.default()

    with pytest.raises(PromptTemplateError, match="missing.*research_question"):
        assembler.assemble(
            role="evidence_researcher",
            task="literature_search",
            variables={
                "scope_title": "课程研究",
                "context": "上下文",
                "tool_manifest": "paper_search",
            },
        )

    with pytest.raises(PromptTemplateError, match="unknown.*api_key"):
        assembler.assemble(
            role="evidence_researcher",
            task="literature_search",
            variables={
                "scope_title": "课程研究",
                "research_question": "如何检索？",
                "context": "上下文",
                "tool_manifest": "paper_search",
                "api_key": "must-not-enter-a-prompt",
            },
        )


def test_context_manager_selects_relevant_chunks_and_compresses_over_budget():
    manager = ResearchContextManager(
        max_tokens=90,
        chunk_chars=180,
        chunk_overlap=30,
        preserve_recent=1,
    )
    items = [
        ContextItem(
            item_id="note-rag",
            kind="notepad",
            content=("检索增强生成 RAG 在编程教育反馈中的证据。" * 30),
            sequence=1,
            importance=0.9,
        ),
        ContextItem(
            item_id="note-unrelated",
            kind="notepad",
            content=("量子化学分子轨道计算记录。" * 30),
            sequence=2,
            importance=0.2,
        ),
        ContextItem(
            item_id="latest-todo",
            kind="todo",
            content="下一步核验 RAG 论文的数据集和实验指标。",
            sequence=3,
            importance=0.8,
        ),
    ]

    prepared = asyncio.run(manager.prepare(
        query="RAG 编程教育 实验指标",
        items=items,
    ))

    assert prepared.compressed is True
    assert prepared.estimated_tokens <= prepared.budget_tokens
    assert "note-rag" in prepared.selected_item_ids
    assert "latest-todo" in prepared.selected_item_ids
    assert prepared.summary
    assert prepared.compression_method == "extractive"
    assert prepared.dropped_item_ids


def test_context_manager_chunks_with_overlap_without_losing_boundary_text():
    manager = ResearchContextManager(
        max_tokens=500,
        chunk_chars=20,
        chunk_overlap=5,
    )
    text = "abcdefghijklmnopqrstuvwxyz0123456789"

    chunks = manager.chunk_text(text)

    assert chunks[0][-5:] == chunks[1][:5]
    assert "".join([chunks[0], chunks[1][5:], chunks[2][5:]]) == text

