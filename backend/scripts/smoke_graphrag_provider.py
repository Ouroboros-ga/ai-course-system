"""Explicit, billable GraphRAG provider smoke over a bounded course corpus."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from sqlmodel import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.models.database import session_factory
from app.models.document_parse_model import RetrievalChunk
from app.platform.knowledge.document_ir_exporter import CanonicalDocumentIRExporter
from app.platform.knowledge.graphrag_runner import GraphRagRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--max-chunks", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--max-input-tokens", type=int, default=12000)
    parser.add_argument("--max-estimated-cost", type=float, default=1.0)
    parser.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable:
        parser.error("真实 Provider 冒烟会产生费用；必须显式传入 --confirm-billable")
    if not settings.GRAPHRAG_ENABLED:
        parser.error("GRAPHRAG_ENABLED 未启用")
    settings.GRAPHRAG_MAX_INPUT_TOKENS = args.max_input_tokens
    settings.GRAPHRAG_MAX_ESTIMATED_COST = args.max_estimated_cost

    run_id = f"manual_smoke_{uuid.uuid4().hex}"
    root = (
        Path(settings.GRAPHRAG_STORAGE_ROOT).resolve()
        / "courses" / str(args.course_id) / "runs" / run_id
    )
    with session_factory() as session:
        chunks = session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == args.course_id,
        ).order_by(RetrievalChunk.chunk_id).limit(args.max_chunks)).all()
        if not chunks:
            parser.error("课程没有 RetrievalChunk")
        manifest = CanonicalDocumentIRExporter().export(
            session,
            course_id=args.course_id,
            output_dir=root / "input",
            chunk_ids={chunk.chunk_id for chunk in chunks},
        )
    artifacts = GraphRagRunner().run(manifest=manifest, artifact_root=root)
    print(json.dumps({
        "manual_billable_smoke": True,
        "course_id": args.course_id,
        "run_id": run_id,
        "input_chunks": manifest.chunk_count,
        "estimated_input_tokens": artifacts.estimated_input_tokens,
        "estimated_max_cost": artifacts.estimated_max_cost,
        "entities": len(artifacts.entities),
        "relationships": len(artifacts.relationships),
        "output_manifest_uri": artifacts.output_manifest_uri,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
