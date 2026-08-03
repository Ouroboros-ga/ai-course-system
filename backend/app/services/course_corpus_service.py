"""Course-level orchestration for parsed materials.

Material parsing produces immutable document facts.  This service is the
boundary that turns the current *set* of successfully parsed material versions
into a course corpus and a separately traceable course-draft build task.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.course_build_model import (
    CorpusSnapshotStatus,
    CourseCorpusItem,
    CourseCorpusSnapshot,
    CourseDraftBuildStatus,
    CourseDraftBuildTask,
    CourseRetrievalSnapshot,
    MaterialStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_outline_model import CourseOutlineVersion, TeachingScriptVersion
from app.models.course_outline_model import (
    CourseOutlineNode,
    OutlineNodeType,
    PatchOperation,
    PatchProposal,
    PatchProposalOperation,
    TeachingScriptNode,
)
from app.models.document_parse_model import (
    DocumentIRVersion,
    DocumentParseRun,
    DocumentBlock,
    EvidenceSpan,
    EvidenceSpanStatus,
    ParseRunStatus,
    RetrievalChunk,
)
from app.services.task_service import TaskCreateRequest, task_service


logger = logging.getLogger(__name__)

DEFAULT_CORPUS_QUIET_WINDOW_SECONDS = 8

ROLE_PRIORITY = {
    "primary_courseware": 10,
    "syllabus": 20,
    "textbook": 30,
    "experiment_guide": 40,
    "exercise_bank": 50,
    "reference": 60,
}


class CourseCorpusService:
    def snapshots_have_same_material_set(
        self,
        session: Session,
        *,
        left_snapshot_id: str | None,
        right_snapshot: CourseCorpusSnapshot | None,
    ) -> bool:
        """Return whether two corpus snapshots contain the same source bytes.

        Snapshot IDs are intentionally immutable and normally form a strict
        lineage.  Older local-demo data can, however, contain duplicate
        material rows for the same uploaded bytes.  The deduplicated corpus
        then receives a new snapshot ID even though an existing outline/script
        was built from the exact same source documents.  Comparing immutable
        file hashes gives that migration case a narrow, auditable compatibility
        path without allowing a genuinely different material set through.
        """
        if not left_snapshot_id or right_snapshot is None:
            return False
        if left_snapshot_id == right_snapshot.corpus_snapshot_id:
            return True
        left = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.corpus_snapshot_id == left_snapshot_id,
            CourseCorpusSnapshot.course_id == right_snapshot.course_id,
        )).first()
        if left is None:
            return False

        def material_keys(snapshot: CourseCorpusSnapshot) -> set[str]:
            version_ids = list(snapshot.material_version_ids or [])
            if not version_ids:
                return set()
            versions = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.course_id == snapshot.course_id,
                SourceMaterialVersion.version_id.in_(version_ids),
            )).all()
            return {
                (version.file_hash or version.version_id).strip()
                for version in versions
                if (version.file_hash or version.version_id).strip()
            }

        left_keys = material_keys(left)
        right_keys = material_keys(right_snapshot)
        return bool(left_keys) and left_keys == right_keys

    def create_ready_snapshot(
        self, session: Session, *, course_id: int, owner_user_id: int,
    ) -> Optional[CourseCorpusSnapshot]:
        """Freeze all current material versions only when every one parsed.

        Returning ``None`` is normal while other material tasks are still in
        flight.  A failed material never silently enters a course corpus.
        """
        rows = list(session.exec(select(SourceMaterialVersion, SourceMaterial).join(
            SourceMaterial, SourceMaterial.material_id == SourceMaterialVersion.material_id,
        ).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.is_current == True,  # noqa: E712
        ).order_by(SourceMaterial.id, SourceMaterialVersion.id)).all())
        # Older builds may already contain duplicate material rows created by
        # the pre-idempotency uploader.  Their bytes are identical, so retain
        # one deterministic current version per content hash rather than
        # feeding the same document to retrieval and initial prep repeatedly.
        included_rows: list[tuple[SourceMaterialVersion, SourceMaterial]] = []
        included_content_keys: set[str] = set()
        for version, material in rows:
            if not material.include_in_course_corpus:
                continue
            content_key = (version.file_hash or version.version_id).strip()
            if content_key in included_content_keys:
                logger.info(
                    "Skipping duplicate current course material in corpus: course_id=%s version_id=%s",
                    course_id,
                    version.version_id,
                )
                continue
            included_content_keys.add(content_key)
            included_rows.append((version, material))
        if not included_rows:
            return None

        # Failed or still-running material is intentionally not silently
        # omitted. The teacher must retry it or explicitly exclude it first.
        allowed_statuses = {MaterialStatus.PARSED, MaterialStatus.NEEDS_REVIEW}
        if any(version.parse_status not in allowed_statuses for version, _ in included_rows):
            return None

        run_ids: list[str] = []
        ir_version_ids: list[str] = []
        item_specs: list[dict] = []
        warnings: list[str] = []
        for version, material in included_rows:
            run = session.exec(select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_version_id == version.version_id,
                DocumentParseRun.status.in_([ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS]),
            ).order_by(DocumentParseRun.finished_at.desc())).first()
            if run is None:
                return None
            if not run.document_ir_version_id:
                return None
            ir_version = session.exec(select(DocumentIRVersion).where(
                DocumentIRVersion.ir_version_id == run.document_ir_version_id,
                DocumentIRVersion.course_id == course_id,
                DocumentIRVersion.material_version_id == version.version_id,
            )).first()
            if ir_version is None:
                return None
            run_ids.append(run.run_id)
            ir_version_ids.append(ir_version.ir_version_id)
            quality_warning = ""
            if run.status == ParseRunStatus.PARTIAL_SUCCESS or version.parse_status == MaterialStatus.NEEDS_REVIEW:
                quality_warning = f"{material.name}: 解析部分成功，构建结果需要教师检查"
                warnings.append(quality_warning)
            item_specs.append({
                "material_id": material.material_id,
                "material_version_id": version.version_id,
                "material_role": material.material_role,
                "priority": ROLE_PRIORITY.get(material.material_role, ROLE_PRIORITY["reference"]),
                "document_ir_version_id": ir_version.ir_version_id,
                "parse_run_id": run.run_id,
                "quality_warning": quality_warning,
            })

        version_ids = sorted(version.version_id for version, _ in included_rows)
        run_ids = sorted(run_ids)
        content_hash = hashlib.sha256(json.dumps(
            {"items": sorted(item_specs, key=lambda item: item["material_version_id"])}, sort_keys=True,
        ).encode("utf-8")).hexdigest()
        existing = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.content_hash == content_hash,
            CourseCorpusSnapshot.status == CorpusSnapshotStatus.READY,
        )).first()
        if existing:
            return existing

        for old in session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.status == CorpusSnapshotStatus.READY,
        )).all():
            old.status = CorpusSnapshotStatus.SUPERSEDED
            session.add(old)

        snapshot = CourseCorpusSnapshot(
            course_id=course_id,
            status=CorpusSnapshotStatus.READY,
            material_version_ids=version_ids,
            parse_run_ids=run_ids,
            document_ir_version_ids=sorted(ir_version_ids),
            warnings=warnings,
            content_hash=content_hash,
            created_by=owner_user_id,
        )
        session.add(snapshot)
        session.flush()
        for item_spec in item_specs:
            session.add(CourseCorpusItem(
                corpus_snapshot_id=snapshot.corpus_snapshot_id,
                course_id=course_id,
                included=True,
                **item_spec,
            ))
        session.flush()
        return snapshot

    def ensure_retrieval_snapshot(
        self, session: Session, *, corpus: CourseCorpusSnapshot,
    ) -> CourseRetrievalSnapshot:
        """Create the teacher-side candidate retrieval selection for a corpus.

        This is intentionally separate from the snapshot frozen at publication:
        builders may inspect all parsed candidate material, while learners may
        only read the reviewed chunk IDs captured by
        :meth:`freeze_release_retrieval_snapshot`.
        """
        existing = session.exec(select(CourseRetrievalSnapshot).where(
            CourseRetrievalSnapshot.course_id == corpus.course_id,
            CourseRetrievalSnapshot.corpus_snapshot_id == corpus.corpus_snapshot_id,
            CourseRetrievalSnapshot.snapshot_kind == "candidate",
        )).first()
        if existing:
            return existing
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == corpus.course_id,
            RetrievalChunk.ir_version_id.in_(list(corpus.document_ir_version_ids or [])),
        )).all())
        retrieval = CourseRetrievalSnapshot(
            course_id=corpus.course_id,
            corpus_snapshot_id=corpus.corpus_snapshot_id,
            material_version_ids=list(corpus.material_version_ids or []),
            document_ir_version_ids=list(corpus.document_ir_version_ids or []),
            snapshot_kind="candidate",
            retrieval_chunk_ids=sorted(chunk.chunk_id for chunk in chunks),
            evidence_anchor_ids=sorted({
                anchor_id for chunk in chunks for anchor_id in (chunk.anchor_ids or [])
            }),
            status="ready",
        )
        session.add(retrieval)
        session.flush()
        return retrieval

    def freeze_release_retrieval_snapshot(
        self, session: Session, *, corpus: CourseCorpusSnapshot,
    ) -> Optional[CourseRetrievalSnapshot]:
        """Freeze exactly the teacher-confirmed chunks for a course release.

        A subsequent evidence decision or reparse may change chunk status, but
        it cannot alter this selection.  Returning ``None`` means the course
        has no student-safe retrieval material yet and publication must stop.
        """
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == corpus.course_id,
            RetrievalChunk.ir_version_id.in_(list(corpus.document_ir_version_ids or [])),
            RetrievalChunk.status == "active",
        )).all())
        if not chunks:
            return None

        chunk_ids = sorted({chunk.chunk_id for chunk in chunks})
        anchor_ids = sorted({
            anchor_id for chunk in chunks for anchor_id in (chunk.anchor_ids or [])
        })
        # A new snapshot is required whenever the reviewed set changes.  The
        # lookup also makes retrying the same publish request idempotent.
        release_snapshots = list(session.exec(select(CourseRetrievalSnapshot).where(
            CourseRetrievalSnapshot.course_id == corpus.course_id,
            CourseRetrievalSnapshot.corpus_snapshot_id == corpus.corpus_snapshot_id,
            CourseRetrievalSnapshot.snapshot_kind == "release",
            CourseRetrievalSnapshot.status == "ready",
        )).all())
        existing = next((snapshot for snapshot in release_snapshots if
            list(snapshot.retrieval_chunk_ids or []) == chunk_ids
            and list(snapshot.evidence_anchor_ids or []) == anchor_ids
        ), None)
        if existing:
            return existing

        retrieval = CourseRetrievalSnapshot(
            course_id=corpus.course_id,
            corpus_snapshot_id=corpus.corpus_snapshot_id,
            material_version_ids=list(corpus.material_version_ids or []),
            document_ir_version_ids=list(corpus.document_ir_version_ids or []),
            snapshot_kind="release",
            retrieval_chunk_ids=chunk_ids,
            evidence_anchor_ids=anchor_ids,
            status="ready",
        )
        session.add(retrieval)
        session.flush()
        return retrieval

    def create_build_task(
        self, session: Session, *, corpus: CourseCorpusSnapshot, owner_user_id: int,
        trigger: str = "auto_after_materials_ready",
        quiet_window_seconds: int = DEFAULT_CORPUS_QUIET_WINDOW_SECONDS,
        force_initial: bool = False,
    ) -> tuple[CourseDraftBuildTask, str]:
        active_builds = list(session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.course_id == corpus.course_id,
            CourseDraftBuildTask.status.in_([CourseDraftBuildStatus.QUEUED, CourseDraftBuildStatus.RUNNING]),
        )).all())
        same_corpus = next((build for build in active_builds
                            if build.corpus_snapshot_id == corpus.corpus_snapshot_id), None)

        # Durable course-level concurrency lock: a new corpus supersedes and
        # cancels every queued/running build for this course before its own
        # orchestration row is created.  The handler also re-checks this
        # boundary between LLM stages, so an in-flight request cannot publish
        # stale results after the material set changes.
        for older in active_builds:
            if older.corpus_snapshot_id == corpus.corpus_snapshot_id:
                continue
            older.status = CourseDraftBuildStatus.CANCELLED
            older.error_code = "CORPUS_CHANGED"
            older.error_message = "新课程语料快照已生成，旧备课任务已取消"
            older.finished_at = utcnow_aware()
            session.add(older)
            if older.task_id:
                try:
                    task = task_service.get_task(session, older.task_id)
                    if task.status in {"pending", "running"}:
                        task_service.cancel(session, older.task_id, reason=older.error_message)
                except ValueError:
                    logger.info("Course build task %s was already terminal", older.task_id)

        if same_corpus is not None:
            return same_corpus, same_corpus.task_id or ""

        latest_outline = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == corpus.course_id,
        ).order_by(CourseOutlineVersion.version.desc())).first()
        latest_script = session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.course_id == corpus.course_id,
        ).order_by(TeachingScriptVersion.version.desc())).first()
        # A teacher may explicitly discard an untouched system-generated
        # initial draft and ask the preparation agent to regenerate it.  The
        # caller is responsible for enforcing that narrow safety condition;
        # all normal rebuilds remain proposals once a draft exists.
        mode = "initial" if force_initial or latest_outline is None else "proposal"
        not_before_at = self._quiet_window_deadline(
            session, course_id=corpus.course_id, quiet_window_seconds=quiet_window_seconds,
        )
        # Create the orchestration row first so its public identifier is part of
        # the durable TaskRecord payload.  The generic retry endpoint rebuilds
        # worker input exclusively from that payload; passing build_task_id only
        # to the first in-memory submit made every later retry lose this value.
        build = CourseDraftBuildTask(
            course_id=corpus.course_id,
            corpus_snapshot_id=corpus.corpus_snapshot_id,
            owner_user_id=owner_user_id,
            trigger=trigger,
            generation_mode=mode,
            base_outline_version_id=latest_outline.outline_version_id if latest_outline else None,
            base_script_version_id=latest_script.script_version_id if latest_script else None,
            not_before_at=not_before_at,
        )
        task_view = task_service.create_task(session, TaskCreateRequest(
            task_type="course_draft_build",
            owner_user_id=owner_user_id,
            course_id=corpus.course_id,
            input_summary="汇总已解析课程材料，生成课程建设草稿",
            input_payload={
                "course_id": corpus.course_id,
                "corpus_snapshot_id": corpus.corpus_snapshot_id,
                "build_task_id": build.build_task_id,
            },
            resource_links=[
                {"resource_kind": "course", "resource_id": str(corpus.course_id), "relation": "input"},
                {"resource_kind": "course_corpus_snapshot", "resource_id": corpus.corpus_snapshot_id, "relation": "input"},
            ],
        ))
        build.task_id = task_view.task_id
        session.add(build)
        session.flush()
        return build, task_view.task_id

    def repair_legacy_build_task_retry(
        self,
        session: Session,
        *,
        task_id: str,
        owner_user_id: int,
    ) -> bool:
        """Repair the retry payload written by older course-build code.

        Older rows omitted ``build_task_id`` from ``TaskRecord.input_payload``.
        After a normal build failure, pressing retry therefore replaced the
        original error with a non-retryable ``VALIDATION_FAILED``.  Recovery is
        deliberately narrow: the task owner, task/build linkage, course, corpus
        snapshot, and the legacy failure signature must all match.
        """
        from app.models.task_model import TaskEventRecord, TaskRecord

        record = session.exec(select(TaskRecord).where(
            TaskRecord.task_id == task_id,
            TaskRecord.owner_user_id == owner_user_id,
            TaskRecord.task_type == "course_draft_build",
        )).first()
        if record is None or record.status != "failed" or record.error_code != "VALIDATION_FAILED":
            return False

        try:
            payload = json.loads(record.input_payload) if record.input_payload else {}
        except (TypeError, ValueError):
            payload = {}
        if payload.get("build_task_id"):
            return False

        build = session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.task_id == task_id,
            CourseDraftBuildTask.course_id == record.course_id,
            CourseDraftBuildTask.corpus_snapshot_id == str(payload.get("corpus_snapshot_id") or ""),
        )).first()
        if build is None:
            return False

        payload["course_id"] = build.course_id
        payload["corpus_snapshot_id"] = build.corpus_snapshot_id
        payload["build_task_id"] = build.build_task_id
        record.input_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        record.retryable = True
        record.updated_at = utcnow_aware()
        session.add(record)
        session.add(TaskEventRecord(
            task_id=task_id,
            event_type="retry_payload_repaired",
            message="已恢复旧版课程草稿构建任务的重试参数",
            created_at=record.updated_at,
        ))
        session.commit()
        return True

    def create_update_proposal(
        self,
        session: Session,
        *,
        corpus: CourseCorpusSnapshot,
        created_by: int | None,
    ) -> PatchProposal:
        """Turn newly parsed corpus facts into concrete, teacher-reviewed edits.

        Rebuilds after the first draft must not overwrite the teacher's work.
        The proposal adds at most one evidence-linked knowledge point and its
        script, and never attaches content below a locked section.
        """
        existing = session.exec(select(PatchProposal).where(
            PatchProposal.course_id == corpus.course_id,
            PatchProposal.tool_name == "CourseBuildAgent",
            PatchProposal.status == "pending",
            PatchProposal.reason.contains(corpus.corpus_snapshot_id),
        )).first()
        if existing is not None:
            return existing

        outline = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == corpus.course_id,
        ).order_by(CourseOutlineVersion.version.desc())).first()
        if outline is None:
            raise ValueError("后续构建缺少基准课程目录")
        nodes = list(session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_version_id == outline.outline_version_id,
        ).order_by(CourseOutlineNode.order_index)).all())
        sections = [node for node in nodes if node.node_type == OutlineNodeType.SECTION and node.locked_by is None]
        if not sections:
            raise ValueError("所有课程 section 均已锁定，无法为新材料创建可审核提案")

        known_blocks = {
            block_id
            for node in nodes
            for block_id in (node.source_block_refs or [])
        }
        blocks = list(session.exec(select(DocumentBlock).where(
            DocumentBlock.course_id == corpus.course_id,
            DocumentBlock.run_id.in_(list(corpus.parse_run_ids or [])),
        ).order_by(DocumentBlock.page_or_slide, DocumentBlock.order_index)).all())
        candidate = next((block for block in blocks if (block.text or "").strip()
                          and block.block_id not in known_blocks
                          and block.semantic_role in {"knowledge_title", "section_title", "explanation"}), None)
        if candidate is None:
            candidate = next((block for block in blocks if (block.text or "").strip()
                              and block.block_id not in known_blocks), None)
        if candidate is None:
            raise ValueError("新课程语料没有可形成教学提案的新增内容")

        evidence_ids = list(session.exec(select(EvidenceSpan.span_id).where(
            EvidenceSpan.course_id == corpus.course_id,
            EvidenceSpan.block_id == candidate.block_id,
            EvidenceSpan.status == EvidenceSpanStatus.CONFIRMED,
        )).all())
        parent = sections[0]
        sibling_order = max((node.order_index for node in nodes if node.parent_node_id == parent.outline_node_id), default=-1) + 1
        title = (candidate.text or "").strip().split("\n", 1)[0][:300]
        new_outline_id = f"on_corpus_{candidate.block_id[-20:]}"
        proposal = PatchProposal(
            course_id=corpus.course_id,
            tool_name="CourseBuildAgent",
            policy_version="course-build-agent/2.1",
            reason=(f"材料集合已更新（{corpus.corpus_snapshot_id}）：建议将新增材料内容加入“{parent.title}”。"
                    "教师接受后才会写入课程草稿；已锁定节点未进入本提案。"),
            created_by=created_by,
        )
        session.add(proposal)
        session.flush()
        outline_payload = {
            "outline_node_id": new_outline_id,
            "parent_node_id": parent.outline_node_id,
            "node_type": OutlineNodeType.KNOWLEDGE_POINT.value,
            "title": title,
            "order_index": sibling_order,
            "source_block_refs": [candidate.block_id],
        }
        session.add(PatchProposalOperation(
            proposal_id=proposal.proposal_id, course_id=corpus.course_id,
            operation=PatchOperation.ADD, target="outline:new:title", before="",
            after=json.dumps(outline_payload, ensure_ascii=False),
            reason="新增材料包含尚未纳入课程树的知识内容；下游影响：接受后需复核 PPT 映射和练习建议。",
            evidence_refs=evidence_ids or None, policy_version=proposal.policy_version,
        ))
        session.add(PatchProposalOperation(
            proposal_id=proposal.proposal_id, course_id=corpus.course_id,
            operation=PatchOperation.ADD, target="script:new:content", before="",
            after=json.dumps({
                "outline_node_id": new_outline_id,
                "content": (candidate.text or "").strip(),
                "evidence_refs": evidence_ids,
            }, ensure_ascii=False),
            reason="为新增知识点提供与原文块绑定的初始讲稿。",
            evidence_refs=evidence_ids or None, policy_version=proposal.policy_version,
        ))
        session.flush()
        return proposal

    def invalidate_queued_builds(self, session: Session, *, course_id: int, reason: str) -> None:
        """Cancel only builds that have not started when a material set changes."""
        builds = session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.course_id == course_id,
            CourseDraftBuildTask.status == CourseDraftBuildStatus.QUEUED,
        )).all()
        for build in builds:
            build.status = CourseDraftBuildStatus.CANCELLED
            build.error_code = "CORPUS_CHANGED"
            build.error_message = reason[:500]
            session.add(build)
            if build.task_id:
                try:
                    task = task_service.get_task(session, build.task_id)
                    if task.status in {"pending", "running"}:
                        task_service.cancel(session, build.task_id, reason=reason)
                    else:
                        # A process restart may leave the orchestration row
                        # queued while its durable task is already terminal.
                        # The stale build still must be cancelled, but there
                        # is no task transition left to perform.
                        logger.info(
                            "Course build task %s already terminal (%s); "
                            "only invalidated its stale build record",
                            build.task_id,
                            task.status,
                        )
                except ValueError:
                    # The handler validates freshness before generating; an
                    # already running task is therefore still safe.
                    logger.info("Course build task %s was no longer cancellable", build.task_id)

    def is_snapshot_current(self, session: Session, *, corpus: CourseCorpusSnapshot) -> bool:
        """Verify no included current material changed after this snapshot."""
        current = self.create_ready_snapshot(
            session, course_id=corpus.course_id, owner_user_id=corpus.created_by or 0,
        )
        return bool(current and current.corpus_snapshot_id == corpus.corpus_snapshot_id)

    @staticmethod
    def _quiet_window_deadline(
        session: Session, *, course_id: int, quiet_window_seconds: int,
    ) -> datetime:
        """Start the 5–10 second window at the last upload or parse completion."""
        latest_at = utcnow_aware()
        versions = session.exec(select(SourceMaterialVersion).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.is_current == True,  # noqa: E712
        )).all()
        for version in versions:
            version_created_at = _as_utc(version.created_at)
            if version_created_at and version_created_at > latest_at:
                latest_at = version_created_at
            run = session.exec(select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_version_id == version.version_id,
                DocumentParseRun.status.in_([ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS]),
            ).order_by(DocumentParseRun.finished_at.desc())).first()
            run_finished_at = _as_utc(run.finished_at) if run else None
            if run_finished_at and run_finished_at > latest_at:
                latest_at = run_finished_at
        return latest_at + timedelta(seconds=max(0, quiet_window_seconds))

    def current_material_type_by_version(self, session: Session, *, course_id: int) -> dict[str, str]:
        rows = session.exec(select(SourceMaterialVersion, SourceMaterial).join(
            SourceMaterial, SourceMaterial.material_id == SourceMaterialVersion.material_id,
        ).where(SourceMaterialVersion.course_id == course_id)).all()
        return {version.version_id: material.material_type for version, material in rows}


course_corpus_service = CourseCorpusService()


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes even for timezone-aware columns."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
