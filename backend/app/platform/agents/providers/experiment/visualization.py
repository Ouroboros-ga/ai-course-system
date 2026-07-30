"""阶段9 算法可视化只读端口实现。

按 course_id 严格隔离查询已发布可视化计划；绝不返回跨课程数据。
仅 PUBLISHED 状态计划对学生可见；draft/validated/rejected/archived 被过滤。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from app.models.visualization_model import (
    VisualizationPlanRecord,
    VisualizationStatus,
)
from app.models.database import engine

logger = logging.getLogger(__name__)


def _plan_to_dict(plan: VisualizationPlanRecord) -> dict[str, Any]:
    """转换为只读字典；保留算法元数据与 plan_id 用于前端回放。"""
    return {
        "plan_id": plan.plan_id,
        "course_id": plan.course_id,
        "node_id": plan.node_id,
        "algorithm_id": plan.algorithm_id,
        "algorithm_name": plan.algorithm_name,
        "plan_version": plan.plan_version,
        "return_anchor_node_id": plan.return_anchor_node_id,
        "return_anchor_label": plan.return_anchor_label,
        "status": plan.status.value if hasattr(plan.status, "value") else str(plan.status),
        "published_at": plan.published_at.isoformat() if plan.published_at else None,
    }


def make_session_scoped_visualization_port(session_factory: Callable[[], Session]):
    """构造一个 session 作用域的 VisualizationPort 实现。"""

    class SessionScopedVisualizationPort:
        async def list_published_plans(
            self,
            *,
            course_id: str,
            node_id: str | None = None,
            limit: int = 10,
        ) -> list[Mapping[str, Any]]:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return []
            session = session_factory()
            try:
                stmt = (
                    select(VisualizationPlanRecord)
                    .where(
                        VisualizationPlanRecord.course_id == course_id_int,
                        VisualizationPlanRecord.status == VisualizationStatus.PUBLISHED,
                    )
                    .order_by(VisualizationPlanRecord.published_at.desc())
                    .limit(max(1, min(limit, 50)))
                )
                rows = session.exec(stmt).all()
                result = []
                for plan in rows:
                    if node_id is not None:
                        try:
                            node_id_int = int(node_id)
                            if plan.node_id != node_id_int:
                                continue
                        except (TypeError, ValueError):
                            pass
                    result.append(_plan_to_dict(plan))
                return result
            except Exception as error:  # noqa: BLE001
                logger.warning("VisualizationPort.list_published_plans failed: %s: %s", type(error).__name__, error)
                return []
            finally:
                session.close()

        async def get_plan(self, *, course_id: str, plan_id: str) -> Mapping[str, Any] | None:
            try:
                course_id_int = int(course_id)
            except (TypeError, ValueError):
                return None
            session = session_factory()
            try:
                stmt = (
                    select(VisualizationPlanRecord)
                    .where(
                        VisualizationPlanRecord.course_id == course_id_int,
                        VisualizationPlanRecord.plan_id == plan_id,
                        VisualizationPlanRecord.status == VisualizationStatus.PUBLISHED,
                    )
                    .limit(1)
                )
                plan = session.exec(stmt).first()
                return _plan_to_dict(plan) if plan else None
            except Exception as error:  # noqa: BLE001
                logger.warning("VisualizationPort.get_plan failed: %s: %s", type(error).__name__, error)
                return None
            finally:
                session.close()

    return SessionScopedVisualizationPort()
