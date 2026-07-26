"""阶段10 历史课程补建清单编排服务。

按 6 阶段流水线列出待补建课程，并支持触发后续阶段：
1. material_pending_version  - 课程有 SourceMaterial 但无 SourceMaterialVersion
2. version_pending_parse     - 课程有 SourceMaterialVersion 但无 succeeded DocumentParseRun
3. parse_pending_evidence    - 课程有 succeeded DocumentParseRun 但无 confirmed EvidenceSpan
4. evidence_pending_candidate- 课程有 confirmed EvidenceSpan 但无 GraphCandidateBatch
5. candidate_pending_review  - 课程有 GraphCandidateBatch(pending) 但无 approved 批次
6. review_pending_release    - 课程有 approved 候选但无 active CourseRelease

设计要点：
- 平台级 COURSE_AUDIT 权限可查看全部课程；课程教师可查看本课程
- 跨课程严格隔离：列表过滤按 course_id 校验
- 仅返回结构化摘要：course_id、阶段、待办数、最近活动时间
- 不直接修改业务数据：触发动作调用对应服务的现有 API
- 失败保留原始 error_code，禁止伪装成功
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_resource_not_found,
    reject_validation_failed,
    unified_response,
)
from app.models.course_build_model import (
    CourseRelease,
    ReleaseStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_model import Course, CourseStatus
from app.models.document_parse_model import (
    CandidateBatchStatus,
    DocumentParseRun,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    ParseRunStatus,
)
from app.models.graph_production_model import GraphSnapshotRecord, SnapshotStatus

logger = logging.getLogger(__name__)


# 6 个流水线阶段标识
REBUILD_STAGES: tuple[str, ...] = (
    "material_pending_version",
    "version_pending_parse",
    "parse_pending_evidence",
    "evidence_pending_candidate",
    "candidate_pending_review",
    "review_pending_release",
)

STAGE_DISPLAY_NAMES: dict[str, str] = {
    "material_pending_version": "材料待上传版本",
    "version_pending_parse": "版本待解析",
    "parse_pending_evidence": "解析待产出证据",
    "evidence_pending_candidate": "证据待图谱候选",
    "candidate_pending_review": "候选待教师审核",
    "review_pending_release": "审核待发布",
}


class HistoricalRebuildService:
    """历史课程补建清单编排服务。"""

    # -----------------------------------------------------------------
    # 全局清单（按阶段聚合）
    # -----------------------------------------------------------------

    def list_global_checklist(
        self,
        session: Session,
        *,
        status_filter: Optional[CourseStatus] = None,
    ) -> list[dict[str, Any]]:
        """列出全部课程的补建状态；按阶段聚合。

        返回 [{course_id, course_title, stage, pending_count, last_activity_at, ...}]。
        每个课程只出现在最前的待办阶段（pipeline 推进式）。
        """
        # 取所有课程基础信息
        stmt = select(Course).order_by(Course.id.asc())
        if status_filter is not None:
            stmt = stmt.where(Course.status == status_filter)
        courses = list(session.exec(stmt).all())

        result: list[dict[str, Any]] = []
        for course in courses:
            entry = self._compute_course_stage(session, course=course)
            if entry is not None:
                result.append(entry)
        return result

    def list_course_detail(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> dict[str, Any]:
        """课程级补建状态详情：列出全部 6 阶段计数。"""
        course = session.get(Course, course_id)
        if course is None:
            reject_resource_not_found("课程不存在")
        return self._compute_full_course_status(session, course=course)

    # -----------------------------------------------------------------
    # 单课程阶段计算
    # -----------------------------------------------------------------

    def _compute_course_stage(
        self, session: Session, *, course: Course,
    ) -> Optional[dict[str, Any]]:
        """计算课程当前最前的待办阶段；全部完成返回 None。"""
        full = self._compute_full_course_status(session, course=course)
        for stage in REBUILD_STAGES:
            if full[f"{stage}_count"] > 0:
                return {
                    "course_id": course.id,
                    "course_title": course.title,
                    "course_status": course.status.value if hasattr(course.status, "value") else str(course.status),
                    "teacher_id": course.teacher_id,
                    "stage": stage,
                    "stage_display": STAGE_DISPLAY_NAMES[stage],
                    "pending_count": full[f"{stage}_count"],
                    "last_activity_at": full["last_activity_at"],
                }
        # 全部完成 → 不进入待办清单
        return None

    def _compute_full_course_status(
        self, session: Session, *, course: Course,
    ) -> dict[str, Any]:
        """计算课程全部 6 阶段的待办数；用于详情视图。"""
        course_id = course.id

        # 1. material_pending_version: 课程有 SourceMaterial 但无 SourceMaterialVersion
        materials_count = session.exec(
            select(func.count(SourceMaterial.id)).where(
                SourceMaterial.course_id == course_id,
            )
        ).one()
        versions_count = session.exec(
            select(func.count(SourceMaterialVersion.id)).where(
                SourceMaterialVersion.course_id == course_id,
            )
        ).one()
        material_pending_version_count = max(0, materials_count - versions_count) if materials_count > 0 else 0

        # 2. version_pending_parse: 课程有 SourceMaterialVersion 但无 succeeded DocumentParseRun
        succeeded_runs = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.status == ParseRunStatus.SUCCEEDED,
            )
        ).all()
        succeeded_run_version_ids = {run.material_version_id for run in succeeded_runs}
        pending_parse_versions = session.exec(
            select(SourceMaterialVersion).where(
                SourceMaterialVersion.course_id == course_id,
            )
        ).all()
        version_pending_parse_count = sum(
            1 for v in pending_parse_versions
            if v.version_id not in succeeded_run_version_ids
        )

        # 3. parse_pending_evidence: 课程有 succeeded DocumentParseRun 但无 confirmed EvidenceSpan
        confirmed_evidence_count = session.exec(
            select(func.count(EvidenceSpan.id)).where(
                EvidenceSpan.course_id == course_id,
                EvidenceSpan.status == EvidenceSpanStatus.CONFIRMED,
            )
        ).one()
        parse_pending_evidence_count = len(succeeded_runs) if confirmed_evidence_count == 0 else 0

        # 4. evidence_pending_candidate: 课程有 confirmed EvidenceSpan 但无 GraphCandidateBatch
        candidate_batches = session.exec(
            select(GraphCandidateBatch).where(
                GraphCandidateBatch.course_id == course_id,
            )
        ).all()
        evidence_pending_candidate_count = 0
        if confirmed_evidence_count > 0 and not candidate_batches:
            evidence_pending_candidate_count = confirmed_evidence_count

        # 5. candidate_pending_review: 课程有 GraphCandidateBatch 但无已审核通过批次
        # 教师审核通过后，批次 snapshot_id 非空（升级为正式 GraphSnapshot）；
        # CandidateBatchStatus 无 APPROVED，使用 snapshot_id 是否非空作为审核通过标志。
        approved_batches = [b for b in candidate_batches if b.snapshot_id]
        pending_review_batches = [b for b in candidate_batches if not b.snapshot_id]
        candidate_pending_review_count = 0
        if candidate_batches and not approved_batches:
            candidate_pending_review_count = len(pending_review_batches) if pending_review_batches else len(candidate_batches)

        # 6. review_pending_release: 课程有 approved 候选但无 active CourseRelease
        active_release = session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
                CourseRelease.is_active == True,  # noqa: E712
                CourseRelease.status == ReleaseStatus.PUBLISHED,
            )
        ).first()
        review_pending_release_count = 0
        if approved_batches and active_release is None:
            review_pending_release_count = len(approved_batches)

        # 最近活动时间：取最新 parse_run.created_at
        last_run = session.exec(
            select(DocumentParseRun)
            .where(DocumentParseRun.course_id == course_id)
            .order_by(DocumentParseRun.created_at.desc())
            .limit(1)
        ).first()
        last_activity_at = last_run.created_at.isoformat() if last_run and last_run.created_at else None

        return {
            "course_id": course_id,
            "course_title": course.title,
            "course_status": course.status.value if hasattr(course.status, "value") else str(course.status),
            "teacher_id": course.teacher_id,
            "material_pending_version_count": material_pending_version_count,
            "version_pending_parse_count": version_pending_parse_count,
            "parse_pending_evidence_count": parse_pending_evidence_count,
            "evidence_pending_candidate_count": evidence_pending_candidate_count,
            "candidate_pending_review_count": candidate_pending_review_count,
            "review_pending_release_count": review_pending_release_count,
            "materials_total": materials_count,
            "versions_total": versions_count,
            "succeeded_runs_total": len(succeeded_runs),
            "confirmed_evidence_total": confirmed_evidence_count,
            "candidate_batches_total": len(candidate_batches),
            "approved_batches_total": len(approved_batches),
            "has_active_release": active_release is not None,
            "last_activity_at": last_activity_at,
        }

    # -----------------------------------------------------------------
    # 全局聚合统计
    # -----------------------------------------------------------------

    def get_global_summary(self, session: Session) -> dict[str, Any]:
        """全局补建进度汇总：每个阶段的课程数。"""
        all_courses = list(session.exec(select(Course)).all())
        stage_counts = {stage: 0 for stage in REBUILD_STAGES}
        completed_count = 0
        for course in all_courses:
            entry = self._compute_course_stage(session, course=course)
            if entry is None:
                completed_count += 1
            else:
                stage_counts[entry["stage"]] += 1
        return {
            "total_courses": len(all_courses),
            "completed_courses": completed_count,
            "pending_courses": len(all_courses) - completed_count,
            "stage_counts": stage_counts,
            "completion_rate": (completed_count / len(all_courses)) if all_courses else 0.0,
        }


historical_rebuild_service = HistoricalRebuildService()
