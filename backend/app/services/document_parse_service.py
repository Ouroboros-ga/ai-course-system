"""阶段4 服务层：课程材料解析、Evidence、Citation 与图谱候选

不重复实现已有 graph_production_service 的能力（CourseEvidenceRecord/GraphSnapshotRecord/GraphNodeReview），
而是补全解析流水线、候选证据、学生可读 Citation、图谱候选批次、release 关联。

关键约束：
- 跨课程严格隔离：所有查询都按 course_id 过滤
- 教师确认才升级为正式证据：EvidenceSpan.confirm → 生成 CourseEvidenceRecord + EvidenceCitation
- 重解析不静默失效：旧 EvidenceSpan/EvidenceCitation 按 stale_strategy 标记
- 图谱不可用时降级：parse_run 失败不影响已有 Citation 查询
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.exceptions import (
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_naive
from app.models.document_parse_model import (
    CandidateBatchStatus,
    CitationStatus,
    DocumentBlock,
    DocumentParseRun,
    EvidenceCitation,
    EvidenceRenderAsset,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    GraphReleaseLink,
    ParsePipeline,
    ParseRunStatus,
    StaleStrategy,
)
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    EvidenceStatus,
    GraphSnapshotRecord,
    SnapshotStatus,
)


# ---------------------------------------------------------------------------
# 解析流水线服务
# ---------------------------------------------------------------------------


class DocumentParseService:
    """课程材料解析流水线服务

    负责创建解析任务、记录运行、写入文档块、抽取候选证据、生成学生可读 Citation。
    解析本身通过统一任务中心异步执行；本服务负责持久化运行元数据与产物。
    """

    def create_run(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: str,
        material_version_id: Optional[str] = None,
        document_id: Optional[str] = None,
        task_id: Optional[str] = None,
        pipeline: ParsePipeline = ParsePipeline.FULL,
        stale_strategy: StaleStrategy = StaleStrategy.MARK_STALE,
        initiated_by: int,
    ) -> DocumentParseRun:
        """创建解析运行。

        - 同一 material_version 不允许并发 pending/running 运行（避免重复解析）
        - 若存在历史 succeeded 运行，记录 prev_run_id 形成链
        """
        # 并发保护
        existing_active = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_id == material_id,
                DocumentParseRun.status.in_([
                    ParseRunStatus.PENDING, ParseRunStatus.RUNNING,
                ]),
            )
        ).first()
        if existing_active is not None:
            reject_state_conflict(
                "该材料已有正在进行的解析任务",
                details={"existing_run_id": existing_active.run_id},
            )

        # 链接上一运行（用于重解析追溯）
        prev_run = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_id == material_id,
                DocumentParseRun.status == ParseRunStatus.SUCCEEDED,
            ).order_by(DocumentParseRun.finished_at.desc())
        ).first()

        run = DocumentParseRun(
            course_id=course_id,
            material_id=material_id,
            material_version_id=material_version_id,
            document_id=document_id,
            task_id=task_id,
            prev_run_id=prev_run.run_id if prev_run else None,
            pipeline=pipeline,
            status=ParseRunStatus.PENDING,
            stale_strategy=stale_strategy,
            initiated_by=initiated_by,
        )
        session.add(run)
        session.flush()

        # 预处理旧证据：根据 stale_strategy 标记
        if prev_run is not None:
            affected = self._mark_old_evidence_stale(
                session,
                course_id=course_id,
                run_id=prev_run.run_id,
                stale_strategy=stale_strategy,
            )
            run.affected_evidence_count = affected
            session.add(run)
            session.flush()
        return run

    def _mark_old_evidence_stale(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        stale_strategy: StaleStrategy,
    ) -> int:
        """根据 stale_strategy 处理旧证据。

        - mark_stale: EvidenceSpan.status=stale, EvidenceCitation.status=source_updated
        - orphan: EvidenceSpan.status=orphaned, EvidenceCitation.status=source_invalid
        - delete: 物理删除（默认不使用）
        """
        now = utcnow_naive()
        affected = 0
        if stale_strategy == StaleStrategy.DELETE:
            # 仅在明确授权时使用，默认不删除
            spans = session.exec(
                select(EvidenceSpan).where(
                    EvidenceSpan.course_id == course_id,
                    EvidenceSpan.run_id == run_id,
                    EvidenceSpan.status.in_([
                        EvidenceSpanStatus.CANDIDATE, EvidenceSpanStatus.CONFIRMED,
                    ]),
                )
            ).all()
            for span in spans:
                session.delete(span)
                affected += 1
            citations = session.exec(
                select(EvidenceCitation).where(
                    EvidenceCitation.course_id == course_id,
                    EvidenceCitation.status.in_([
                        CitationStatus.EXACT, CitationStatus.APPROXIMATE,
                    ]),
                )
            ).all()
            for cit in citations:
                session.delete(cit)
                affected += 1
            return affected

        new_span_status = (
            EvidenceSpanStatus.STALE if stale_strategy == StaleStrategy.MARK_STALE
            else EvidenceSpanStatus.ORPHANED
        )
        new_citation_status = (
            CitationStatus.SOURCE_UPDATED if stale_strategy == StaleStrategy.MARK_STALE
            else CitationStatus.SOURCE_INVALID
        )
        reason = "courseware_reparse" if stale_strategy == StaleStrategy.MARK_STALE else "courseware_orphaned"

        spans = session.exec(
            select(EvidenceSpan).where(
                EvidenceSpan.course_id == course_id,
                EvidenceSpan.run_id == run_id,
                EvidenceSpan.status.in_([
                    EvidenceSpanStatus.CANDIDATE, EvidenceSpanStatus.CONFIRMED,
                ]),
            )
        ).all()
        for span in spans:
            span.status = new_span_status
            span.stale_reason = reason
            span.stale_at = now
            span.updated_at = now
            session.add(span)
            affected += 1

        citations = session.exec(
            select(EvidenceCitation).where(
                EvidenceCitation.course_id == course_id,
                EvidenceCitation.status.in_([
                    CitationStatus.EXACT, CitationStatus.APPROXIMATE,
                ]),
            )
        ).all()
        for cit in citations:
            cit.status = new_citation_status
            cit.stale_reason = reason
            cit.stale_at = now
            cit.updated_at = now
            session.add(cit)
            affected += 1
        return affected

    def mark_running(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
    ) -> DocumentParseRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status != ParseRunStatus.PENDING:
            reject_state_conflict(
                f"解析运行状态 {run.status.value} 不能转移到 running",
                details={"current_status": run.status.value},
            )
        run.status = ParseRunStatus.RUNNING
        run.started_at = utcnow_naive()
        run.updated_at = utcnow_naive()
        session.add(run)
        session.flush()
        return run

    def mark_succeeded(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
        block_count: int = 0,
        evidence_span_count: int = 0,
        graph_candidate_count: int = 0,
    ) -> DocumentParseRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        if run.status not in (ParseRunStatus.PENDING, ParseRunStatus.RUNNING):
            reject_state_conflict(
                f"解析运行状态 {run.status.value} 不能转移到 succeeded",
                details={"current_status": run.status.value},
            )
        run.status = ParseRunStatus.SUCCEEDED
        run.block_count = block_count
        run.evidence_span_count = evidence_span_count
        run.graph_candidate_count = graph_candidate_count
        run.finished_at = utcnow_naive()
        run.updated_at = utcnow_naive()
        session.add(run)
        session.flush()
        return run

    def mark_failed(
        self,
        session: Session,
        *,
        run_id: str,
        course_id: int,
        error_code: str,
        error_message: str,
    ) -> DocumentParseRun:
        run = self._require_run(session, run_id=run_id, course_id=course_id)
        run.status = ParseRunStatus.FAILED
        run.error_code = error_code
        run.error_message = error_message[:500]
        run.finished_at = utcnow_naive()
        run.updated_at = utcnow_naive()
        session.add(run)
        session.flush()
        return run

    def _require_run(self, session: Session, *, run_id: str, course_id: int) -> DocumentParseRun:
        run = session.exec(
            select(DocumentParseRun).where(
                DocumentParseRun.run_id == run_id,
                DocumentParseRun.course_id == course_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found("解析运行不存在")
        return run

    def list_runs(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: Optional[str] = None,
        status: Optional[ParseRunStatus] = None,
    ) -> list[DocumentParseRun]:
        stmt = select(DocumentParseRun).where(
            DocumentParseRun.course_id == course_id
        ).order_by(DocumentParseRun.created_at.desc())
        if material_id is not None:
            stmt = stmt.where(DocumentParseRun.material_id == material_id)
        if status is not None:
            stmt = stmt.where(DocumentParseRun.status == status)
        return list(session.exec(stmt).all())

    # --- 文档块与证据片段 ---------------------------------------------

    def add_block(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        document_id: Optional[str],
        page_number: int,
        block_type: str,
        text: str,
        bbox: Optional[dict] = None,
        char_start: int = 0,
        char_end: int = 0,
        order_index: int = 0,
    ) -> DocumentBlock:
        """写入文档块，并计算内容哈希。"""
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
        block = DocumentBlock(
            course_id=course_id,
            run_id=run_id,
            document_id=document_id,
            page_number=page_number,
            block_type=block_type,
            text=text,
            bbox=bbox,
            char_start=char_start,
            char_end=char_end,
            content_hash=content_hash,
            order_index=order_index,
        )
        session.add(block)
        session.flush()
        return block

    def add_evidence_span(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        block_id: str,
        document_id: Optional[str],
        page_number: int,
        text_snippet: str,
        bbox: Optional[dict] = None,
        char_start: int = 0,
        char_end: int = 0,
        linked_node_ids: Optional[list] = None,
    ) -> EvidenceSpan:
        """写入候选证据片段（status=candidate）。"""
        content_hash = hashlib.sha256(text_snippet.encode("utf-8")).hexdigest() if text_snippet else ""
        span = EvidenceSpan(
            course_id=course_id,
            run_id=run_id,
            block_id=block_id,
            document_id=document_id,
            page_number=page_number,
            text_snippet=text_snippet,
            bbox=bbox,
            char_start=char_start,
            char_end=char_end,
            content_hash=content_hash,
            status=EvidenceSpanStatus.CANDIDATE,
            linked_node_ids=linked_node_ids or [],
        )
        session.add(span)
        session.flush()
        return span

    def confirm_evidence_span(
        self,
        session: Session,
        *,
        course_id: int,
        span_id: str,
        confirmed_by: int,
        source_file: str = "",
        source_type: str = "document",
        node_id: Optional[int] = None,
    ) -> tuple[EvidenceSpan, CourseEvidenceRecord, EvidenceCitation]:
        """教师确认候选证据：升级为正式 CourseEvidenceRecord + 学生可读 EvidenceCitation。

        - 已 confirmed 的不可重复确认
        - rejected 的不可再确认（需重新生成）
        """
        span = self._require_span(session, span_id=span_id, course_id=course_id)
        if span.status == EvidenceSpanStatus.CONFIRMED:
            reject_state_conflict("证据片段已确认，无需重复确认")
        if span.status in (EvidenceSpanStatus.REJECTED, EvidenceSpanStatus.ORPHANED):
            reject_state_conflict(
                f"证据片段状态 {span.status.value} 不可确认",
                details={"current_status": span.status.value},
            )

        now = utcnow_naive()
        span.status = EvidenceSpanStatus.CONFIRMED
        span.confirmed_by = confirmed_by
        span.confirmed_at = now
        span.updated_at = now
        if node_id is not None and node_id not in span.linked_node_ids:
            span.linked_node_ids = [*span.linked_node_ids, node_id]
        session.add(span)

        # 生成正式 CourseEvidenceRecord
        evidence_id = "ev_" + __import__("uuid").uuid4().hex
        formal = CourseEvidenceRecord(
            evidence_id=evidence_id,
            course_id=course_id,
            document_id=span.document_id,
            source_file=source_file,
            page_number=span.page_number,
            char_start=span.char_start,
            char_end=span.char_end,
            text_snippet=span.text_snippet,
            evidence_type="document_extract",
            content_hash=span.content_hash,
            status=EvidenceStatus.ACTIVE,
            reviewed_by=confirmed_by,
            reviewed_at=now,
            created_at=now,
        )
        session.add(formal)

        # 生成学生可读 Citation
        citation = EvidenceCitation(
            course_id=course_id,
            evidence_id=evidence_id,
            span_id=span.span_id,
            document_id=span.document_id,
            node_id=node_id,
            source_file=source_file,
            source_type=source_type,
            page_number=span.page_number,
            bbox=span.bbox,
            text_snippet=span.text_snippet,
            char_start=span.char_start,
            char_end=span.char_end,
            version=1,
            status=CitationStatus.EXACT,
            student_visible=True,
        )
        session.add(citation)

        span.linked_evidence_id = evidence_id
        session.add(span)
        session.flush()
        return span, formal, citation

    def reject_evidence_span(
        self,
        session: Session,
        *,
        course_id: int,
        span_id: str,
        rejected_by: int,
        reject_reason: str = "",
    ) -> EvidenceSpan:
        span = self._require_span(session, span_id=span_id, course_id=course_id)
        if span.status in (EvidenceSpanStatus.CONFIRMED, EvidenceSpanStatus.REJECTED,
                            EvidenceSpanStatus.ORPHANED):
            reject_state_conflict(
                f"证据片段状态 {span.status.value} 不可拒绝",
                details={"current_status": span.status.value},
            )
        span.status = EvidenceSpanStatus.REJECTED
        span.rejected_by = rejected_by
        span.rejected_at = utcnow_naive()
        span.reject_reason = reject_reason
        span.updated_at = utcnow_naive()
        session.add(span)
        session.flush()
        return span

    def _require_span(self, session: Session, *, span_id: str, course_id: int) -> EvidenceSpan:
        span = session.exec(
            select(EvidenceSpan).where(
                EvidenceSpan.span_id == span_id,
                EvidenceSpan.course_id == course_id,
            )
        ).first()
        if span is None:
            reject_resource_not_found("证据片段不存在")
        return span

    def list_evidence_spans(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: Optional[str] = None,
        status: Optional[EvidenceSpanStatus] = None,
        node_id: Optional[int] = None,
    ) -> list[EvidenceSpan]:
        stmt = select(EvidenceSpan).where(EvidenceSpan.course_id == course_id)
        if run_id is not None:
            stmt = stmt.where(EvidenceSpan.run_id == run_id)
        if status is not None:
            stmt = stmt.where(EvidenceSpan.status == status)
        if node_id is not None:
            stmt = stmt.where(EvidenceSpan.linked_node_ids.contains([node_id]))
        stmt = stmt.order_by(EvidenceSpan.created_at.desc())
        return list(session.exec(stmt).all())

    # --- 学生可读 Citation --------------------------------------------

    def list_citations(
        self,
        session: Session,
        *,
        course_id: int,
        node_id: Optional[int] = None,
        student_visible: Optional[bool] = None,
        include_stale: bool = False,
    ) -> list[EvidenceCitation]:
        """学生端查询原文引用。

        - 学生默认仅看 student_visible=True 且 status in (exact, approximate)
        - 教师可看全部（include_stale=True 包含 source_updated/source_invalid）
        """
        stmt = select(EvidenceCitation).where(EvidenceCitation.course_id == course_id)
        if node_id is not None:
            stmt = stmt.where(EvidenceCitation.node_id == node_id)
        if student_visible is not None:
            stmt = stmt.where(EvidenceCitation.student_visible == student_visible)
        if not include_stale:
            stmt = stmt.where(
                EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE])
            )
        stmt = stmt.order_by(EvidenceCitation.created_at.desc())
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 图谱候选批次服务
# ---------------------------------------------------------------------------


class GraphCandidateService:
    """图谱候选批次服务

    - 创建候选批次，记录节点/关系候选数
    - 教师审核通过后，绑定已发布 GraphSnapshot
    - 与课程 release 关联（GraphReleaseLink）
    """

    def create_batch(
        self,
        session: Session,
        *,
        course_id: int,
        parse_run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        initiated_by: int,
        model_version: str = "graph-candidate-v1.0",
    ) -> GraphCandidateBatch:
        # 旧活跃批次标记为 superseded
        old_batches = session.exec(
            select(GraphCandidateBatch).where(
                GraphCandidateBatch.course_id == course_id,
                GraphCandidateBatch.status.in_([
                    CandidateBatchStatus.PENDING, CandidateBatchStatus.RUNNING,
                    CandidateBatchStatus.SUCCEEDED, CandidateBatchStatus.PARTIAL_SUCCESS,
                ]),
            )
        ).all()
        prev_batch_id = None
        for old in old_batches:
            if old.status in (CandidateBatchStatus.PENDING, CandidateBatchStatus.RUNNING,
                              CandidateBatchStatus.SUCCEEDED, CandidateBatchStatus.PARTIAL_SUCCESS):
                prev_batch_id = old.batch_id
                old.status = CandidateBatchStatus.SUPERSEDED
                old.updated_at = utcnow_naive()
                session.add(old)

        batch = GraphCandidateBatch(
            course_id=course_id,
            parse_run_id=parse_run_id,
            task_id=task_id,
            prev_batch_id=prev_batch_id,
            status=CandidateBatchStatus.PENDING,
            initiated_by=initiated_by,
            model_version=model_version,
        )
        session.add(batch)
        session.flush()
        return batch

    def mark_succeeded(
        self,
        session: Session,
        *,
        course_id: int,
        batch_id: str,
        node_candidate_count: int = 0,
        relation_candidate_count: int = 0,
    ) -> GraphCandidateBatch:
        batch = self._require_batch(session, batch_id=batch_id, course_id=course_id)
        batch.status = CandidateBatchStatus.SUCCEEDED
        batch.node_candidate_count = node_candidate_count
        batch.relation_candidate_count = relation_candidate_count
        batch.finished_at = utcnow_naive()
        batch.updated_at = utcnow_naive()
        session.add(batch)
        session.flush()
        return batch

    def link_snapshot(
        self,
        session: Session,
        *,
        course_id: int,
        batch_id: str,
        snapshot_id: str,
    ) -> GraphCandidateBatch:
        """教师审核通过后，将候选批次绑定到已发布 GraphSnapshot。"""
        batch = self._require_batch(session, batch_id=batch_id, course_id=course_id)
        # 校验快照归属同课程
        snapshot = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.snapshot_id == snapshot_id,
                GraphSnapshotRecord.course_id == course_id,
            )
        ).first()
        if snapshot is None:
            reject_resource_not_found("图谱快照不存在或不属于该课程")
        batch.snapshot_id = snapshot_id
        batch.updated_at = utcnow_naive()
        session.add(batch)
        session.flush()
        return batch

    def _require_batch(
        self, session: Session, *, batch_id: str, course_id: int,
    ) -> GraphCandidateBatch:
        batch = session.exec(
            select(GraphCandidateBatch).where(
                GraphCandidateBatch.batch_id == batch_id,
                GraphCandidateBatch.course_id == course_id,
            )
        ).first()
        if batch is None:
            reject_resource_not_found("图谱候选批次不存在")
        return batch

    def list_batches(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[CandidateBatchStatus] = None,
    ) -> list[GraphCandidateBatch]:
        stmt = select(GraphCandidateBatch).where(
            GraphCandidateBatch.course_id == course_id
        ).order_by(GraphCandidateBatch.created_at.desc())
        if status is not None:
            stmt = stmt.where(GraphCandidateBatch.status == status)
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 图谱快照 ↔ 课程 release 关联服务
# ---------------------------------------------------------------------------


class GraphReleaseLinkService:
    """图谱快照与课程 release 关联服务

    保证图谱与课程内容版本一致；release 回滚时图谱同步回滚。
    """

    def link(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        snapshot_id: str,
        linked_by: int,
    ) -> GraphReleaseLink:
        # 校验快照归属同课程
        snapshot = session.exec(
            select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.snapshot_id == snapshot_id,
                GraphSnapshotRecord.course_id == course_id,
            )
        ).first()
        if snapshot is None:
            reject_resource_not_found("图谱快照不存在或不属于该课程")
        existing = session.exec(
            select(GraphReleaseLink).where(
                GraphReleaseLink.course_id == course_id,
                GraphReleaseLink.release_id == release_id,
            )
        ).first()
        if existing is not None:
            # 幂等更新 snapshot
            existing.snapshot_id = snapshot_id
            existing.linked_by = linked_by
            existing.linked_at = utcnow_naive()
            session.add(existing)
            session.flush()
            return existing
        link = GraphReleaseLink(
            course_id=course_id,
            release_id=release_id,
            snapshot_id=snapshot_id,
            linked_by=linked_by,
        )
        session.add(link)
        session.flush()
        return link

    def get_link(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
    ) -> Optional[GraphReleaseLink]:
        return session.exec(
            select(GraphReleaseLink).where(
                GraphReleaseLink.course_id == course_id,
                GraphReleaseLink.release_id == release_id,
            )
        ).first()

    def list_links(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> list[GraphReleaseLink]:
        return list(session.exec(
            select(GraphReleaseLink).where(
                GraphReleaseLink.course_id == course_id,
            ).order_by(GraphReleaseLink.linked_at.desc())
        ).all())


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

document_parse_service = DocumentParseService()
graph_candidate_service = GraphCandidateService()
graph_release_link_service = GraphReleaseLinkService()
