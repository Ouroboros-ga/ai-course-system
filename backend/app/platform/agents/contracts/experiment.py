"""Experiment and visualization ports: course-scoped read-only access.

Both ports are read-only and isolated by ``course_id``. ``ExperimentPort``
reads experiment definitions and latest student attempts; ``VisualizationPort``
reads published JSAV-style visualization plans.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ExperimentPort(Protocol):
    """课程实验只读端口：按 course_id 隔离查询实验定义与最近提交。"""

    async def list_experiments(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...
    async def get_latest_attempt(self, *, course_id: str, student_id: str, experiment_id: str) -> Mapping[str, Any] | None: ...


class VisualizationPort(Protocol):
    """算法可视化只读端口：按 course_id 隔离查询已发布可视化计划。"""

    async def list_published_plans(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...
    async def get_plan(self, *, course_id: str, plan_id: str) -> Mapping[str, Any] | None: ...


__all__ = ["ExperimentPort", "VisualizationPort"]
