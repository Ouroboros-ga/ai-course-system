"""Persistence Port for the isolated ResearchAgent workspace domain."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class ResearchWorkspacePort(Protocol):
    async def get_or_create_workspace(
        self, *, course_id: int, actor_user_id: str, title: str,
    ) -> Mapping[str, Any]: ...

    async def get_workspace_snapshot(
        self, *, workspace_id: str, course_id: int, actor_user_id: str,
    ) -> Mapping[str, Any]: ...

    async def create_todo(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def update_todo(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def save_note(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def create_scope(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def transition_scope(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def store_memory(self, **kwargs: Any) -> Mapping[str, Any]: ...

    async def search_memory(self, **kwargs: Any) -> Mapping[str, Any]: ...


__all__ = ["ResearchWorkspacePort"]

