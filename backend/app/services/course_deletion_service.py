"""Owner-only hard deletion for one complete course data scope."""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from sqlalchemy import Table, and_, delete, or_, select, tuple_
from sqlmodel import SQLModel, Session

from app.core.config import settings
from app.models.course_model import Course, StudentEnrollment
from app.models.knowledge_bundle_model import GraphRagRun, GraphRagRunStatus
from app.models.storage_object_ref_model import StorageObjectRef
from app.models.task_model import TaskRecord
from app.services.object_storage import ObjectStorageProvider, get_object_storage


logger = logging.getLogger(__name__)

ACTIVE_TASK_STATUSES = {"pending", "queued", "running", "retrying", "processing"}
ACTIVE_GRAPH_RUN_STATUSES = {
    GraphRagRunStatus.QUEUED,
    GraphRagRunStatus.EXPORTING,
    GraphRagRunStatus.EXTRACTING,
    GraphRagRunStatus.CLASSIFYING,
    GraphRagRunStatus.RECONCILING,
}
OBJECT_KEY_COLUMNS = {
    "object_key",
    "file_path",
    "source_file_path",
    "pdf_file_path",
}
VIRTUAL_REFERENCES = (
    ("task_events", "task_id", "tasks", "task_id"),
    ("task_resource_links", "task_id", "tasks", "task_id"),
    ("idempotency_keys", "task_id", "tasks", "task_id"),
    ("resource_tags", "resource_id", "resource_items", "resource_id"),
    ("agent_action_decisions", "proposal_id", "agent_action_proposals", "proposal_id"),
)


class CourseDeletionError(RuntimeError):
    def __init__(self, code: str, *, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


@dataclass
class CourseDeletionReport:
    course_id: int
    title: str
    affected_students: int
    deleted_rows: dict[str, int] = field(default_factory=dict)
    deleted_object_keys: list[str] = field(default_factory=list)
    preserved_shared_object_keys: list[str] = field(default_factory=list)
    deleted_index_directories: list[str] = field(default_factory=list)
    cleanup_errors: list[str] = field(default_factory=list)

    @property
    def cleanup_complete(self) -> bool:
        return not self.cleanup_errors

    def to_dict(self) -> dict:
        return {
            "deleted_course_id": self.course_id,
            "affected_students": self.affected_students,
            "deleted_rows": self.deleted_rows,
            "deleted_object_count": len(self.deleted_object_keys),
            "preserved_shared_object_count": len(self.preserved_shared_object_keys),
            "deleted_index_directories": self.deleted_index_directories,
            "cleanup_complete": self.cleanup_complete,
            "cleanup_errors": self.cleanup_errors,
        }


class CourseDeletionService:
    def delete(
        self,
        session: Session,
        *,
        course_id: int,
        expected_title: str,
        storage: ObjectStorageProvider | None = None,
    ) -> CourseDeletionReport:
        course = session.get(Course, course_id)
        if course is None:
            raise CourseDeletionError("COURSE_NOT_FOUND")
        if expected_title.strip() != course.title.strip():
            raise CourseDeletionError("COURSE_DELETE_CONFIRMATION_MISMATCH")
        course_title = course.title
        self._ensure_idle(session, course_id)

        affected_students = len(session.exec(
            select(StudentEnrollment.id).where(
                StudentEnrollment.course_id == course_id,
                StudentEnrollment.is_active == True,  # noqa: E712
            )
        ).all())
        conditions = self._course_conditions(course_id)
        candidate_keys = self._collect_object_keys(session, conditions)
        deleted_rows = self._delete_scoped_rows(session, conditions)
        remaining_keys = self._find_remaining_object_references(session, candidate_keys)
        unreferenced_keys = sorted(candidate_keys - remaining_keys)
        for record in session.exec(
            select(StorageObjectRef).where(StorageObjectRef.object_key.in_(unreferenced_keys))
        ).all() if unreferenced_keys else []:
            session.delete(record)
        session.commit()

        report = CourseDeletionReport(
            course_id=course_id,
            title=course_title,
            affected_students=affected_students,
            deleted_rows=deleted_rows,
            preserved_shared_object_keys=sorted(remaining_keys),
        )
        self._delete_objects(storage or get_object_storage(), unreferenced_keys, report)
        self._delete_knowledge_directories(course_id, report)
        return report

    @staticmethod
    def _ensure_idle(session: Session, course_id: int) -> None:
        active_tasks = session.exec(select(TaskRecord).where(
            TaskRecord.course_id == course_id,
            TaskRecord.status.in_(ACTIVE_TASK_STATUSES),
        )).all()
        active_runs = session.exec(select(GraphRagRun).where(
            GraphRagRun.course_id == course_id,
            GraphRagRun.status.in_(ACTIVE_GRAPH_RUN_STATUSES),
        )).all()
        if active_tasks or active_runs:
            raise CourseDeletionError(
                "COURSE_DELETE_TASKS_ACTIVE",
                details={
                    "task_ids": [task.task_id for task in active_tasks],
                    "graphrag_run_ids": [run.run_id for run in active_runs],
                },
            )

    @staticmethod
    def _course_conditions(course_id: int) -> dict[str, object]:
        tables = SQLModel.metadata.tables
        conditions: dict[str, object] = {}
        if "courses" not in tables:
            raise CourseDeletionError("COURSE_DELETE_SCHEMA_INCOMPLETE")
        conditions["courses"] = tables["courses"].c.id == course_id
        for table in tables.values():
            if "course_id" in table.c:
                conditions[table.name] = table.c.course_id == course_id

        processed: set[tuple[str, str, str]] = set()
        changed = True
        while changed:
            changed = False
            for table in tables.values():
                for constraint in table.foreign_key_constraints:
                    elements = list(constraint.elements)
                    if not elements:
                        continue
                    parent = elements[0].column.table
                    key = (table.name, parent.name, constraint.name or repr(elements))
                    if key in processed or parent.name not in conditions:
                        continue
                    processed.add(key)
                    local_columns = [element.parent for element in elements]
                    parent_columns = [element.column for element in elements]
                    parent_query = select(*parent_columns).where(conditions[parent.name])
                    relation_condition = (
                        local_columns[0].in_(parent_query)
                        if len(local_columns) == 1
                        else tuple_(*local_columns).in_(parent_query)
                    )
                    conditions[table.name] = (
                        or_(conditions[table.name], relation_condition)
                        if table.name in conditions else relation_condition
                    )
                    changed = True
            for child_name, child_column, parent_name, parent_column in VIRTUAL_REFERENCES:
                key = (child_name, parent_name, child_column)
                if key in processed or parent_name not in conditions:
                    continue
                child = tables.get(child_name)
                parent = tables.get(parent_name)
                if child is None or parent is None:
                    continue
                processed.add(key)
                relation_condition = child.c[child_column].in_(
                    select(parent.c[parent_column]).where(conditions[parent_name])
                )
                conditions[child_name] = (
                    or_(conditions[child_name], relation_condition)
                    if child_name in conditions else relation_condition
                )
                changed = True
        return conditions

    @staticmethod
    def _collect_object_keys(session: Session, conditions: dict[str, object]) -> set[str]:
        keys: set[str] = set()
        for table_name, condition in conditions.items():
            table = SQLModel.metadata.tables[table_name]
            for column in _object_columns(table):
                for value in session.execute(
                    select(column).where(condition, column.is_not(None), column != "")
                ).scalars():
                    if _is_object_key(str(value)):
                        keys.add(str(value).replace("\\", "/"))
        return keys

    @staticmethod
    def _find_remaining_object_references(session: Session, candidates: set[str]) -> set[str]:
        if not candidates:
            return set()
        referenced: set[str] = set()
        values = sorted(candidates)
        for table in SQLModel.metadata.tables.values():
            if table.name == StorageObjectRef.__tablename__:
                continue
            for column in _object_columns(table):
                for offset in range(0, len(values), 200):
                    referenced.update(str(value).replace("\\", "/") for value in session.execute(
                        select(column).distinct().where(column.in_(values[offset:offset + 200]))
                    ).scalars())
        return referenced & candidates

    @staticmethod
    def _delete_scoped_rows(session: Session, conditions: dict[str, object]) -> dict[str, int]:
        counts: dict[str, int] = {}
        ordered = list(reversed(SQLModel.metadata.sorted_tables))
        for table in ordered:
            condition = conditions.get(table.name)
            if condition is None:
                continue
            result = session.execute(delete(table).where(condition))
            if result.rowcount:
                counts[table.name] = int(result.rowcount)
        return counts

    @staticmethod
    def _delete_objects(
        storage: ObjectStorageProvider,
        object_keys: Iterable[str],
        report: CourseDeletionReport,
    ) -> None:
        for object_key in object_keys:
            try:
                storage.delete(object_key)
                report.deleted_object_keys.append(object_key)
            except Exception as exc:  # pragma: no cover - provider-specific failure
                logger.exception("Could not delete course object %s", object_key)
                report.cleanup_errors.append(f"object:{object_key}:{type(exc).__name__}")

    @staticmethod
    def _delete_knowledge_directories(course_id: int, report: CourseDeletionReport) -> None:
        seen: set[Path] = set()
        for configured_root in (settings.GRAPHRAG_STORAGE_ROOT, settings.VECTOR_STORE_ROOT):
            root = Path(configured_root).resolve()
            target = (root / "courses" / str(course_id)).resolve()
            if target in seen:
                continue
            seen.add(target)
            if root not in target.parents:
                report.cleanup_errors.append(f"index:{target}:INVALID_STORAGE_PATH")
                continue
            try:
                if target.exists():
                    shutil.rmtree(target)
                    report.deleted_index_directories.append(str(target))
            except OSError as exc:
                logger.exception("Could not delete course knowledge directory %s", target)
                report.cleanup_errors.append(f"index:{target}:{type(exc).__name__}")


def _object_columns(table: Table) -> list:
    return [
        column
        for column in table.c
        if column.name in OBJECT_KEY_COLUMNS or column.name.endswith("_object_key")
    ]


def _is_object_key(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or "\x00" in normalized:
        return False
    if os.path.isabs(value) or (len(normalized) > 1 and normalized[1] == ":"):
        return False
    return all(part not in {"", ".", ".."} for part in normalized.split("/"))


course_deletion_service = CourseDeletionService()
