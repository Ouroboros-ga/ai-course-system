"""SQLModel workspace provider with pgvector-aware memory retrieval."""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.research_workspace_model import (
    ResearchMemory,
    ResearchNote,
    ResearchScope,
    ResearchTodo,
    ResearchWorkspace,
)

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")
_TODO_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
_TODO_TRANSITIONS = {
    "pending": {"in_progress", "completed", "cancelled"},
    "in_progress": {"pending", "completed", "cancelled"},
    "completed": {"pending"},
    "cancelled": {"pending"},
}
_SCOPE_ACTIONS = {"switch", "interrupt", "resume", "complete"}


class ResearchWorkspaceError(RuntimeError):
    """Stable workspace failure surfaced through Harness result codes."""


class ResearchWorkspaceAccessError(ResearchWorkspaceError):
    """The requested workspace does not belong to the course/actor pair."""


class ResearchWorkspaceConflictError(ResearchWorkspaceError):
    """An optimistic version or state transition conflict."""


class LazyEmbeddingProvider:
    """Initialize a configured embedding backend on the first memory call.

    Local transformer loading and remote-provider construction stay outside
    application bootstrap.  The factory is invoked once under a lock; remote
    network I/O still happens only when ``embed`` is explicitly requested.
    """

    def __init__(
        self,
        *,
        factory: Callable[[], Any],
        provider_name: str,
        model_name: str,
    ) -> None:
        self._factory = factory
        self.provider_name = provider_name
        self.model_name = model_name
        self._instance: Any | None = None
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        instance = self._instance
        if instance is None:
            with self._lock:
                instance = self._instance
                if instance is None:
                    instance = self._factory()
                    self._instance = instance
        return instance.embed(texts)


class SqlResearchWorkspaceProvider:
    """Call-scoped persistence for Todos, notes, scopes and memories.

    Every public method resolves the workspace by ``workspace_id + course_id +
    actor_user_id`` before touching child rows.  This storage boundary does not
    replace Course Access; the API and graph tool node perform that authorization
    separately before calling this provider.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        embedding_provider: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_provider = embedding_provider

    async def get_or_create_workspace(
        self,
        *,
        course_id: int,
        actor_user_id: str,
        title: str = "科研工作台",
    ) -> Mapping[str, Any]:
        actor_id = _actor_id(actor_user_id)
        with self._session_factory() as session:
            workspace = session.exec(select(ResearchWorkspace).where(
                ResearchWorkspace.course_id == int(course_id),
                ResearchWorkspace.owner_user_id == actor_id,
            )).first()
            if workspace is None:
                workspace = ResearchWorkspace(
                    course_id=int(course_id),
                    owner_user_id=actor_id,
                    title=_bounded(title, 200, fallback="科研工作台"),
                )
                session.add(workspace)
                session.flush()
                root = ResearchScope(
                    workspace_id=workspace.workspace_id,
                    title="主研究作用域",
                    objective="统筹当前课程内的研究任务与证据线索",
                )
                session.add(root)
                session.flush()
                workspace.active_scope_id = root.scope_id
                session.add(workspace)
                session.commit()
                session.refresh(workspace)
            return _workspace_dict(workspace)

    async def get_workspace_snapshot(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
    ) -> Mapping[str, Any]:
        with self._session_factory() as session:
            workspace = self._require_workspace(
                session, workspace_id=workspace_id, course_id=course_id,
                actor_user_id=actor_user_id,
            )
            todos = list(session.exec(select(ResearchTodo).where(
                ResearchTodo.workspace_id == workspace.workspace_id,
            )).all())
            todos.sort(key=lambda item: (
                -item.priority,
                {"in_progress": 0, "pending": 1, "completed": 2, "cancelled": 3}.get(item.status, 9),
                item.position,
                item.created_at,
            ))
            notes = list(session.exec(select(ResearchNote).where(
                ResearchNote.workspace_id == workspace.workspace_id,
            ).order_by(ResearchNote.updated_at.desc())).all())
            scopes = list(session.exec(select(ResearchScope).where(
                ResearchScope.workspace_id == workspace.workspace_id,
            ).order_by(ResearchScope.created_at.asc())).all())
            memories = list(session.exec(select(ResearchMemory).where(
                ResearchMemory.workspace_id == workspace.workspace_id,
            ).order_by(ResearchMemory.last_accessed_at.desc()).limit(20)).all())
            return {
                **_workspace_dict(workspace),
                "todos": [_todo_dict(item) for item in todos],
                "notes": [_note_dict(item) for item in notes],
                "scopes": [_scope_dict(item, workspace.active_scope_id) for item in scopes],
                "memories": [_memory_dict(item, include_content=False) for item in memories],
            }

    async def create_todo(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        scope_id: str | None,
        title: str,
        description: str = "",
        priority: int = 1,
    ) -> Mapping[str, Any]:
        actor_id = _actor_id(actor_user_id)
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            self._require_scope(session, workspace.workspace_id, scope_id)
            bounded_priority = min(3, max(0, int(priority)))
            existing = session.exec(select(ResearchTodo).where(
                ResearchTodo.workspace_id == workspace.workspace_id,
                ResearchTodo.priority == bounded_priority,
            )).all()
            todo = ResearchTodo(
                workspace_id=workspace.workspace_id,
                scope_id=scope_id,
                title=_bounded(title, 300),
                description=_bounded(description, 8_000, fallback=""),
                priority=bounded_priority,
                position=len(existing),
                created_by=actor_id,
            )
            session.add(todo)
            self._touch_workspace(workspace)
            session.add(workspace)
            session.commit()
            session.refresh(todo)
            return _todo_dict(todo)

    async def update_todo(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        todo_id: str,
        status: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        position: int | None = None,
        expected_version: int | None = None,
    ) -> Mapping[str, Any]:
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            todo = session.exec(select(ResearchTodo).where(
                ResearchTodo.workspace_id == workspace.workspace_id,
                ResearchTodo.todo_id == todo_id,
            )).first()
            if todo is None:
                raise ResearchWorkspaceAccessError("RESEARCH_TODO_NOT_FOUND")
            _check_version(todo.version, expected_version)
            if status is not None and status != todo.status:
                if status not in _TODO_STATUSES or status not in _TODO_TRANSITIONS.get(todo.status, set()):
                    raise ResearchWorkspaceConflictError("RESEARCH_TODO_TRANSITION_INVALID")
                todo.status = status
                todo.completed_at = utcnow_aware() if status == "completed" else None
            if title is not None:
                todo.title = _bounded(title, 300)
            if description is not None:
                todo.description = _bounded(description, 8_000, fallback="")
            if priority is not None:
                todo.priority = min(3, max(0, int(priority)))
            if position is not None:
                todo.position = max(0, int(position))
            todo.version += 1
            todo.updated_at = utcnow_aware()
            self._touch_workspace(workspace)
            session.add(todo)
            session.add(workspace)
            session.commit()
            session.refresh(todo)
            return _todo_dict(todo)

    async def save_note(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        scope_id: str | None,
        title: str,
        content: str,
        tags: Sequence[str] | None = None,
        note_id: str | None = None,
        expected_version: int | None = None,
    ) -> Mapping[str, Any]:
        actor_id = _actor_id(actor_user_id)
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            self._require_scope(session, workspace.workspace_id, scope_id)
            note = None
            if note_id:
                note = session.exec(select(ResearchNote).where(
                    ResearchNote.workspace_id == workspace.workspace_id,
                    ResearchNote.note_id == note_id,
                )).first()
                if note is None:
                    raise ResearchWorkspaceAccessError("RESEARCH_NOTE_NOT_FOUND")
                _check_version(note.version, expected_version)
                note.version += 1
                note.updated_at = utcnow_aware()
            else:
                note = ResearchNote(
                    workspace_id=workspace.workspace_id,
                    scope_id=scope_id,
                    title=_bounded(title, 300, fallback="研究笔记"),
                    content="",
                    created_by=actor_id,
                )
            note.title = _bounded(title, 300, fallback="研究笔记")
            note.content = _bounded(content, 40_000)
            note.tags = _tags(tags)
            session.add(note)
            self._touch_workspace(workspace)
            session.add(workspace)
            session.commit()
            session.refresh(note)
            return _note_dict(note)

    async def create_scope(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        parent_scope_id: str | None,
        title: str,
        objective: str = "",
        activate: bool = True,
    ) -> Mapping[str, Any]:
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            parent = self._require_scope(session, workspace.workspace_id, parent_scope_id or workspace.active_scope_id)
            scope = ResearchScope(
                workspace_id=workspace.workspace_id,
                parent_scope_id=parent.scope_id if parent else None,
                title=_bounded(title, 240),
                objective=_bounded(objective, 8_000, fallback=""),
                status="active",
            )
            session.add(scope)
            session.flush()
            if activate:
                workspace.active_scope_id = scope.scope_id
            self._touch_workspace(workspace)
            session.add(workspace)
            session.commit()
            session.refresh(scope)
            return _scope_dict(scope, workspace.active_scope_id)

    async def transition_scope(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        scope_id: str,
        action: str,
        context_summary: str | None = None,
    ) -> Mapping[str, Any]:
        if action not in _SCOPE_ACTIONS:
            raise ResearchWorkspaceConflictError("RESEARCH_SCOPE_ACTION_INVALID")
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            scope = self._require_scope(session, workspace.workspace_id, scope_id)
            if scope is None:
                raise ResearchWorkspaceAccessError("RESEARCH_SCOPE_NOT_FOUND")
            if context_summary is not None:
                scope.context_summary = _bounded(context_summary, 16_000, fallback="")
            if action == "interrupt":
                if scope.status == "completed":
                    raise ResearchWorkspaceConflictError("RESEARCH_SCOPE_TRANSITION_INVALID")
                scope.status = "interrupted"
                if workspace.active_scope_id == scope.scope_id:
                    workspace.active_scope_id = self._fallback_scope_id(session, workspace, scope)
            elif action in {"resume", "switch"}:
                if scope.status == "completed":
                    raise ResearchWorkspaceConflictError("RESEARCH_SCOPE_TRANSITION_INVALID")
                scope.status = "active"
                workspace.active_scope_id = scope.scope_id
            elif action == "complete":
                scope.status = "completed"
                if workspace.active_scope_id == scope.scope_id:
                    workspace.active_scope_id = self._fallback_scope_id(session, workspace, scope)
            scope.version += 1
            scope.updated_at = utcnow_aware()
            self._touch_workspace(workspace)
            session.add(scope)
            session.add(workspace)
            session.commit()
            session.refresh(scope)
            return _scope_dict(scope, workspace.active_scope_id)

    async def store_memory(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        scope_id: str | None,
        tier: str,
        content: str,
        importance: float = 0.5,
    ) -> Mapping[str, Any]:
        normalized = _bounded(content, 24_000)
        if tier not in {"short_term", "long_term"}:
            raise ResearchWorkspaceConflictError("RESEARCH_MEMORY_TIER_INVALID")
        vector, embedding_status = await self._embed(normalized)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        actor_id = _actor_id(actor_user_id)
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            self._require_scope(session, workspace.workspace_id, scope_id)
            memory = session.exec(select(ResearchMemory).where(
                ResearchMemory.workspace_id == workspace.workspace_id,
                ResearchMemory.content_hash == digest,
            )).first()
            if memory is None:
                memory = ResearchMemory(
                    workspace_id=workspace.workspace_id,
                    scope_id=scope_id,
                    tier=tier,
                    content=normalized,
                    content_hash=digest,
                    keywords=sorted(_terms(normalized))[:64],
                    importance=max(0.0, min(1.0, float(importance))),
                    embedding=vector,
                    embedding_provider=(getattr(self._embedding_provider, "provider_name", "") if vector else ""),
                    embedding_model=(getattr(self._embedding_provider, "model_name", "") if vector else ""),
                    embedding_dimensions=len(vector or []),
                    created_by=actor_id,
                )
            else:
                memory.last_accessed_at = utcnow_aware()
                memory.importance = max(memory.importance, max(0.0, min(1.0, float(importance))))
                if vector and not memory.embedding:
                    memory.embedding = vector
                    memory.embedding_provider = getattr(self._embedding_provider, "provider_name", "")
                    memory.embedding_model = getattr(self._embedding_provider, "model_name", "")
                    memory.embedding_dimensions = len(vector)
            session.add(memory)
            if tier == "short_term":
                workspace.short_term_summary = normalized
            self._touch_workspace(workspace)
            session.add(workspace)
            session.commit()
            session.refresh(memory)
            return {**_memory_dict(memory), "embedding_status": embedding_status}

    async def search_memory(
        self,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
        query: str,
        limit: int = 8,
    ) -> Mapping[str, Any]:
        bounded_limit = min(20, max(1, int(limit)))
        query_vector, _ = await self._embed(_bounded(query, 2_000))
        with self._session_factory() as session:
            workspace = self._require_workspace(session, workspace_id=workspace_id, course_id=course_id, actor_user_id=actor_user_id)
            pgvector_query_unavailable = False
            if query_vector and session.bind is not None and session.bind.dialect.name == "postgresql":
                try:
                    return self._postgres_vector_search(
                        session, workspace_id=workspace.workspace_id,
                        vector=query_vector, limit=bounded_limit,
                    )
                except SQLAlchemyError:
                    # PostgreSQL and pgvector are independently upgraded in
                    # deployment.  If the extension/operator is unavailable,
                    # clear the failed transaction and keep private memory
                    # recall usable through deterministic keyword ranking.
                    session.rollback()
                    pgvector_query_unavailable = True
            memories = list(session.exec(select(ResearchMemory).where(
                ResearchMemory.workspace_id == workspace.workspace_id,
            )).all())
            query_terms = _terms(query)
            scored: list[tuple[float, ResearchMemory]] = []
            used_vector = False
            for memory in memories:
                score = _keyword_score(query_terms, set(memory.keywords or []))
                if not pgvector_query_unavailable and query_vector and memory.embedding and len(query_vector) == len(memory.embedding):
                    score = _cosine(query_vector, memory.embedding)
                    used_vector = True
                score = score * 0.9 + memory.importance * 0.1
                scored.append((score, memory))
            scored.sort(key=lambda pair: (pair[0], pair[1].last_accessed_at), reverse=True)
            selected = scored[:bounded_limit]
            now = utcnow_aware()
            for _, memory in selected:
                memory.last_accessed_at = now
                session.add(memory)
            session.commit()
            return {
                "retrieval_mode": "vector" if used_vector else "keyword",
                "degraded": not used_vector,
                "degraded_reason": "pgvector_query_unavailable" if pgvector_query_unavailable else None,
                "items": [
                    {**_memory_dict(memory), "score": round(float(score), 6)}
                    for score, memory in selected
                ],
            }

    async def _embed(self, text_value: str) -> tuple[list[float] | None, str]:
        if self._embedding_provider is None:
            return None, "unavailable"
        try:
            vectors = await asyncio.to_thread(self._embedding_provider.embed, [text_value])
            vector = [float(value) for value in vectors[0]]
            if not vector or any(not math.isfinite(value) for value in vector):
                raise ValueError("invalid embedding vector")
            return vector, "available"
        except Exception:  # noqa: BLE001 - memory remains usable through keyword degradation
            return None, "degraded"

    def _postgres_vector_search(
        self,
        session: Session,
        *,
        workspace_id: str,
        vector: list[float],
        limit: int,
    ) -> Mapping[str, Any]:
        literal = "[" + ",".join(format(value, ".12g") for value in vector) + "]"
        rows = session.execute(text("""
            SELECT memory_id, scope_id, tier, content, importance,
                   embedding_provider, embedding_model, embedding_dimensions,
                   created_at, last_accessed_at,
                   1 - (embedding <=> CAST(:query_vector AS vector)) AS score
              FROM research_memories
             WHERE workspace_id = :workspace_id
               AND embedding IS NOT NULL
               AND embedding_dimensions = :dimensions
             ORDER BY embedding <=> CAST(:query_vector AS vector)
             LIMIT :limit
        """), {
            "query_vector": literal,
            "workspace_id": workspace_id,
            "dimensions": len(vector),
            "limit": limit,
        }).mappings().all()
        return {
            "retrieval_mode": "vector",
            "degraded": False,
            "items": [
                {
                    "memory_id": row["memory_id"],
                    "scope_id": row["scope_id"],
                    "tier": row["tier"],
                    "content": row["content"],
                    "importance": row["importance"],
                    "embedding_provider": row["embedding_provider"],
                    "embedding_model": row["embedding_model"],
                    "embedding_dimensions": row["embedding_dimensions"],
                    "created_at": _iso(row["created_at"]),
                    "last_accessed_at": _iso(row["last_accessed_at"]),
                    "score": round(float(row["score"] or 0.0), 6),
                }
                for row in rows
            ],
        }

    @staticmethod
    def _touch_workspace(workspace: ResearchWorkspace) -> None:
        workspace.version += 1
        workspace.updated_at = utcnow_aware()

    @staticmethod
    def _require_workspace(
        session: Session,
        *,
        workspace_id: str,
        course_id: int,
        actor_user_id: str,
    ) -> ResearchWorkspace:
        workspace = session.exec(select(ResearchWorkspace).where(
            ResearchWorkspace.workspace_id == workspace_id,
            ResearchWorkspace.course_id == int(course_id),
            ResearchWorkspace.owner_user_id == _actor_id(actor_user_id),
        )).first()
        if workspace is None:
            raise ResearchWorkspaceAccessError("RESEARCH_WORKSPACE_SCOPE_DENIED")
        return workspace

    @staticmethod
    def _require_scope(
        session: Session,
        workspace_id: str,
        scope_id: str | None,
    ) -> ResearchScope | None:
        if not scope_id:
            return None
        scope = session.exec(select(ResearchScope).where(
            ResearchScope.workspace_id == workspace_id,
            ResearchScope.scope_id == scope_id,
        )).first()
        if scope is None:
            raise ResearchWorkspaceAccessError("RESEARCH_SCOPE_NOT_FOUND")
        return scope

    @staticmethod
    def _fallback_scope_id(
        session: Session,
        workspace: ResearchWorkspace,
        current: ResearchScope,
    ) -> str | None:
        if current.parent_scope_id:
            parent = session.exec(select(ResearchScope).where(
                ResearchScope.workspace_id == workspace.workspace_id,
                ResearchScope.scope_id == current.parent_scope_id,
                ResearchScope.status != "completed",
            )).first()
            if parent is not None:
                return parent.scope_id
        root = session.exec(select(ResearchScope).where(
            ResearchScope.workspace_id == workspace.workspace_id,
            ResearchScope.parent_scope_id.is_(None),
            ResearchScope.status != "completed",
        ).order_by(ResearchScope.created_at.asc())).first()
        return root.scope_id if root else None


def _actor_id(value: str | int) -> int:
    try:
        actor_id = int(value)
    except (TypeError, ValueError) as error:
        raise ResearchWorkspaceAccessError("RESEARCH_WORKSPACE_ACTOR_INVALID") from error
    if actor_id <= 0:
        raise ResearchWorkspaceAccessError("RESEARCH_WORKSPACE_ACTOR_INVALID")
    return actor_id


def _bounded(value: Any, limit: int, *, fallback: str | None = None) -> str:
    normalized = str(value or "").strip()
    if not normalized and fallback is not None:
        return str(fallback)[:limit]
    if not normalized:
        raise ResearchWorkspaceConflictError("RESEARCH_WORKSPACE_CONTENT_REQUIRED")
    return normalized[:limit]


def _check_version(actual: int, expected: int | None) -> None:
    if expected is not None and int(expected) != actual:
        raise ResearchWorkspaceConflictError("RESEARCH_WORKSPACE_VERSION_CONFLICT")


def _tags(values: Sequence[str] | None) -> list[str]:
    return list(dict.fromkeys(
        str(value).strip()[:64]
        for value in (values or [])
        if str(value).strip()
    ))[:20]


def _terms(value: str) -> set[str]:
    return {token.casefold() for token in _WORD_PATTERN.findall(str(value or ""))}


def _keyword_score(query_terms: set[str], memory_terms: set[str]) -> float:
    if not query_terms or not memory_terms:
        return 0.0
    return len(query_terms & memory_terms) / len(query_terms | memory_terms)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _workspace_dict(workspace: ResearchWorkspace) -> dict[str, Any]:
    return {
        "workspace_id": workspace.workspace_id,
        "course_id": workspace.course_id,
        "owner_user_id": workspace.owner_user_id,
        "title": workspace.title,
        "status": workspace.status,
        "active_scope_id": workspace.active_scope_id,
        "short_term_summary": workspace.short_term_summary,
        "context_budget_tokens": workspace.context_budget_tokens,
        "data_policy_version": workspace.data_policy_version,
        "version": workspace.version,
        "created_at": _iso(workspace.created_at),
        "updated_at": _iso(workspace.updated_at),
    }


def _todo_dict(todo: ResearchTodo) -> dict[str, Any]:
    return {
        "todo_id": todo.todo_id,
        "scope_id": todo.scope_id,
        "title": todo.title,
        "description": todo.description,
        "priority": todo.priority,
        "position": todo.position,
        "status": todo.status,
        "version": todo.version,
        "created_at": _iso(todo.created_at),
        "updated_at": _iso(todo.updated_at),
        "completed_at": _iso(todo.completed_at),
    }


def _note_dict(note: ResearchNote) -> dict[str, Any]:
    return {
        "note_id": note.note_id,
        "scope_id": note.scope_id,
        "title": note.title,
        "content": note.content,
        "tags": list(note.tags or []),
        "version": note.version,
        "created_at": _iso(note.created_at),
        "updated_at": _iso(note.updated_at),
    }


def _scope_dict(scope: ResearchScope, active_scope_id: str | None) -> dict[str, Any]:
    return {
        "scope_id": scope.scope_id,
        "parent_scope_id": scope.parent_scope_id,
        "title": scope.title,
        "objective": scope.objective,
        "status": scope.status,
        "context_summary": scope.context_summary,
        "scope_thread_id": scope.scope_thread_id,
        "version": scope.version,
        "is_active": scope.scope_id == active_scope_id,
        "created_at": _iso(scope.created_at),
        "updated_at": _iso(scope.updated_at),
    }


def _memory_dict(memory: ResearchMemory, *, include_content: bool = True) -> dict[str, Any]:
    payload = {
        "memory_id": memory.memory_id,
        "scope_id": memory.scope_id,
        "tier": memory.tier,
        "importance": memory.importance,
        "embedding_provider": memory.embedding_provider,
        "embedding_model": memory.embedding_model,
        "embedding_dimensions": memory.embedding_dimensions,
        "created_at": _iso(memory.created_at),
        "last_accessed_at": _iso(memory.last_accessed_at),
    }
    if include_content:
        payload["content"] = memory.content
    return payload


def _iso(value) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


__all__ = [
    "LazyEmbeddingProvider",
    "ResearchWorkspaceAccessError",
    "ResearchWorkspaceConflictError",
    "ResearchWorkspaceError",
    "SqlResearchWorkspaceProvider",
]
