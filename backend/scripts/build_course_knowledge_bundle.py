"""Manual course knowledge Bootstrap or GraphRAG draft build.

This script never auto-approves a GraphRAG draft.  Whole-graph approval remains
an authenticated teacher action in the governance UI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.database import session_factory
from app.services.knowledge_bundle_service import knowledge_bundle_service
from app.services.task_service import task_service


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--actor-user-id", type=int, required=True)
    parser.add_argument("--mode", choices=("bootstrap", "graphrag-draft"), required=True)
    parser.add_argument("--reason", default="人工正式重建")
    parser.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable:
        parser.error("真实 Embedding/GraphRAG 构建会产生费用；必须传入 --confirm-billable")

    with session_factory() as session:
        if args.mode == "bootstrap":
            bundle, task = knowledge_bundle_service.bootstrap_existing_snapshot(
                session,
                course_id=args.course_id,
                actor_user_id=args.actor_user_id,
            )
            vector_id = bundle.vector_index_id
            bundle_id = bundle.bundle_id
            task_service.mark_running(
                session, task["task_id"], stage="vectorize_text_units"
            )
        else:
            run, task = knowledge_bundle_service.request_regeneration(
                session,
                course_id=args.course_id,
                actor_user_id=args.actor_user_id,
                reason=args.reason,
            )
            task_service.mark_running(
                session, task["task_id"], stage="export_document_ir"
            )
            run = knowledge_bundle_service.execute_graphrag_run(
                session, run_id=run.run_id
            )
            task_service.mark_succeeded(
                session,
                task["task_id"],
                result_ref=run.run_id,
                result_data=knowledge_bundle_service.serialize_run(run),
            )
            print(json.dumps({
                "course_id": args.course_id,
                "run_id": run.run_id,
                "status": run.status.value,
                "entities": run.entity_count,
                "relationships": run.relationship_count,
                "next_action": "教师登录知识图谱治理页核验并通过整图",
            }, ensure_ascii=False, indent=2))
            return 0

    with session_factory() as session:
        bundle = knowledge_bundle_service.build_vector_index(
            session,
            course_id=args.course_id,
            bundle_id=bundle_id,
            vector_index_id=vector_id,
            actor_user_id=args.actor_user_id,
        )
        task_service.mark_succeeded(
            session,
            task["task_id"],
            result_ref=bundle.bundle_id,
            result_data=knowledge_bundle_service.serialize_bundle(bundle),
        )
        print(json.dumps({
            "course_id": args.course_id,
            "bundle": knowledge_bundle_service.serialize_bundle(bundle),
            "task": task,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
