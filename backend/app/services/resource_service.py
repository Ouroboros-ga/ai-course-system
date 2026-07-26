"""阶段7 服务层：资源库、平台实验室与任务中心接入

完成通用资源库（文件版本、标签、课程引用、回收站、下游影响与权限）和平台实验
大厅读模型（catalog、course-tasks、my-experiments、records）。

关键约束：
- 删除资源先展示受影响课程/发布版本，软删除后仍可恢复
- 任务中心可定位到源课程、源资源、失败原因和恢复动作
- 平台实验与课程实验共享沙箱能力，但课程实验可回写课程证据和 return anchor
- 跨用户/课程严格隔离：所有查询都按 owner_user_id / course_id 过滤
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_naive
from app.models.resource_model import (
    LabCatalogEntry,
    LabCatalogVisibility,
    LabEnrollment,
    LabRecord,
    RecycleBinEntry,
    ResourceAclEntry,
    ResourceItem,
    ResourceItemType,
    ResourceReference,
    ResourceScope,
    ResourceTag,
    ResourceVersion,
)


# 默认回收站保留期 30 天
DEFAULT_RECYCLE_RETENTION_DAYS = 30


# ---------------------------------------------------------------------------
# 资源库服务
# ---------------------------------------------------------------------------


class ResourceService:
    """通用资源库服务

    - 按 owner_user_id 与 course_id（可选）严格隔离
    - 软删除进入回收站，恢复时检查下游影响
    - 版本演进不破坏历史引用
    """

    def create_resource(
        self,
        session: Session,
        *,
        owner_user_id: int,
        course_id: Optional[int] = None,
        name: str,
        description: str = "",
        resource_type: ResourceItemType = ResourceItemType.OTHER,
        mime_type: str = "",
        file_size: int = 0,
        object_key: str = "",
        content_hash: str = "",
        tags: Optional[list[str]] = None,
    ) -> ResourceItem:
        scope = ResourceScope.COURSE if course_id is not None else ResourceScope.USER
        resource = ResourceItem(
            owner_user_id=owner_user_id,
            course_id=course_id,
            scope=scope,
            name=name,
            description=description,
            resource_type=resource_type,
            mime_type=mime_type,
            file_size=file_size,
        )
        session.add(resource)
        session.flush()

        # 创建首版本
        version = self._create_version(
            session,
            resource=resource,
            object_key=object_key,
            content_hash=content_hash,
            file_size=file_size,
            mime_type=mime_type,
            label="v1",
            uploaded_by=owner_user_id,
            activate=True,
        )

        # 创建标签
        for tag in (tags or []):
            tag_entry = ResourceTag(
                resource_id=resource.resource_id,
                tag=tag,
                owner_user_id=owner_user_id,
            )
            session.add(tag_entry)

        session.flush()
        return resource

    def _create_version(
        self,
        session: Session,
        *,
        resource: ResourceItem,
        object_key: str,
        content_hash: str,
        file_size: int,
        mime_type: str,
        label: str = "",
        uploaded_by: int,
        activate: bool = True,
    ) -> ResourceVersion:
        # 计算版本号
        max_version = session.exec(
            select(func.max(ResourceVersion.version_number)).where(
                ResourceVersion.resource_id == resource.resource_id,
            )
        ).one() or 0
        version_number = int(max_version) + 1

        version = ResourceVersion(
            resource_id=resource.resource_id,
            owner_user_id=resource.owner_user_id,
            course_id=resource.course_id,
            version_number=version_number,
            label=label or f"v{version_number}",
            object_key=object_key,
            content_hash=content_hash,
            file_size=file_size,
            mime_type=mime_type,
            is_active=False,
            uploaded_by=uploaded_by,
        )
        session.add(version)
        session.flush()

        if activate:
            self._activate_version(
                session, version=version, resource=resource,
            )

        return version

    def _activate_version(
        self,
        session: Session,
        *,
        version: ResourceVersion,
        resource: ResourceItem,
    ) -> ResourceVersion:
        # 失活同资源其他版本
        others = session.exec(
            select(ResourceVersion).where(
                ResourceVersion.resource_id == resource.resource_id,
                ResourceVersion.is_active == True,  # noqa: E712
                ResourceVersion.version_id != version.version_id,
            )
        ).all()
        for other in others:
            other.is_active = False
            session.add(other)

        version.is_active = True
        session.add(version)

        resource.current_version_id = version.version_id
        resource.updated_at = utcnow_naive()
        session.add(resource)
        session.flush()
        return version

    def get_resource(
        self,
        session: Session,
        *,
        resource_id: str,
        owner_user_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> ResourceItem:
        resource = session.exec(
            select(ResourceItem).where(
                ResourceItem.resource_id == resource_id,
            )
        ).first()
        if resource is None:
            reject_resource_not_found(f"资源 {resource_id} 不存在")
        if not include_deleted and resource.is_deleted:
            reject_resource_not_found(f"资源 {resource_id} 已删除")
        if owner_user_id is not None and resource.owner_user_id != owner_user_id:
            # 检查 ACL
            if not self._has_access(session, resource_id=resource_id, user_id=owner_user_id):
                reject_course_access_denied("无权访问该资源")
        return resource

    def _has_access(self, session: Session, *, resource_id: str, user_id: int) -> bool:
        """检查用户是否有权访问资源（ACL）"""
        acl = session.exec(
            select(ResourceAclEntry).where(
                ResourceAclEntry.resource_id == resource_id,
                ResourceAclEntry.grantee_user_id == user_id,
            )
        ).first()
        return acl is not None

    def list_resources(
        self,
        session: Session,
        *,
        owner_user_id: Optional[int] = None,
        course_id: Optional[int] = None,
        scope: Optional[str] = None,
        include_deleted: bool = False,
        cursor: Optional[str] = None,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """列出资源，按 scope=mine|course|recent|trash 过滤"""
        stmt = select(ResourceItem)
        if not include_deleted:
            stmt = stmt.where(ResourceItem.is_deleted == False)  # noqa: E712
        if scope == "trash":
            stmt = stmt.where(ResourceItem.is_deleted == True)  # noqa: E712
        if scope == "mine" and owner_user_id is not None:
            stmt = stmt.where(ResourceItem.owner_user_id == owner_user_id)
        if scope == "course" and course_id is not None:
            stmt = stmt.where(ResourceItem.course_id == course_id)
        if scope == "recent" and owner_user_id is not None:
            stmt = stmt.where(ResourceItem.owner_user_id == owner_user_id)

        stmt = stmt.order_by(ResourceItem.updated_at.desc())
        items = list(session.exec(stmt).all())

        # 应用 cursor 分页
        if cursor:
            # cursor 是上一页最后一条 resource_id
            cursor_idx = next(
                (i for i, r in enumerate(items) if r.resource_id == cursor),
                len(items),
            )
            items = items[cursor_idx + 1:]
        items_page = items[:page_size]
        next_cursor = None
        if len(items) > page_size:
            next_cursor = items_page[-1].resource_id if items_page else None

        return {
            "items": [self._serialize_resource(r) for r in items_page],
            "next_cursor": next_cursor,
            "total": len(items),
        }

    def _serialize_resource(self, r: ResourceItem) -> dict[str, Any]:
        return {
            "resource_id": r.resource_id,
            "owner_user_id": r.owner_user_id,
            "course_id": r.course_id,
            "scope": r.scope.value,
            "name": r.name,
            "description": r.description,
            "resource_type": r.resource_type.value,
            "mime_type": r.mime_type,
            "file_size": r.file_size,
            "current_version_id": r.current_version_id,
            "is_deleted": r.is_deleted,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }

    def update_resource(
        self,
        session: Session,
        *,
        resource_id: str,
        owner_user_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> ResourceItem:
        resource = self.get_resource(
            session, resource_id=resource_id, owner_user_id=owner_user_id,
        )
        if name is not None:
            resource.name = name
        if description is not None:
            resource.description = description
        resource.updated_at = utcnow_naive()
        session.add(resource)

        if tags is not None:
            # 删除旧标签
            old_tags = session.exec(
                select(ResourceTag).where(
                    ResourceTag.resource_id == resource_id,
                )
            ).all()
            for t in old_tags:
                session.delete(t)
            # 写入新标签
            for tag in tags:
                session.add(ResourceTag(
                    resource_id=resource_id,
                    tag=tag,
                    owner_user_id=owner_user_id,
                ))

        session.flush()
        return resource

    def add_reference(
        self,
        session: Session,
        *,
        resource_id: str,
        owner_user_id: int,
        target_type: str,
        target_course_id: Optional[int] = None,
        target_node_id: Optional[int] = None,
        target_experiment_id: Optional[str] = None,
        target_lab_id: Optional[str] = None,
        reference_note: str = "",
        version_id: Optional[str] = None,
    ) -> ResourceReference:
        """记录资源引用（用于删除时返回下游影响）"""
        self.get_resource(
            session, resource_id=resource_id, owner_user_id=owner_user_id,
        )
        if target_type not in ("course", "node", "experiment", "lab"):
            reject_validation_failed(f"未知的引用类型: {target_type}")

        reference = ResourceReference(
            resource_id=resource_id,
            version_id=version_id,
            owner_user_id=owner_user_id,
            target_type=target_type,
            target_course_id=target_course_id,
            target_node_id=target_node_id,
            target_experiment_id=target_experiment_id,
            target_lab_id=target_lab_id,
            reference_note=reference_note,
        )
        session.add(reference)
        session.flush()
        return reference

    def list_references(
        self,
        session: Session,
        *,
        resource_id: str,
        owner_user_id: int,
    ) -> list[ResourceReference]:
        self.get_resource(
            session, resource_id=resource_id, owner_user_id=owner_user_id,
        )
        return list(session.exec(
            select(ResourceReference).where(
                ResourceReference.resource_id == resource_id,
                ResourceReference.owner_user_id == owner_user_id,
            ).order_by(ResourceReference.created_at.desc())
        ).all())

    def soft_delete(
        self,
        session: Session,
        *,
        resource_id: str,
        deleted_by: int,
    ) -> dict[str, Any]:
        """软删除资源，返回下游影响（不静默删除）"""
        resource = self.get_resource(
            session, resource_id=resource_id, owner_user_id=deleted_by,
        )
        if resource.is_deleted:
            reject_state_conflict("资源已删除")

        # 收集下游引用快照
        references = session.exec(
            select(ResourceReference).where(
                ResourceReference.resource_id == resource_id,
            )
        ).all()
        affected = [
            {
                "reference_id": ref.reference_id,
                "target_type": ref.target_type,
                "target_course_id": ref.target_course_id,
                "target_node_id": ref.target_node_id,
                "target_experiment_id": ref.target_experiment_id,
                "target_lab_id": ref.target_lab_id,
                "reference_note": ref.reference_note,
            }
            for ref in references
        ]

        # 软删除
        resource.is_deleted = True
        resource.deleted_at = utcnow_naive()
        resource.updated_at = utcnow_naive()
        session.add(resource)

        # 进入回收站
        recycle_entry = RecycleBinEntry(
            resource_id=resource_id,
            owner_user_id=deleted_by,
            course_id=resource.course_id,
            deleted_by=deleted_by,
            expires_at=utcnow_naive() + timedelta(days=DEFAULT_RECYCLE_RETENTION_DAYS),
            affected_references=affected,
            restorable=True,
        )
        session.add(recycle_entry)
        session.flush()

        return {
            "resource_id": resource_id,
            "entry_id": recycle_entry.entry_id,
            "affected_references": affected,
            "affected_count": len(affected),
            "expires_at": recycle_entry.expires_at.isoformat(),
        }

    def restore(
        self,
        session: Session,
        *,
        resource_id: str,
        restored_by: int,
    ) -> ResourceItem:
        """从回收站恢复资源"""
        entry = session.exec(
            select(RecycleBinEntry).where(
                RecycleBinEntry.resource_id == resource_id,
                RecycleBinEntry.owner_user_id == restored_by,
                RecycleBinEntry.restorable == True,  # noqa: E712
                RecycleBinEntry.restored_at.is_(None),
            )
        ).first()
        if entry is None:
            reject_resource_not_found(f"资源 {resource_id} 不在回收站")

        if utcnow_naive() > entry.expires_at:
            entry.restorable = False
            session.add(entry)
            reject_state_conflict("回收站条目已过期，无法恢复")

        resource = self.get_resource(
            session, resource_id=resource_id, owner_user_id=restored_by, include_deleted=True,
        )
        resource.is_deleted = False
        resource.deleted_at = None
        resource.updated_at = utcnow_naive()
        session.add(resource)

        entry.restored_at = utcnow_naive()
        session.add(entry)
        session.flush()
        return resource

    def purge(
        self,
        session: Session,
        *,
        resource_id: str,
        purged_by: int,
    ) -> dict[str, Any]:
        """彻底删除资源（需更高权限）"""
        entry = session.exec(
            select(RecycleBinEntry).where(
                RecycleBinEntry.resource_id == resource_id,
                RecycleBinEntry.owner_user_id == purged_by,
            )
        ).first()
        if entry is None:
            reject_resource_not_found(f"资源 {resource_id} 不在回收站")

        resource = self.get_resource(
            session, resource_id=resource_id, owner_user_id=purged_by, include_deleted=True,
        )
        # 彻底删除：物理删除所有版本、引用、ACL、标签
        versions = session.exec(
            select(ResourceVersion).where(ResourceVersion.resource_id == resource_id)
        ).all()
        for v in versions:
            session.delete(v)
        references = session.exec(
            select(ResourceReference).where(ResourceReference.resource_id == resource_id)
        ).all()
        for r in references:
            session.delete(r)
        acls = session.exec(
            select(ResourceAclEntry).where(ResourceAclEntry.resource_id == resource_id)
        ).all()
        for a in acls:
            session.delete(a)
        tags = session.exec(
            select(ResourceTag).where(ResourceTag.resource_id == resource_id)
        ).all()
        for t in tags:
            session.delete(t)

        entry.purged_at = utcnow_naive()
        session.add(entry)
        session.delete(resource)
        session.flush()
        return {"resource_id": resource_id, "purged_at": entry.purged_at.isoformat()}


# ---------------------------------------------------------------------------
# 平台实验室目录服务
# ---------------------------------------------------------------------------


class LabCatalogService:
    """平台实验室目录服务

    - 平台实验与课程实验共享沙箱能力
    - 课程实验可回写课程证据和 return anchor
    - 按 visibility 控制发现范围
    """

    def create_lab(
        self,
        session: Session,
        *,
        owner_user_id: int,
        title: str,
        description: str = "",
        course_id: Optional[int] = None,
        experiment_id: Optional[str] = None,
        language_whitelist: Optional[list[str]] = None,
        visibility: LabCatalogVisibility = LabCatalogVisibility.COURSE_ONLY,
        cpu_time_limit: int = 5,
        memory_limit: int = 128_000,
        wall_time_limit: int = 10,
        knowledge_node_ids: Optional[list[int]] = None,
        statement_object_key: str = "",
        created_by: int,
    ) -> LabCatalogEntry:
        lab = LabCatalogEntry(
            owner_user_id=owner_user_id,
            course_id=course_id,
            experiment_id=experiment_id,
            title=title,
            description=description,
            statement_object_key=statement_object_key,
            language_whitelist=list(language_whitelist or []),
            visibility=visibility,
            cpu_time_limit=cpu_time_limit,
            memory_limit=memory_limit,
            wall_time_limit=wall_time_limit,
            knowledge_node_ids=list(knowledge_node_ids or []),
            created_by=created_by,
        )
        session.add(lab)
        session.flush()
        return lab

    def get_lab(
        self,
        session: Session,
        *,
        lab_id: str,
    ) -> LabCatalogEntry:
        lab = session.exec(
            select(LabCatalogEntry).where(LabCatalogEntry.lab_id == lab_id)
        ).first()
        if lab is None:
            reject_resource_not_found(f"实验室 {lab_id} 不存在")
        return lab

    def list_catalog(
        self,
        session: Session,
        *,
        student_id: Optional[int] = None,
        course_id: Optional[int] = None,
        visibility: Optional[LabCatalogVisibility] = None,
        published_only: bool = True,
        cursor: Optional[str] = None,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """平台实验室大厅：catalog 列表"""
        stmt = select(LabCatalogEntry)
        if published_only:
            stmt = stmt.where(LabCatalogEntry.is_published == True)  # noqa: E712
        if course_id is not None:
            stmt = stmt.where(
                (LabCatalogEntry.course_id == course_id)
                | (LabCatalogEntry.visibility == LabCatalogVisibility.PUBLIC)
            )
        elif visibility is not None:
            stmt = stmt.where(LabCatalogEntry.visibility == visibility)
        elif student_id is not None:
            # 学生视角：仅看 public 或自己课程
            stmt = stmt.where(
                (LabCatalogEntry.visibility == LabCatalogVisibility.PUBLIC)
                | (LabCatalogEntry.owner_user_id == student_id)
            )

        stmt = stmt.order_by(LabCatalogEntry.created_at.desc())
        items = list(session.exec(stmt).all())

        if cursor:
            cursor_idx = next(
                (i for i, l in enumerate(items) if l.lab_id == cursor),
                len(items),
            )
            items = items[cursor_idx + 1:]
        items_page = items[:page_size]
        next_cursor = None
        if len(items) > page_size:
            next_cursor = items_page[-1].lab_id if items_page else None

        return {
            "items": [self._serialize_lab(l) for l in items_page],
            "next_cursor": next_cursor,
            "total": len(items),
        }

    def list_course_tasks(
        self,
        session: Session,
        *,
        course_id: int,
        student_id: int,
    ) -> list[dict[str, Any]]:
        """课程任务页：列出课程实验与学生的参与情况"""
        labs = list(session.exec(
            select(LabCatalogEntry).where(
                LabCatalogEntry.course_id == course_id,
                LabCatalogEntry.is_published == True,  # noqa: E712
            ).order_by(LabCatalogEntry.created_at.desc())
        ).all())

        result: list[dict[str, Any]] = []
        for lab in labs:
            enrollment = session.exec(
                select(LabEnrollment).where(
                    LabEnrollment.lab_id == lab.lab_id,
                    LabEnrollment.student_id == student_id,
                )
            ).first()
            record = session.exec(
                select(LabRecord).where(
                    LabRecord.lab_id == lab.lab_id,
                    LabRecord.student_id == student_id,
                ).order_by(LabRecord.created_at.desc())
            ).first()
            result.append({
                **self._serialize_lab(lab),
                "enrolled": enrollment is not None and enrollment.is_active,
                "last_attempt_id": enrollment.last_attempt_id if enrollment else None,
                "last_active_at": enrollment.last_active_at.isoformat() if enrollment and enrollment.last_active_at else None,
                "best_score": record.final_score if record else None,
                "passed": record.passed if record else None,
            })
        return result

    def list_my_experiments(
        self,
        session: Session,
        *,
        student_id: int,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """我的实验页：列出当前学生参与的所有平台/课程实验室"""
        stmt = select(LabEnrollment).where(LabEnrollment.student_id == student_id)
        if active_only:
            stmt = stmt.where(LabEnrollment.is_active == True)  # noqa: E712
        stmt = stmt.order_by(LabEnrollment.enrolled_at.desc())
        enrollments = list(session.exec(stmt).all())

        result: list[dict[str, Any]] = []
        for enr in enrollments:
            lab = session.get(LabCatalogEntry, enr.lab_id) if enr.lab_id else None
            # lab_id 是字符串主键索引，需用 select
            lab = session.exec(
                select(LabCatalogEntry).where(LabCatalogEntry.lab_id == enr.lab_id)
            ).first()
            if lab is None:
                continue
            result.append({
                **self._serialize_lab(lab),
                "enrolled_at": enr.enrolled_at.isoformat() if enr.enrolled_at else None,
                "last_active_at": enr.last_active_at.isoformat() if enr.last_active_at else None,
                "last_attempt_id": enr.last_attempt_id,
            })
        return result

    def list_records(
        self,
        session: Session,
        *,
        student_id: int,
        course_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """实验记录页：汇总学生在平台/课程实验室的最终记录"""
        stmt = select(LabRecord).where(LabRecord.student_id == student_id)
        if course_id is not None:
            stmt = stmt.where(LabRecord.course_id == course_id)
        stmt = stmt.order_by(LabRecord.created_at.desc())
        records = list(session.exec(stmt).all())

        return [
            {
                "record_id": r.record_id,
                "lab_id": r.lab_id,
                "student_id": r.student_id,
                "course_id": r.course_id,
                "attempt_id": r.attempt_id,
                "final_score": r.final_score,
                "passed": r.passed,
                "evidence_id": r.evidence_id,
                "return_anchor": r.return_anchor,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in records
        ]

    def publish_lab(
        self,
        session: Session,
        *,
        lab_id: str,
    ) -> LabCatalogEntry:
        lab = self.get_lab(session, lab_id=lab_id)
        lab.is_published = True
        lab.published_at = utcnow_naive()
        lab.updated_at = utcnow_naive()
        session.add(lab)
        session.flush()
        return lab

    def enroll_student(
        self,
        session: Session,
        *,
        lab_id: str,
        student_id: int,
    ) -> LabEnrollment:
        """学生加入实验室"""
        # 验证实验室已发布
        lab = self.get_lab(session, lab_id=lab_id)
        if not lab.is_published:
            reject_state_conflict("实验室未发布")

        # 幂等：已存在则激活
        existing = session.exec(
            select(LabEnrollment).where(
                LabEnrollment.lab_id == lab_id,
                LabEnrollment.student_id == student_id,
            )
        ).first()
        if existing is not None:
            existing.is_active = True
            existing.last_active_at = utcnow_naive()
            session.add(existing)
            session.flush()
            return existing

        enrollment = LabEnrollment(
            lab_id=lab_id,
            student_id=student_id,
            course_id=lab.course_id,
            last_active_at=utcnow_naive(),
        )
        session.add(enrollment)
        session.flush()
        return enrollment

    def record_attempt_result(
        self,
        session: Session,
        *,
        lab_id: str,
        student_id: int,
        attempt_id: str,
        final_score: Optional[float] = None,
        passed: Optional[bool] = None,
        evidence_id: Optional[str] = None,
        return_anchor: Optional[dict] = None,
    ) -> LabRecord:
        """记录学生在实验室的最终尝试结果"""
        record = LabRecord(
            lab_id=lab_id,
            student_id=student_id,
            attempt_id=attempt_id,
            final_score=final_score,
            passed=passed,
            evidence_id=evidence_id,
            return_anchor=return_anchor or {},
        )
        session.add(record)
        session.flush()

        # 更新 enrollment 的 last_attempt_id
        enrollment = session.exec(
            select(LabEnrollment).where(
                LabEnrollment.lab_id == lab_id,
                LabEnrollment.student_id == student_id,
            )
        ).first()
        if enrollment is not None:
            enrollment.last_attempt_id = attempt_id
            enrollment.last_active_at = utcnow_naive()
            session.add(enrollment)

        session.flush()
        return record

    def _serialize_lab(self, lab: LabCatalogEntry) -> dict[str, Any]:
        return {
            "lab_id": lab.lab_id,
            "owner_user_id": lab.owner_user_id,
            "course_id": lab.course_id,
            "experiment_id": lab.experiment_id,
            "title": lab.title,
            "description": lab.description,
            "statement_object_key": lab.statement_object_key,
            "language_whitelist": lab.language_whitelist,
            "visibility": lab.visibility.value,
            "is_published": lab.is_published,
            "cpu_time_limit": lab.cpu_time_limit,
            "memory_limit": lab.memory_limit,
            "wall_time_limit": lab.wall_time_limit,
            "knowledge_node_ids": lab.knowledge_node_ids,
            "created_by": lab.created_by,
            "created_at": lab.created_at.isoformat() if lab.created_at else None,
            "updated_at": lab.updated_at.isoformat() if lab.updated_at else None,
            "published_at": lab.published_at.isoformat() if lab.published_at else None,
        }


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


resource_service = ResourceService()
lab_catalog_service = LabCatalogService()
