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


class ExperimentDispatchPort(Protocol):
    """Create only teacher-confirmed experiment recommendation proposals.

    The port intentionally has no operation for attempts, runs, source code,
    or sandbox execution.  Approval is handled by the existing proposal state
    machine; its worker will revalidate current course state before creating a
    single visible recommendation.
    """

    async def list_recommendable_experiments(
        self, *, course_id: str, node_id: str | None = None, limit: int = 10,
    ) -> list[Mapping[str, Any]]: ...

    async def propose_recommendation(
        self,
        *,
        course_id: str,
        student_id: str,
        experiment_id: str,
        outline_node_id: str | None,
        trace_id: str,
        session_id: str,
    ) -> Mapping[str, Any]: ...


class VisualizationPort(Protocol):
    """算法可视化只读端口：按 course_id 隔离查询已发布可视化计划。"""

    async def list_published_plans(self, *, course_id: str, node_id: str | None = None, limit: int = 10) -> list[Mapping[str, Any]]: ...
    async def get_plan(self, *, course_id: str, plan_id: str) -> Mapping[str, Any] | None: ...


__all__ = ["ExperimentDispatchPort", "ExperimentPort", "VisualizationPort"]
