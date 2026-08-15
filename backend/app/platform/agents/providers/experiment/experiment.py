"""阶段9 课程实验只读端口实现。

按 course_id 严格隔离查询实验定义与最近提交；绝不返回跨课程数据。
仅 published 状态实验对学生可见；draft/archived 被过滤。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
)
from app.models.access_control_model import CourseCapability
from app.models.database import engine

logger = logging.getLogger(__name__)


def _definition_to_dict(exp: ExperimentDefinition) -> dict[str, Any]:
    """转换为只读字典；剥离 statement_object_key 等内部字段。"""
    return {
        "experiment_id": exp.experiment_id,
        "course_id": exp.course_id,
        "title": exp.title,
        "description": exp.description,
        "language_whitelist": list(exp.language_whitelist or []),
        "default_version_id": exp.default_version_id,
        "publish_status": exp.publish_status.value if hasattr(exp.publish_status, "value") else str(exp.publish_status),
        "knowledge_node_ids": list(exp.knowledge_node_ids or []),
        "max_attempts": exp.max_attempts,
        "cooldown_minutes": exp.cooldown_minutes,
    }


def _attempt_to_dict(att: ExperimentAttempt) -> dict[str, Any]:
    """转换为只读字典；绝不返回 source_code 或 solution。"""
    return {
        "attempt_id": att.attempt_id,
        "experiment_id": att.experiment_id,
        "version_id": att.version_id,
        "course_id": att.course_id,
        "student_id": att.student_id,
        "status": att.status.value if hasattr(att.status, "value") else str(att.status),
        "started_at": att.started_at.isoformat() if att.started_at else None,
        "submitted_at": att.submitted_at.isoformat() if att.submitted_at else None,
        "finalized_at": att.finalized_at.isoformat() if att.finalized_at else None,
        "final_score": att.final_score,
        "passed": att.passed,
        "evidence_id": att.evidence_id,
    }


def make_session_scoped_experiment_port(session_factory: Callable[[], Session]):
    """构造一个 session 作用域的 ExperimentPort 实现。"""

    class SessionScopedExperimentPort:
        async def list_experiments(
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
                capability = session.exec(
                    select(CourseCapability).where(CourseCapability.course_id == course_id_int)
                ).first()
                if capability is None or not capability.experiment or not capability.coding_sandbox:
                    return []
                stmt = (
                    select(ExperimentDefinition)
                    .where(
                        ExperimentDefinition.course_id == course_id_int,
                        ExperimentDefinition.publish_status == ExperimentPublishStatus.PUBLISHED,
                    )
                    .order_by(ExperimentDefinition.created_at.desc())
                    .limit(max(1, min(limit, 50)))
                )
                rows = session.exec(stmt).all()
                result = []
                for exp in rows:
                    item = _definition_to_dict(exp)
                    if node_id is not None:
                        try:
                            node_id_int = int(node_id)
                            if node_id_int not in (exp.knowledge_node_ids or []):
                                continue
                        except (TypeError, ValueError):
                            pass
                    result.append(item)
                return result
            except Exception as error:  # noqa: BLE001
                logger.warning("ExperimentPort.list_experiments failed: %s: %s", type(error).__name__, error)
                return []
            finally:
                session.close()

        async def get_latest_attempt(
            self,
            *,
            course_id: str,
            student_id: str,
            experiment_id: str,
        ) -> Mapping[str, Any] | None:
            try:
                course_id_int = int(course_id)
                student_id_int = int(student_id)
            except (TypeError, ValueError):
                return None
            session = session_factory()
            try:
                capability = session.exec(
                    select(CourseCapability).where(CourseCapability.course_id == course_id_int)
                ).first()
                if capability is None or not capability.experiment or not capability.coding_sandbox:
                    return None
                stmt = (
                    select(ExperimentAttempt)
                    .where(
                        ExperimentAttempt.course_id == course_id_int,
                        ExperimentAttempt.student_id == student_id_int,
                        ExperimentAttempt.experiment_id == experiment_id,
                    )
                    .order_by(ExperimentAttempt.started_at.desc())
                    .limit(1)
                )
                att = session.exec(stmt).first()
                return _attempt_to_dict(att) if att else None
            except Exception as error:  # noqa: BLE001
                logger.warning("ExperimentPort.get_latest_attempt failed: %s: %s", type(error).__name__, error)
                return None
            finally:
                session.close()

    return SessionScopedExperimentPort()
