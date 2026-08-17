"""Build, validate, and atomically activate immutable course knowledge bundles."""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.time_utils import utcnow_aware
from app.models.course_build_model import CourseRetrievalSnapshot
from app.models.document_parse_model import (
    CitationStatus,
    EvidenceAnchor,
    EvidenceCitation,
    EvidenceSpan,
    EvidenceSpanStatus,
    RetrievalChunk,
)
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
    EvidenceStatus,
    GraphSnapshotRecord,
    SnapshotStatus,
)
from app.models.knowledge_bundle_model import (
    CourseKnowledgeActivation,
    CourseKnowledgeBundle,
    CourseKnowledgeHead,
    CourseVectorIndex,
    GraphRagRun,
    GraphRagRunStatus,
    KnowledgeBundleStatus,
    VectorIndexStatus,
)
from app.platform.knowledge.document_ir_exporter import CanonicalDocumentIRExporter
from app.platform.knowledge.document_ir_exporter import load_graph_rag_input_manifest
from app.platform.knowledge.embedding import embedding_provider_from_settings
from app.platform.knowledge.graphrag_runner import GraphRagRunError, GraphRagRunner
from app.platform.knowledge.lancedb_provider import (
    LanceDbCourseVectorProvider,
    VectorIndexError,
)
from app.services.document_parse_service import document_parse_service
from app.services.graphrag_identity_service import GraphRagIdentityService
from app.services.task_service import TaskCreateRequest, task_service


class KnowledgeBundleError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class KnowledgeBundleService:
    def __init__(self) -> None:
        self.exporter = CanonicalDocumentIRExporter()
        self.identity = GraphRagIdentityService()

    # ------------------------------------------------------------------
    # GraphRAG draft generation
    # ------------------------------------------------------------------

    def request_regeneration(
        self,
        session: Session,
        *,
        course_id: int,
        actor_user_id: int,
        reason: str,
        instructions: str = "",
        source_scope: dict | None = None,
        relation_profile: list[str] | None = None,
        parent_run_id: str | None = None,
    ) -> tuple[GraphRagRun, dict]:
        if not settings.KNOWLEDGE_BUNDLE_ENABLED or not settings.GRAPHRAG_ENABLED:
            raise KnowledgeBundleError("GRAPHRAG_NOT_CONFIGURED")
        reason = reason.strip()
        if not reason:
            raise KnowledgeBundleError("REGENERATION_REASON_REQUIRED")
        scoped_chunk_ids = self._resolve_source_chunk_ids(
            session,
            course_id=course_id,
            source_scope=source_scope or {},
        )
        input_hash = self._course_input_hash(
            session,
            course_id,
            chunk_ids=scoped_chunk_ids,
        )
        config_hash = self._effective_config_hash()
        runs = session.exec(select(GraphRagRun).where(
            GraphRagRun.course_id == course_id,
            GraphRagRun.input_content_hash == input_hash,
            GraphRagRun.effective_config_hash == config_hash,
            GraphRagRun.regeneration_reason == reason,
            GraphRagRun.regeneration_instructions == instructions.strip(),
            GraphRagRun.status.in_([
                GraphRagRunStatus.QUEUED,
                GraphRagRunStatus.EXPORTING,
                GraphRagRunStatus.EXTRACTING,
                GraphRagRunStatus.CLASSIFYING,
                GraphRagRunStatus.RECONCILING,
                GraphRagRunStatus.AWAITING_REVIEW,
            ]),
        ).order_by(GraphRagRun.created_at.desc())).all()
        # 去重键必须包含 relation_profile：仅改关系策略时不应静默复用旧策略产物。
        existing = next((
            r for r in runs
            if list(r.relation_profile or []) == list(relation_profile or [])
        ), None)
        # 相同输入+配置但 FAILED 且 GraphRAG 产物完整的 run 直接复用：
        # 重试时 _load_complete_outputs 命中缓存，零 LLM 调用只重跑 reconcile，
        # 避免 regenerate 新建 run 完整重跑 build_index 重复烧钱。
        if existing is None:
            failed = session.exec(select(GraphRagRun).where(
                GraphRagRun.course_id == course_id,
                GraphRagRun.input_content_hash == input_hash,
                GraphRagRun.effective_config_hash == config_hash,
                GraphRagRun.regeneration_reason == reason,
                GraphRagRun.regeneration_instructions == instructions.strip(),
                GraphRagRun.status == GraphRagRunStatus.FAILED,
            ).order_by(GraphRagRun.created_at.desc())).first()
            if (
                failed is not None
                and list(failed.relation_profile or []) == list(relation_profile or [])
                and self._has_complete_graph_artifacts(failed)
            ):
                existing = failed
        if existing is not None:
            task = task_service.get_task(session, existing.task_id) if existing.task_id else None
            return existing, task.to_dict() if task else {}

        run = GraphRagRun(
            course_id=course_id,
            parent_run_id=parent_run_id,
            status=GraphRagRunStatus.QUEUED,
            prompt_policy_version=settings.GRAPHRAG_PROMPT_POLICY,
            completion_provider=settings.GRAPHRAG_COMPLETION_PROVIDER,
            completion_model=settings.GRAPHRAG_COMPLETION_MODEL,
            embedding_provider=settings.GRAPHRAG_EMBEDDING_PROVIDER,
            embedding_model=settings.GRAPHRAG_EMBEDDING_MODEL,
            effective_config_hash=config_hash,
            input_content_hash=input_hash,
            input_chunk_count=len(scoped_chunk_ids) if scoped_chunk_ids is not None else (
                session.exec(select(func.count(RetrievalChunk.id)).where(
                    RetrievalChunk.course_id == course_id,
                )).one()
            ),
            regeneration_reason=reason,
            regeneration_instructions=instructions.strip(),
            source_scope=source_scope or {},
            relation_profile=relation_profile or [],
            created_by=actor_user_id,
        )
        session.add(run)
        session.flush()
        task = task_service.create_task(session, TaskCreateRequest(
            task_type="knowledge.graphrag_build",
            owner_user_id=actor_user_id,
            course_id=course_id,
            input_summary=f"课程 {course_id} GraphRAG 语义图谱构建",
            input_payload={"run_id": run.run_id, "course_id": course_id},
            resource_links=[{
                "resource_kind": "graphrag_run",
                "resource_id": run.run_id,
                "relation": "output",
            }],
            idempotency_key=f"knowledge-graphrag:{run.run_id}",
        ))
        run.task_id = task.task_id
        session.add(run)
        session.commit()
        session.refresh(run)
        return run, task.to_dict()

    def execute_graphrag_run(
        self,
        session: Session,
        *,
        run_id: str,
        progress=None,
    ) -> GraphRagRun:
        run = self._require_run(session, run_id)
        if (
            run.status == GraphRagRunStatus.AWAITING_REVIEW
            and not self._draft_has_duplicate_identities(run)
        ):
            return run
        if run.status not in {
            GraphRagRunStatus.QUEUED,
            GraphRagRunStatus.EXPORTING,
            GraphRagRunStatus.EXTRACTING,
            GraphRagRunStatus.CLASSIFYING,
            GraphRagRunStatus.AWAITING_REVIEW,
        }:
            raise KnowledgeBundleError("GRAPH_RUN_STATE_CONFLICT")
        root = self._run_root(run.course_id, run.run_id)
        run.status = GraphRagRunStatus.EXPORTING
        run.artifact_root_uri = str(root)
        session.add(run)
        session.commit()
        if progress:
            progress(5, "export_document_ir")
        scoped_chunk_ids = self._resolve_source_chunk_ids(
            session,
            course_id=run.course_id,
            source_scope=run.source_scope or {},
        )
        manifest = self.exporter.export(
            session,
            course_id=run.course_id,
            output_dir=root / "input",
            chunk_ids=scoped_chunk_ids,
        )
        run.input_manifest_uri = str(root / "input" / "input_manifest.json")
        run.input_content_hash = manifest.input_content_hash
        run.input_chunk_count = manifest.chunk_count
        run.status = GraphRagRunStatus.EXTRACTING
        session.add(run)
        session.commit()
        if progress:
            progress(15, "graphrag_extract")
        run.status = GraphRagRunStatus.CLASSIFYING
        session.add(run)
        session.commit()
        if progress:
            progress(45, "classify_relations")
        from app.services.platform_task_concurrency_service import get_config as get_platform_runtime_config
        runtime_config = get_platform_runtime_config(session)
        admin_budget = int(runtime_config.get("graphrag_max_input_tokens") or 0)
        artifacts = GraphRagRunner().run(
            manifest=manifest,
            artifact_root=root,
            policy_context={
                "reason": run.regeneration_reason,
                "instructions": run.regeneration_instructions,
                "source_scope": run.source_scope or {},
                "relation_profile": run.relation_profile or [],
                "prompt_policy_version": run.prompt_policy_version,
            },
            max_input_tokens=admin_budget or settings.GRAPHRAG_MAX_INPUT_TOKENS,
        )
        run.status = GraphRagRunStatus.RECONCILING
        session.add(run)
        session.commit()
        if progress:
            progress(60, "reconcile_identity")
        graph = self.identity.reconcile(
            session,
            course_id=run.course_id,
            graphrag_run_id=run.run_id,
            manifest=manifest,
            artifacts=artifacts,
        )
        run.draft_nodes = list(graph.nodes)
        run.draft_relations = list(graph.relations)
        run.entity_count = len(graph.nodes)
        run.relationship_count = len(graph.relations)
        run.typed_relationship_count = sum(
            relation.get("type") != "RELATED_TO" for relation in graph.relations
        )
        run.output_manifest_uri = artifacts.output_manifest_uri
        run.token_usage = {"estimated_input_tokens": artifacts.estimated_input_tokens}
        run.estimated_cost = artifacts.estimated_max_cost
        run.warning_count = len(artifacts.warnings)
        run.warnings = list(artifacts.warnings)
        run.status = GraphRagRunStatus.AWAITING_REVIEW
        run.finished_at = utcnow_aware()
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    def refine_existing_run(
        self,
        session: Session,
        *,
        course_id: int,
        parent_run_id: str,
        actor_user_id: int,
        reason: str,
        identity_policy: str = "strict-title-anchor/1.0",
        filter_placeholders: bool = True,
    ) -> GraphRagRun:
        """Create a reviewable draft from immutable artifacts without model calls."""
        reason = reason.strip()
        if not reason:
            raise KnowledgeBundleError("REFINEMENT_REASON_REQUIRED")
        if identity_policy != "strict-title-anchor/1.0":
            raise KnowledgeBundleError("IDENTITY_POLICY_UNSUPPORTED")
        if not filter_placeholders:
            raise KnowledgeBundleError("PLACEHOLDER_FILTER_REQUIRED")

        parent = self._require_run(session, parent_run_id, course_id=course_id)
        if parent.status not in {
            GraphRagRunStatus.AWAITING_REVIEW,
            GraphRagRunStatus.APPROVED,
            GraphRagRunStatus.SUPERSEDED,
        }:
            raise KnowledgeBundleError("GRAPH_REFINEMENT_STATE_CONFLICT")
        artifact_source_run_id = str(
            (parent.source_scope or {}).get("artifact_source_run_id") or parent.run_id
        )
        existing_refinements = session.exec(select(GraphRagRun).where(
            GraphRagRun.course_id == course_id,
            GraphRagRun.method == "quality-refinement",
            GraphRagRun.regeneration_reason == reason,
            GraphRagRun.status.in_([
                GraphRagRunStatus.RECONCILING,
                GraphRagRunStatus.AWAITING_REVIEW,
            ]),
        ).order_by(GraphRagRun.created_at.desc())).all()
        for existing in existing_refinements:
            scope = existing.source_scope or {}
            if (
                scope.get("artifact_source_run_id") == artifact_source_run_id
                and scope.get("identity_policy") == identity_policy
                and scope.get("filter_placeholders") is True
            ):
                return existing
        artifact_root = self._run_root(course_id, artifact_source_run_id)
        manifest_path = artifact_root / "input" / "input_manifest.json"
        if not manifest_path.is_file():
            raise KnowledgeBundleError("GRAPH_ARTIFACTS_NOT_FOUND")
        try:
            manifest = load_graph_rag_input_manifest(manifest_path)
            if manifest.course_id != course_id:
                raise KnowledgeBundleError("GRAPH_INPUT_MANIFEST_MISMATCH")
            artifacts = GraphRagRunner().load_existing_artifacts(
                manifest=manifest,
                artifact_root=artifact_root,
            )
        except KnowledgeBundleError:
            raise
        except (GraphRagRunError, OSError, ValueError) as exc:
            code = getattr(exc, "code", str(exc).split(":", 1)[0])
            if code not in {
                "GRAPH_ARTIFACTS_NOT_FOUND",
                "GRAPH_INPUT_MANIFEST_MISMATCH",
                "GRAPH_OUTPUT_INVALID",
                "TYPED_RELATIONSHIPS_NOT_FOUND",
            }:
                code = "GRAPH_ARTIFACTS_NOT_FOUND"
            raise KnowledgeBundleError(code) from exc

        run = GraphRagRun(
            course_id=course_id,
            parent_run_id=parent.run_id,
            status=GraphRagRunStatus.RECONCILING,
            method="quality-refinement",
            prompt_policy_version=parent.prompt_policy_version,
            completion_provider=parent.completion_provider,
            completion_model=parent.completion_model,
            embedding_provider=parent.embedding_provider,
            embedding_model=parent.embedding_model,
            effective_config_hash=parent.effective_config_hash,
            input_content_hash=manifest.input_content_hash,
            input_chunk_count=manifest.chunk_count,
            artifact_root_uri=str(artifact_root),
            input_manifest_uri=str(manifest_path),
            output_manifest_uri=artifacts.output_manifest_uri,
            regeneration_reason=reason,
            regeneration_instructions=(
                "Deterministic identity remap; no completion, embedding, or "
                "relationship-classification provider is invoked."
            ),
            source_scope={
                "artifact_source_run_id": artifact_source_run_id,
                "identity_policy": identity_policy,
                "filter_placeholders": True,
            },
            relation_profile=list(parent.relation_profile or []),
            token_usage={
                "model_calls": 0,
                "completion_tokens": 0,
                "embedding_tokens": 0,
            },
            estimated_cost=0.0,
            actual_cost=0.0,
            created_by=actor_user_id,
        )
        session.add(run)
        session.flush()
        try:
            graph = self.identity.reconcile(
                session,
                course_id=course_id,
                graphrag_run_id=run.run_id,
                manifest=manifest,
                artifacts=artifacts,
            )
        except Exception as exc:
            session.rollback()
            code = (
                "IDENTITY_AMBIGUOUS"
                if type(exc).__name__ == "IdentityAmbiguousError"
                else str(exc).split(":", 1)[0]
            )
            if code not in {"IDENTITY_AMBIGUOUS", "GRAPH_OUTPUT_INVALID"}:
                code = "GRAPH_QUALITY_GATE_FAILED"
            raise KnowledgeBundleError(code) from exc

        quality_report = {
            **graph.quality_report,
            "parent_run_id": parent.run_id,
            "artifact_source_run_id": artifact_source_run_id,
            "model_calls": 0,
        }
        report_root = self._run_root(course_id, run.run_id) / "reports"
        report_root.mkdir(parents=True, exist_ok=True)
        report_path = report_root / "refinement_report.json"
        report_path.write_text(
            json.dumps(quality_report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        run.draft_nodes = list(graph.nodes)
        run.draft_relations = list(graph.relations)
        run.entity_count = len(graph.nodes)
        run.relationship_count = len(graph.relations)
        run.typed_relationship_count = sum(
            relation.get("type") != "RELATED_TO" for relation in graph.relations
        )
        run.warning_count = (
            quality_report["rejected_placeholder_count"]
            + quality_report["removed_placeholder_relationship_count"]
            + quality_report["removed_self_loop_count"]
            + quality_report["deduplicated_relationship_count"]
        )
        run.warnings = [{"code": "QUALITY_REFINEMENT_REPORT", **quality_report}]
        run.report_uri = str(report_path)
        run.status = GraphRagRunStatus.AWAITING_REVIEW
        run.finished_at = utcnow_aware()
        superseded = session.exec(select(GraphRagRun).where(
            GraphRagRun.course_id == course_id,
            GraphRagRun.method == "quality-refinement",
            GraphRagRun.run_id != run.run_id,
            GraphRagRun.status == GraphRagRunStatus.AWAITING_REVIEW,
        )).all()
        for previous in superseded:
            scope = previous.source_scope or {}
            if scope.get("artifact_source_run_id") == artifact_source_run_id:
                previous.status = GraphRagRunStatus.SUPERSEDED
                session.add(previous)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    @staticmethod
    def _draft_has_duplicate_identities(run: GraphRagRun) -> bool:
        node_ids = [
            str(node.get("id") or "")
            for node in run.draft_nodes or []
            if node.get("id")
        ]
        return len(node_ids) != len(set(node_ids))

    @staticmethod
    def _has_complete_graph_artifacts(run: GraphRagRun) -> bool:
        """True when the run's GraphRAG parquet outputs exist and are non-empty."""
        root = Path(run.artifact_root_uri) if run.artifact_root_uri else None
        if root is None or not root.is_dir():
            return False
        output_dir = root / "output"
        try:
            for name in GraphRagRunner.required_outputs:
                path = output_dir / f"{name}.parquet"
                if not path.is_file() or path.stat().st_size <= 0:
                    return False
            import pandas as pd
            for name in ("entities", "relationships"):
                frame = pd.read_parquet(output_dir / f"{name}.parquet")
                if frame.empty:
                    return False
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Whole-graph approval and indexing
    # ------------------------------------------------------------------

    def approve_draft(
        self,
        session: Session,
        *,
        course_id: int,
        run_id: str,
        actor_user_id: int,
        label: str = "",
    ) -> tuple[CourseKnowledgeBundle, dict]:
        run = self._require_run(session, run_id, course_id=course_id)
        if run.status == GraphRagRunStatus.APPROVED:
            existing = session.exec(select(CourseKnowledgeBundle).where(
                CourseKnowledgeBundle.course_id == course_id,
                CourseKnowledgeBundle.graphrag_run_id == run_id,
            )).first()
            if existing:
                vector = session.exec(select(CourseVectorIndex).where(
                    CourseVectorIndex.vector_index_id == existing.vector_index_id,
                )).first()
                task = (
                    task_service.get_task(session, vector.task_id).to_dict()
                    if vector is not None and vector.task_id else {}
                )
                return existing, task
        if run.status != GraphRagRunStatus.AWAITING_REVIEW:
            raise KnowledgeBundleError("GRAPH_RUN_NOT_REVIEWABLE")
        nodes = deepcopy(run.draft_nodes or [])
        relations = deepcopy(run.draft_relations or [])
        if not nodes or not relations:
            raise KnowledgeBundleError("GRAPH_OUTPUT_INVALID")

        anchor_node_ids: dict[str, int] = {}
        for node in nodes:
            identity_id = int(node.get("identity_id") or 0)
            for anchor_id in node.get("source_anchor_ids") or []:
                anchor_node_ids.setdefault(str(anchor_id), identity_id)
        all_anchor_ids = {
            str(anchor_id)
            for item in [*nodes, *relations]
            for anchor_id in item.get("source_anchor_ids") or []
        }
        evidence_by_anchor, citations_by_evidence = self._promote_evidence(
            session,
            course_id=course_id,
            anchor_ids=all_anchor_ids,
            anchor_node_ids=anchor_node_ids,
            actor_user_id=actor_user_id,
        )
        for item in [*nodes, *relations]:
            evidence_ids = sorted({
                evidence_id
                for anchor_id in item.get("source_anchor_ids") or []
                for evidence_id in evidence_by_anchor.get(str(anchor_id), set())
            })
            citation_ids = sorted({
                citation_id
                for evidence_id in evidence_ids
                for citation_id in citations_by_evidence.get(evidence_id, set())
            })
            if not evidence_ids or not citation_ids:
                raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
            item["evidence_ids"] = evidence_ids
            item["citation_ids"] = citation_ids

        # Reuse the established production validator, but do not expose this
        # snapshot until its vector index has passed validation.
        from app.services.graph_production_service import _validate_snapshot_content

        _validate_snapshot_content(session, course_id, nodes, relations)
        previous = session.exec(select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
            GraphSnapshotRecord.is_active == True,  # noqa: E712
        )).first()
        version = int(session.exec(select(func.max(GraphSnapshotRecord.version)).where(
            GraphSnapshotRecord.course_id == course_id,
        )).one() or 0) + 1
        snapshot = GraphSnapshotRecord(
            snapshot_id=str(uuid.uuid4()),
            course_id=course_id,
            nodes=nodes,
            relations=relations,
            version=version,
            ontology_version="edu-graph-graphrag/1.0",
            prev_snapshot_id=previous.snapshot_id if previous else None,
            status=SnapshotStatus.DRAFT,
            is_active=False,
            label=label or f"GraphRAG v{version}",
            node_count=len(nodes),
            relation_count=len(relations),
            created_by=actor_user_id,
        )
        session.add(snapshot)
        session.flush()

        retrieval = self._freeze_retrieval_snapshot(
            session,
            course_id=course_id,
            run=run,
            anchor_ids=all_anchor_ids,
        )
        bundle_version = int(session.exec(
            select(func.max(CourseKnowledgeBundle.version)).where(
                CourseKnowledgeBundle.course_id == course_id,
            )
        ).one() or 0) + 1
        head = session.exec(select(CourseKnowledgeHead).where(
            CourseKnowledgeHead.course_id == course_id,
        )).first()
        manifest_hash = _hash_payload({
            "run_id": run.run_id,
            "snapshot_id": snapshot.snapshot_id,
            "retrieval_snapshot_id": retrieval.retrieval_snapshot_id,
            "nodes": nodes,
            "relations": relations,
        })
        bundle = CourseKnowledgeBundle(
            course_id=course_id,
            version=bundle_version,
            prev_bundle_id=head.active_bundle_id if head else None,
            graphrag_run_id=run.run_id,
            corpus_snapshot_id=run.corpus_snapshot_id,
            graph_snapshot_id=snapshot.snapshot_id,
            retrieval_snapshot_id=retrieval.retrieval_snapshot_id,
            approval_manifest_hash=manifest_hash,
            content_hash=manifest_hash,
            status=KnowledgeBundleStatus.APPROVED_PENDING_INDEX,
            label=label or f"GraphRAG Bundle v{bundle_version}",
            approved_by=actor_user_id,
            approved_at=utcnow_aware(),
            created_by=actor_user_id,
        )
        session.add(bundle)
        session.flush()
        vector_index = CourseVectorIndex(
            course_id=course_id,
            bundle_id=bundle.bundle_id,
            graphrag_run_id=run.run_id,
            graph_snapshot_id=snapshot.snapshot_id,
            retrieval_snapshot_id=retrieval.retrieval_snapshot_id,
            provider="lancedb",
            embedding_provider=settings.GRAPHRAG_EMBEDDING_PROVIDER,
            embedding_model=settings.GRAPHRAG_EMBEDDING_MODEL,
            status=VectorIndexStatus.QUEUED,
        )
        session.add(vector_index)
        session.flush()
        bundle.vector_index_id = vector_index.vector_index_id
        run.status = GraphRagRunStatus.APPROVED
        self.supersede_sibling_refinement_drafts(session, approved_run=run)
        session.add_all([bundle, run])
        task = task_service.create_task(session, TaskCreateRequest(
            task_type="knowledge.vector_index",
            owner_user_id=actor_user_id,
            course_id=course_id,
            input_summary=f"课程 {course_id} 知识 Bundle 向量构建与激活",
            input_payload={
                "course_id": course_id,
                "bundle_id": bundle.bundle_id,
                "vector_index_id": vector_index.vector_index_id,
                "actor_user_id": actor_user_id,
            },
            resource_links=[
                {"resource_kind": "knowledge_bundle", "resource_id": bundle.bundle_id, "relation": "input"},
                {"resource_kind": "vector_index", "resource_id": vector_index.vector_index_id, "relation": "output"},
            ],
            idempotency_key=f"knowledge-vector:{bundle.bundle_id}",
        ))
        vector_index.task_id = task.task_id
        bundle.status = KnowledgeBundleStatus.INDEXING
        session.add_all([vector_index, bundle])
        session.commit()
        session.refresh(bundle)
        return bundle, task.to_dict()

    @staticmethod
    def supersede_sibling_refinement_drafts(
        session: Session,
        *,
        approved_run: GraphRagRun,
    ) -> int:
        """Retire alternative review drafts derived from the same raw artifacts."""
        if approved_run.method != "quality-refinement":
            return 0
        artifact_source_run_id = str(
            (approved_run.source_scope or {}).get("artifact_source_run_id") or ""
        )
        if not artifact_source_run_id:
            return 0
        changed = 0
        siblings = session.exec(select(GraphRagRun).where(
            GraphRagRun.course_id == approved_run.course_id,
            GraphRagRun.method == "quality-refinement",
            GraphRagRun.run_id != approved_run.run_id,
            GraphRagRun.status == GraphRagRunStatus.AWAITING_REVIEW,
        )).all()
        for sibling in siblings:
            if (
                (sibling.source_scope or {}).get("artifact_source_run_id")
                != artifact_source_run_id
            ):
                continue
            sibling.status = GraphRagRunStatus.SUPERSEDED
            session.add(sibling)
            changed += 1
        return changed

    def build_vector_index(
        self,
        session: Session,
        *,
        course_id: int,
        bundle_id: str,
        vector_index_id: str,
        actor_user_id: int | None = None,
        progress=None,
        embedding_provider=None,
    ) -> CourseKnowledgeBundle:
        bundle = self._require_bundle(session, course_id, bundle_id)
        vector_index = session.exec(select(CourseVectorIndex).where(
            CourseVectorIndex.course_id == course_id,
            CourseVectorIndex.vector_index_id == vector_index_id,
            CourseVectorIndex.bundle_id == bundle_id,
        )).first()
        if vector_index is None:
            raise KnowledgeBundleError("VECTOR_INDEX_NOT_FOUND")
        if vector_index.status == VectorIndexStatus.READY:
            return bundle
        vector_index.status = VectorIndexStatus.BUILDING
        bundle.status = KnowledgeBundleStatus.INDEXING
        session.add_all([vector_index, bundle])
        session.commit()
        if progress:
            progress(80, "vectorize_text_units")
        rows = self._vector_rows(session, bundle)
        provider = LanceDbCourseVectorProvider(
            embedding_provider=embedding_provider or embedding_provider_from_settings()
        )
        result = provider.build(
            course_id=course_id,
            bundle_id=bundle_id,
            graph_snapshot_id=bundle.graph_snapshot_id,
            text_units=rows["text_units"],
            entities=rows["entities"],
            evidence=rows["evidence"],
        )
        expected_counts = (
            len(rows["text_units"]),
            len(rows["entities"]),
            len(rows["evidence"]),
        )
        actual_counts = (
            result.text_unit_row_count,
            result.entity_row_count,
            result.evidence_row_count,
        )
        if actual_counts != expected_counts:
            raise KnowledgeBundleError("INDEX_MANIFEST_MISMATCH")
        probe = rows["evidence"][0]
        probe_results = provider.search(
            course_id=course_id,
            bundle_id=bundle_id,
            query=str(probe["text"]),
            top_k=min(20, max(6, len(rows["evidence"]))),
        )
        expected_citation = str(probe["citation_id"])
        if not any(
            expected_citation in (item.get("citation_ids") or [])
            for item in probe_results
        ):
            raise KnowledgeBundleError("INDEX_MANIFEST_MISMATCH")
        if progress:
            progress(94, "validate")
        vector_index.storage_uri = result.storage_uri
        vector_index.manifest_uri = result.manifest_uri
        vector_index.vector_dimension = result.vector_dimension
        vector_index.text_unit_row_count = result.text_unit_row_count
        vector_index.entity_row_count = result.entity_row_count
        vector_index.evidence_row_count = result.evidence_row_count
        vector_index.content_hash = result.manifest_hash
        vector_index.status = VectorIndexStatus.READY
        vector_index.validated_at = utcnow_aware()
        bundle.status = KnowledgeBundleStatus.READY
        session.add_all([vector_index, bundle])
        session.commit()
        self.activate_bundle(
            session,
            course_id=course_id,
            bundle_id=bundle_id,
            actor_user_id=actor_user_id,
            action="publish",
        )
        session.refresh(bundle)
        return bundle

    # ------------------------------------------------------------------
    # Activation, rollback and bootstrap
    # ------------------------------------------------------------------

    def activate_bundle(
        self,
        session: Session,
        *,
        course_id: int,
        bundle_id: str,
        actor_user_id: int | None,
        action: str,
    ) -> CourseKnowledgeBundle:
        bundle = self._require_bundle(session, course_id, bundle_id)
        if bundle.status != KnowledgeBundleStatus.READY or not bundle.vector_index_id:
            raise KnowledgeBundleError("BUNDLE_NOT_READY")
        vector_index = session.exec(select(CourseVectorIndex).where(
            CourseVectorIndex.course_id == course_id,
            CourseVectorIndex.vector_index_id == bundle.vector_index_id,
            CourseVectorIndex.status == VectorIndexStatus.READY,
        )).first()
        if vector_index is None:
            raise KnowledgeBundleError("VECTOR_INDEX_NOT_READY")
        provider = LanceDbCourseVectorProvider(
            embedding_provider=None
        )
        try:
            result = provider.validate(course_id=course_id, bundle_id=bundle_id)
        except VectorIndexError as exc:
            raise KnowledgeBundleError(str(exc)) from exc
        if result.manifest_hash != vector_index.content_hash:
            raise KnowledgeBundleError("INDEX_MANIFEST_MISMATCH")

        head = session.exec(select(CourseKnowledgeHead).where(
            CourseKnowledgeHead.course_id == course_id,
        )).first()
        if head is None:
            head = CourseKnowledgeHead(course_id=course_id)
            session.add(head)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise KnowledgeBundleError("ACTIVATION_CONFLICT") from exc
        previous_bundle_id = head.active_bundle_id
        expected_version = head.lock_version
        result_update = session.exec(
            update(CourseKnowledgeHead)
            .where(
                CourseKnowledgeHead.id == head.id,
                CourseKnowledgeHead.lock_version == expected_version,
            )
            .values(
                active_bundle_id=bundle_id,
                lock_version=expected_version + 1,
                updated_at=utcnow_aware(),
            )
        )
        if result_update.rowcount != 1:
            session.rollback()
            raise KnowledgeBundleError("ACTIVATION_CONFLICT")
        snapshots = list(session.exec(select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
        )).all())
        target_snapshot = None
        for snapshot in snapshots:
            if snapshot.snapshot_id == bundle.graph_snapshot_id:
                target_snapshot = snapshot
                snapshot.is_active = True
                snapshot.status = SnapshotStatus.PUBLISHED
                snapshot.published_at = snapshot.published_at or utcnow_aware()
            elif snapshot.is_active:
                snapshot.is_active = False
                snapshot.status = SnapshotStatus.SUPERSEDED
            session.add(snapshot)
        if target_snapshot is None:
            session.rollback()
            raise KnowledgeBundleError("GRAPH_SNAPSHOT_NOT_FOUND")
        active_node_keys = {str(node.get("id")) for node in target_snapshot.nodes or []}
        for node in session.exec(select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == course_id,
        )).all():
            if node.node_key in active_node_keys:
                node.status = CourseKnowledgeNodeStatus.PUBLISHED
            elif node.status == CourseKnowledgeNodeStatus.PUBLISHED:
                node.status = CourseKnowledgeNodeStatus.RETIRED
            node.updated_at = utcnow_aware()
            session.add(node)
        session.add(CourseKnowledgeActivation(
            course_id=course_id,
            bundle_id=bundle_id,
            previous_bundle_id=previous_bundle_id,
            action=action,
            actor_user_id=actor_user_id,
        ))
        session.commit()
        return bundle

    def bootstrap_existing_snapshot(
        self,
        session: Session,
        *,
        course_id: int,
        actor_user_id: int,
    ) -> tuple[CourseKnowledgeBundle, dict]:
        existing_head = session.exec(select(CourseKnowledgeHead).where(
            CourseKnowledgeHead.course_id == course_id,
            CourseKnowledgeHead.active_bundle_id.is_not(None),
        )).first()
        if existing_head:
            return self._require_bundle(
                session, course_id, str(existing_head.active_bundle_id)
            ), {}
        snapshot = session.exec(select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == course_id,
            GraphSnapshotRecord.is_active == True,  # noqa: E712
            GraphSnapshotRecord.status == SnapshotStatus.PUBLISHED,
        )).first()
        if snapshot is None:
            raise KnowledgeBundleError("GRAPH_SNAPSHOT_NOT_FOUND")
        anchor_ids = {
            str(anchor_id)
            for item in [*(snapshot.nodes or []), *(snapshot.relations or [])]
            for anchor_id in (
                item.get("source_anchor_ids")
                or item.get("anchor_ids")
                or []
            )
        }
        # Older snapshots may only carry Evidence IDs. Recover their anchors.
        evidence_ids = {
            str(evidence_id)
            for item in [*(snapshot.nodes or []), *(snapshot.relations or [])]
            for evidence_id in item.get("evidence_ids") or []
        }
        if evidence_ids:
            for evidence in session.exec(select(CourseEvidenceRecord).where(
                CourseEvidenceRecord.course_id == course_id,
                CourseEvidenceRecord.evidence_id.in_(evidence_ids),
                CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
            )).all():
                anchor_ids.update(str(item) for item in evidence.source_anchor_ids or [])
        pseudo_run = GraphRagRun(
            course_id=course_id,
            status=GraphRagRunStatus.APPROVED,
            method="legacy-bootstrap",
            prompt_policy_version="legacy-bootstrap/1",
            input_content_hash=self._course_input_hash(session, course_id, only_active=True),
            input_chunk_count=session.exec(select(func.count(RetrievalChunk.id)).where(
                RetrievalChunk.course_id == course_id,
                RetrievalChunk.status == "active",
            )).one(),
            entity_count=snapshot.node_count,
            relationship_count=snapshot.relation_count,
            typed_relationship_count=0,
            draft_nodes=deepcopy(snapshot.nodes or []),
            draft_relations=deepcopy(snapshot.relations or []),
            created_by=actor_user_id,
            finished_at=utcnow_aware(),
        )
        session.add(pseudo_run)
        session.flush()
        retrieval = self._freeze_retrieval_snapshot(
            session,
            course_id=course_id,
            run=pseudo_run,
            anchor_ids=anchor_ids,
            only_active=True,
        )
        latest_bundle = session.exec(select(CourseKnowledgeBundle).where(
            CourseKnowledgeBundle.course_id == course_id,
        ).order_by(CourseKnowledgeBundle.version.desc())).first()
        bundle_version = (latest_bundle.version if latest_bundle else 0) + 1
        bundle = CourseKnowledgeBundle(
            course_id=course_id,
            version=bundle_version,
            prev_bundle_id=latest_bundle.bundle_id if latest_bundle else None,
            graphrag_run_id=pseudo_run.run_id,
            graph_snapshot_id=snapshot.snapshot_id,
            retrieval_snapshot_id=retrieval.retrieval_snapshot_id,
            approval_manifest_hash=_hash_payload({
                "snapshot_id": snapshot.snapshot_id,
                "retrieval_snapshot_id": retrieval.retrieval_snapshot_id,
            }),
            content_hash=_hash_payload(snapshot.nodes or []),
            status=KnowledgeBundleStatus.INDEXING,
            label=f"Legacy Bootstrap v{bundle_version}",
            approved_by=actor_user_id,
            approved_at=utcnow_aware(),
            created_by=actor_user_id,
        )
        session.add(bundle)
        session.flush()
        vector_index = CourseVectorIndex(
            course_id=course_id,
            bundle_id=bundle.bundle_id,
            graphrag_run_id=pseudo_run.run_id,
            graph_snapshot_id=snapshot.snapshot_id,
            retrieval_snapshot_id=retrieval.retrieval_snapshot_id,
            embedding_provider=settings.GRAPHRAG_EMBEDDING_PROVIDER,
            embedding_model=settings.GRAPHRAG_EMBEDDING_MODEL,
        )
        session.add(vector_index)
        session.flush()
        bundle.vector_index_id = vector_index.vector_index_id
        task = task_service.create_task(session, TaskCreateRequest(
            task_type="knowledge.vector_index",
            owner_user_id=actor_user_id,
            course_id=course_id,
            input_summary=f"课程 {course_id} Bootstrap Bundle 向量构建",
            input_payload={
                "course_id": course_id,
                "bundle_id": bundle.bundle_id,
                "vector_index_id": vector_index.vector_index_id,
                "actor_user_id": actor_user_id,
            },
            idempotency_key=f"knowledge-vector:{bundle.bundle_id}",
        ))
        vector_index.task_id = task.task_id
        session.add_all([bundle, vector_index])
        session.commit()
        session.refresh(bundle)
        return bundle, task.to_dict()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_active_bundle(
        self, session: Session, course_id: int
    ) -> CourseKnowledgeBundle | None:
        head = session.exec(select(CourseKnowledgeHead).where(
            CourseKnowledgeHead.course_id == course_id,
        )).first()
        if head is None or not head.active_bundle_id:
            return None
        return session.exec(select(CourseKnowledgeBundle).where(
            CourseKnowledgeBundle.course_id == course_id,
            CourseKnowledgeBundle.bundle_id == head.active_bundle_id,
            CourseKnowledgeBundle.status == KnowledgeBundleStatus.READY,
        )).first()

    @staticmethod
    def serialize_bundle(bundle: CourseKnowledgeBundle) -> dict[str, Any]:
        return {
            "bundle_id": bundle.bundle_id,
            "course_id": bundle.course_id,
            "version": bundle.version,
            "prev_bundle_id": bundle.prev_bundle_id,
            "graphrag_run_id": bundle.graphrag_run_id,
            "graph_snapshot_id": bundle.graph_snapshot_id,
            "retrieval_snapshot_id": bundle.retrieval_snapshot_id,
            "vector_index_id": bundle.vector_index_id,
            "status": bundle.status.value,
            "label": bundle.label,
            "approved_by": bundle.approved_by,
            "approved_at": bundle.approved_at.isoformat() if bundle.approved_at else None,
            "created_at": bundle.created_at.isoformat(),
        }

    @staticmethod
    def serialize_run(run: GraphRagRun) -> dict[str, Any]:
        quality_report = next((
            item for item in (run.warnings or [])
            if isinstance(item, dict) and item.get("code") == "QUALITY_REFINEMENT_REPORT"
        ), None)
        return {
            "run_id": run.run_id,
            "course_id": run.course_id,
            "parent_run_id": run.parent_run_id,
            "task_id": run.task_id,
            "status": run.status.value,
            "method": run.method,
            "prompt_policy_version": run.prompt_policy_version,
            "completion_provider": run.completion_provider,
            "completion_model": run.completion_model,
            "embedding_provider": run.embedding_provider,
            "embedding_model": run.embedding_model,
            "input_content_hash": run.input_content_hash,
            "input_chunk_count": run.input_chunk_count,
            "entity_count": run.entity_count,
            "relationship_count": run.relationship_count,
            "typed_relationship_count": run.typed_relationship_count,
            "warning_count": run.warning_count,
            "warnings": run.warnings,
            "quality_report": quality_report,
            "report_uri": run.report_uri,
            "regeneration_reason": run.regeneration_reason,
            "regeneration_instructions": run.regeneration_instructions,
            "nodes": run.draft_nodes,
            "relations": run.draft_relations,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _promote_evidence(
        self,
        session: Session,
        *,
        course_id: int,
        anchor_ids: set[str],
        anchor_node_ids: dict[str, int],
        actor_user_id: int,
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        anchors = list(session.exec(select(EvidenceAnchor).where(
            EvidenceAnchor.course_id == course_id,
            EvidenceAnchor.anchor_id.in_(sorted(anchor_ids)),
        )).all()) if anchor_ids else []
        if len(anchors) != len(anchor_ids):
            raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
        evidence_by_anchor: dict[str, set[str]] = {}
        active_evidence = list(session.exec(select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == course_id,
            CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
        )).all())
        for evidence in active_evidence:
            for anchor_id in evidence.source_anchor_ids or []:
                evidence_by_anchor.setdefault(str(anchor_id), set()).add(evidence.evidence_id)
        for anchor in anchors:
            if evidence_by_anchor.get(anchor.anchor_id):
                continue
            spans = list(session.exec(select(EvidenceSpan).where(
                EvidenceSpan.course_id == course_id,
                EvidenceSpan.run_id == anchor.run_id,
                EvidenceSpan.ir_version_id == anchor.ir_version_id,
                EvidenceSpan.block_id == anchor.block_id,
                EvidenceSpan.char_start <= anchor.char_end,
                EvidenceSpan.char_end >= anchor.char_start,
            )).all())
            span = next((item for item in spans if item.status == EvidenceSpanStatus.CANDIDATE), None)
            if span is None:
                span = next((item for item in spans if item.status == EvidenceSpanStatus.CONFIRMED), None)
            if span is None:
                raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
            if span.status == EvidenceSpanStatus.CANDIDATE:
                _, evidence, citation = document_parse_service.confirm_evidence_span(
                    session,
                    course_id=course_id,
                    span_id=span.span_id,
                    confirmed_by=actor_user_id,
                    node_id=anchor_node_ids.get(anchor.anchor_id),
                )
                self._bind_formal_evidence_to_anchor(
                    session,
                    evidence=evidence,
                    citations=[citation],
                    anchor_id=anchor.anchor_id,
                )
                evidence_by_anchor.setdefault(anchor.anchor_id, set()).add(evidence.evidence_id)
            elif span.linked_evidence_id:
                evidence = session.exec(select(CourseEvidenceRecord).where(
                    CourseEvidenceRecord.course_id == course_id,
                    CourseEvidenceRecord.evidence_id == span.linked_evidence_id,
                    CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
                )).first()
                if evidence is None:
                    raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
                linked_citations = list(session.exec(select(EvidenceCitation).where(
                    EvidenceCitation.course_id == course_id,
                    EvidenceCitation.evidence_id == evidence.evidence_id,
                )).all())
                self._bind_formal_evidence_to_anchor(
                    session,
                    evidence=evidence,
                    citations=linked_citations,
                    anchor_id=anchor.anchor_id,
                )
                evidence_by_anchor.setdefault(anchor.anchor_id, set()).add(span.linked_evidence_id)
        evidence_ids = {
            evidence_id
            for values in evidence_by_anchor.values()
            for evidence_id in values
        }
        citations_by_evidence: dict[str, set[str]] = {}
        if evidence_ids:
            citations = session.exec(select(EvidenceCitation).where(
                EvidenceCitation.course_id == course_id,
                EvidenceCitation.evidence_id.in_(sorted(evidence_ids)),
                EvidenceCitation.student_visible == True,  # noqa: E712
                EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE]),
            )).all()
            for citation in citations:
                citations_by_evidence.setdefault(str(citation.evidence_id), set()).add(
                    citation.citation_id
                )
        if any(not citations_by_evidence.get(item) for item in evidence_ids):
            raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
        return evidence_by_anchor, citations_by_evidence

    @staticmethod
    def _bind_formal_evidence_to_anchor(
        session: Session,
        *,
        evidence: CourseEvidenceRecord,
        citations: list[EvidenceCitation],
        anchor_id: str,
    ) -> None:
        """Close an overlapping span to the exact GraphRAG source anchor."""
        if anchor_id not in (evidence.source_anchor_ids or []):
            evidence.source_anchor_ids = [
                *(evidence.source_anchor_ids or []),
                anchor_id,
            ]
            session.add(evidence)
        for citation in citations:
            if anchor_id not in (citation.source_anchor_ids or []):
                citation.source_anchor_ids = [
                    *(citation.source_anchor_ids or []),
                    anchor_id,
                ]
                session.add(citation)

    def _freeze_retrieval_snapshot(
        self,
        session: Session,
        *,
        course_id: int,
        run: GraphRagRun,
        anchor_ids: set[str],
        only_active: bool = False,
    ) -> CourseRetrievalSnapshot:
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == course_id,
        )).all())
        included = [
            chunk for chunk in chunks
            if set(str(item) for item in chunk.anchor_ids or []) & anchor_ids
            and (not only_active or chunk.status == "active")
        ]
        if not included:
            raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
        retrieval = CourseRetrievalSnapshot(
            course_id=course_id,
            corpus_snapshot_id=run.corpus_snapshot_id or f"knowledge:{run.run_id}",
            material_version_ids=[],
            document_ir_version_ids=sorted({item.ir_version_id for item in included}),
            snapshot_kind="release",
            retrieval_chunk_ids=sorted({item.chunk_id for item in included}),
            evidence_anchor_ids=sorted(anchor_ids),
            status="ready",
            provider_policy_version="active-knowledge-bundle/1",
        )
        session.add(retrieval)
        session.flush()
        return retrieval

    def _vector_rows(self, session: Session, bundle: CourseKnowledgeBundle) -> dict[str, list[dict]]:
        snapshot = session.exec(select(GraphSnapshotRecord).where(
            GraphSnapshotRecord.course_id == bundle.course_id,
            GraphSnapshotRecord.snapshot_id == bundle.graph_snapshot_id,
        )).first()
        retrieval = session.exec(select(CourseRetrievalSnapshot).where(
            CourseRetrievalSnapshot.course_id == bundle.course_id,
            CourseRetrievalSnapshot.retrieval_snapshot_id == bundle.retrieval_snapshot_id,
            CourseRetrievalSnapshot.snapshot_kind == "release",
        )).first()
        if snapshot is None or retrieval is None:
            raise KnowledgeBundleError("BUNDLE_MANIFEST_INVALID")
        evidence_ids = {
            str(item)
            for graph_item in [*(snapshot.nodes or []), *(snapshot.relations or [])]
            for item in graph_item.get("evidence_ids") or []
        }
        evidence_records = list(session.exec(select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == bundle.course_id,
            CourseEvidenceRecord.evidence_id.in_(sorted(evidence_ids)),
            CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
        )).all())
        citations = list(session.exec(select(EvidenceCitation).where(
            EvidenceCitation.course_id == bundle.course_id,
            EvidenceCitation.evidence_id.in_(sorted(evidence_ids)),
            EvidenceCitation.student_visible == True,  # noqa: E712
            EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE]),
        )).all())
        citations_by_evidence: dict[str, list[EvidenceCitation]] = {}
        for citation in citations:
            citations_by_evidence.setdefault(str(citation.evidence_id), []).append(citation)
        evidence_by_anchor: dict[str, set[str]] = {}
        for evidence in evidence_records:
            for anchor_id in evidence.source_anchor_ids or []:
                evidence_by_anchor.setdefault(str(anchor_id), set()).add(evidence.evidence_id)
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == bundle.course_id,
            RetrievalChunk.chunk_id.in_(list(retrieval.retrieval_chunk_ids or [])),
        )).all())
        node_by_anchor: dict[str, set[str]] = {}
        for node in snapshot.nodes or []:
            for anchor_id in node.get("source_anchor_ids") or node.get("anchor_ids") or []:
                node_by_anchor.setdefault(str(anchor_id), set()).add(str(node.get("id")))
        text_rows = []
        for chunk in chunks:
            chunk_evidence = sorted({
                evidence_id
                for anchor_id in chunk.anchor_ids or []
                for evidence_id in evidence_by_anchor.get(str(anchor_id), set())
            })
            chunk_citations = sorted({
                citation.citation_id
                for evidence_id in chunk_evidence
                for citation in citations_by_evidence.get(evidence_id, [])
            })
            if not chunk_citations:
                continue
            node_keys = sorted({
                node_key
                for anchor_id in chunk.anchor_ids or []
                for node_key in node_by_anchor.get(str(anchor_id), set())
            })
            text_rows.append({
                "id": chunk.chunk_id,
                "text": chunk.text,
                "retrieval_chunk_id": chunk.chunk_id,
                "text_unit_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "content_hash": chunk.content_hash,
                "node_key": node_keys[0] if len(node_keys) == 1 else "",
                "node_keys": node_keys,
                "evidence_ids": chunk_evidence,
                "citation_ids": chunk_citations,
                "student_visible": True,
            })
        identity_ids = [int(node.get("identity_id") or 0) for node in snapshot.nodes or []]
        identities = {
            int(node.id): node for node in session.exec(select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == bundle.course_id,
                CourseKnowledgeNode.id.in_(identity_ids),
            )).all()
        } if identity_ids else {}
        entity_rows = []
        for node in snapshot.nodes or []:
            identity_id = int(node.get("identity_id") or 0)
            node_evidence = list(node.get("evidence_ids") or [])
            node_citations = list(node.get("citation_ids") or [])
            if not node_evidence or not node_citations:
                raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
            title = str(node.get("title") or node.get("label") or "")
            description = str(node.get("description") or "")
            entity_rows.append({
                "id": str(node["id"]),
                "node_key": str(node["id"]),
                "knowledge_node_id": identity_id,
                "title": title,
                "entity_type": str(node.get("type") or node.get("kind") or "concept"),
                "description": description,
                "text": f"{title}\n{description}".strip(),
                "text_unit_ids": list(node.get("source_text_unit_ids") or []),
                "evidence_ids": node_evidence,
                "citation_ids": node_citations,
                "content_hash": _hash_payload(node),
            })
            if identity_id not in identities:
                raise KnowledgeBundleError("IDENTITY_MAPPING_INVALID")
        evidence_rows = []
        for evidence in evidence_records:
            evidence_citations = citations_by_evidence.get(evidence.evidence_id, [])
            if not evidence_citations:
                raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
            node = identities.get(int(evidence.node_id or 0))
            primary_citation = sorted(
                evidence_citations, key=lambda item: item.citation_id
            )[0]
            evidence_rows.append({
                "id": evidence.evidence_id,
                "evidence_id": evidence.evidence_id,
                "citation_id": primary_citation.citation_id,
                "node_key": node.node_key if node else "",
                "knowledge_node_id": int(evidence.node_id or 0),
                "retrieval_chunk_id": next((
                    chunk.chunk_id for chunk in chunks
                    if set(chunk.anchor_ids or []) & set(evidence.source_anchor_ids or [])
                ), ""),
                "document_id": evidence.document_id or "",
                "page_number": evidence.page_number or 0,
                "text": evidence.text_snippet,
                "content_hash": evidence.content_hash,
                "evidence_ids": [evidence.evidence_id],
                "citation_ids": sorted(item.citation_id for item in evidence_citations),
            })
        if len({row["evidence_id"] for row in evidence_rows}) != len(evidence_records):
            raise KnowledgeBundleError("EVIDENCE_CLOSURE_FAILED")
        return {"text_units": text_rows, "entities": entity_rows, "evidence": evidence_rows}

    @staticmethod
    def _require_run(
        session: Session, run_id: str, course_id: int | None = None
    ) -> GraphRagRun:
        statement = select(GraphRagRun).where(GraphRagRun.run_id == run_id)
        if course_id is not None:
            statement = statement.where(GraphRagRun.course_id == course_id)
        run = session.exec(statement).first()
        if run is None:
            raise KnowledgeBundleError("GRAPHRAG_RUN_NOT_FOUND")
        return run

    @staticmethod
    def _require_bundle(
        session: Session, course_id: int, bundle_id: str
    ) -> CourseKnowledgeBundle:
        bundle = session.exec(select(CourseKnowledgeBundle).where(
            CourseKnowledgeBundle.course_id == course_id,
            CourseKnowledgeBundle.bundle_id == bundle_id,
        )).first()
        if bundle is None:
            raise KnowledgeBundleError("KNOWLEDGE_BUNDLE_NOT_FOUND")
        return bundle

    @staticmethod
    def _course_input_hash(
        session: Session,
        course_id: int,
        *,
        only_active: bool = False,
        chunk_ids: set[str] | None = None,
    ) -> str:
        statement = select(RetrievalChunk).where(RetrievalChunk.course_id == course_id)
        if only_active:
            statement = statement.where(RetrievalChunk.status == "active")
        if chunk_ids is not None:
            statement = statement.where(RetrievalChunk.chunk_id.in_(sorted(chunk_ids)))
        chunks = sorted(session.exec(statement).all(), key=lambda item: item.chunk_id)
        if not chunks:
            raise KnowledgeBundleError("GRAPH_INPUT_EMPTY")
        return _hash_payload([
            {"chunk_id": item.chunk_id, "content_hash": item.content_hash, "status": item.status}
            for item in chunks
        ])

    @staticmethod
    def _resolve_source_chunk_ids(
        session: Session,
        *,
        course_id: int,
        source_scope: dict[str, Any],
    ) -> set[str] | None:
        document_ids = {
            str(item) for item in source_scope.get("document_ids") or [] if item
        }
        raw_ranges = source_scope.get("page_ranges") or []
        page_ranges: list[tuple[str | None, int, int]] = []
        for item in raw_ranges:
            if isinstance(item, dict):
                document_id = str(item.get("document_id") or "") or None
                start = item.get("start", item.get("page_start"))
                end = item.get("end", item.get("page_end", start))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                document_id = None
                start, end = item[0], item[1]
            else:
                continue
            try:
                start_page, end_page = int(start), int(end)
            except (TypeError, ValueError):
                continue
            page_ranges.append((
                document_id,
                min(start_page, end_page),
                max(start_page, end_page),
            ))
        if not document_ids and not page_ranges:
            return None

        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == course_id,
        )).all())
        anchor_ids = {
            str(anchor_id)
            for chunk in chunks
            for anchor_id in chunk.anchor_ids or []
        }
        anchors = list(session.exec(select(EvidenceAnchor).where(
            EvidenceAnchor.course_id == course_id,
            EvidenceAnchor.anchor_id.in_(sorted(anchor_ids)),
        )).all()) if anchor_ids else []
        anchors_by_id = {anchor.anchor_id: anchor for anchor in anchors}

        selected: set[str] = set()
        for chunk in chunks:
            if document_ids and chunk.document_id not in document_ids:
                continue
            if page_ranges:
                chunk_anchors = [
                    anchors_by_id[str(anchor_id)]
                    for anchor_id in chunk.anchor_ids or []
                    if str(anchor_id) in anchors_by_id
                ]
                if not any(
                    anchor.page_or_slide is not None
                    and (document_id is None or anchor.document_id == document_id)
                    and start <= int(anchor.page_or_slide) <= end
                    for document_id, start, end in page_ranges
                    for anchor in chunk_anchors
                ):
                    continue
            selected.add(chunk.chunk_id)
        if not selected:
            raise KnowledgeBundleError("GRAPH_INPUT_EMPTY")
        return selected

    @staticmethod
    def _effective_config_hash() -> str:
        return _hash_payload({
            "prompt_policy": settings.GRAPHRAG_PROMPT_POLICY,
            "completion_provider": settings.GRAPHRAG_COMPLETION_PROVIDER,
            "completion_model": settings.GRAPHRAG_COMPLETION_MODEL,
            "embedding_provider": settings.GRAPHRAG_EMBEDDING_PROVIDER,
            "embedding_model": settings.GRAPHRAG_EMBEDDING_MODEL,
            "embedding_dimension": settings.GRAPHRAG_EMBEDDING_DIMENSION,
            "embedding_local_path": settings.GRAPHRAG_EMBEDDING_LOCAL_PATH,
            "max_gleanings": settings.GRAPHRAG_MAX_GLEANINGS,
        })

    @staticmethod
    def _run_root(course_id: int, run_id: str) -> Path:
        root = Path(settings.GRAPHRAG_STORAGE_ROOT).resolve()
        target = (root / "courses" / str(course_id) / "runs" / run_id).resolve()
        if root not in target.parents:
            raise KnowledgeBundleError("INVALID_STORAGE_PATH")
        return target


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


knowledge_bundle_service = KnowledgeBundleService()
