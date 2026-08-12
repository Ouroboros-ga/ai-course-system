"""Persistence contracts for the course-scoped ResearchAgent workspace."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.platform.agents.providers.research.workspace import (
    ResearchWorkspaceAccessError,
    SqlResearchWorkspaceProvider,
)


class TopicEmbeddingProvider:
    provider_name = "topic-test"
    model_name = "topic-test/1"

    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = text.casefold()
            vectors.append([
                1.0 if "rag" in lowered or "检索增强" in lowered else 0.0,
                1.0 if "量子" in lowered else 0.0,
                1.0 if "教育" in lowered else 0.0,
            ])
        return vectors


@pytest.fixture()
def workspace_provider():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return SqlResearchWorkspaceProvider(
        session_factory=lambda: Session(engine),
        embedding_provider=TopicEmbeddingProvider(),
    )


def _workspace(provider, actor="11"):
    return asyncio.run(provider.get_or_create_workspace(
        course_id=7,
        actor_user_id=actor,
        title="RAG 课程研究",
    ))


def test_todos_are_persisted_sorted_and_versioned(workspace_provider):
    workspace = _workspace(workspace_provider)
    low = asyncio.run(workspace_provider.create_todo(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=workspace["active_scope_id"],
        title="整理术语",
        priority=1,
    ))
    high = asyncio.run(workspace_provider.create_todo(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=workspace["active_scope_id"],
        title="核验关键论文",
        priority=3,
    ))

    updated = asyncio.run(workspace_provider.update_todo(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        todo_id=high["todo_id"],
        status="in_progress",
        expected_version=1,
    ))
    snapshot = asyncio.run(workspace_provider.get_workspace_snapshot(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
    ))

    assert updated["version"] == 2
    assert updated["status"] == "in_progress"
    assert [todo["todo_id"] for todo in snapshot["todos"]] == [high["todo_id"], low["todo_id"]]
    assert snapshot["todos"][0]["priority"] == 3


def test_workspace_storage_rejects_cross_actor_access(workspace_provider):
    workspace = _workspace(workspace_provider, actor="11")

    with pytest.raises(ResearchWorkspaceAccessError, match="RESEARCH_WORKSPACE_SCOPE_DENIED"):
        asyncio.run(workspace_provider.get_workspace_snapshot(
            workspace_id=workspace["workspace_id"],
            course_id=7,
            actor_user_id="12",
        ))


def test_notepad_updates_in_place_with_a_monotonic_version(workspace_provider):
    workspace = _workspace(workspace_provider)
    note = asyncio.run(workspace_provider.save_note(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=workspace["active_scope_id"],
        title="证据摘录",
        content="第一版：仅有摘要级证据。",
        tags=["evidence"],
    ))
    changed = asyncio.run(workspace_provider.save_note(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=workspace["active_scope_id"],
        note_id=note["note_id"],
        title="证据摘录",
        content="第二版：补充来源定位。",
        tags=["evidence", "verified"],
        expected_version=1,
    ))

    assert changed["note_id"] == note["note_id"]
    assert changed["version"] == 2
    assert changed["content"].startswith("第二版")


def test_child_scope_interrupt_and_resume_preserve_independent_summary(workspace_provider):
    workspace = _workspace(workspace_provider)
    root_scope = workspace["active_scope_id"]
    child = asyncio.run(workspace_provider.create_scope(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        parent_scope_id=root_scope,
        title="复核实验指标",
        objective="核验指标定义与基线",
        activate=True,
    ))
    interrupted = asyncio.run(workspace_provider.transition_scope(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=child["scope_id"],
        action="interrupt",
        context_summary="已核验 BLEU，待核验人工评价。",
    ))
    after_interrupt = asyncio.run(workspace_provider.get_workspace_snapshot(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
    ))
    resumed = asyncio.run(workspace_provider.transition_scope(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        scope_id=child["scope_id"],
        action="resume",
    ))

    assert interrupted["status"] == "interrupted"
    assert after_interrupt["active_scope_id"] == root_scope
    assert resumed["status"] == "active"
    assert resumed["context_summary"].startswith("已核验 BLEU")
    assert resumed["is_active"] is True


def test_long_term_memory_uses_vectors_and_returns_relevant_items(workspace_provider):
    workspace = _workspace(workspace_provider)
    for content in (
        "RAG 检索增强生成用于教育反馈。",
        "量子化学轨道计算的收敛记录。",
    ):
        asyncio.run(workspace_provider.store_memory(
            workspace_id=workspace["workspace_id"],
            course_id=7,
            actor_user_id="11",
            scope_id=workspace["active_scope_id"],
            tier="long_term",
            content=content,
            importance=0.8,
        ))

    result = asyncio.run(workspace_provider.search_memory(
        workspace_id=workspace["workspace_id"],
        course_id=7,
        actor_user_id="11",
        query="RAG 教育",
        limit=2,
    ))

    assert result["retrieval_mode"] == "vector"
    assert result["items"][0]["content"].startswith("RAG")
    assert result["items"][0]["score"] > result["items"][1]["score"]

