"""Key-free JSON handoff entry point for an optional isolated GraphRAG venv."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.platform.knowledge.document_ir_exporter import (
    load_graph_rag_input_manifest,
)
from app.platform.knowledge.graphrag_runner import GraphRagRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--policy-context", required=False)
    args = parser.parse_args()
    result_path = Path(args.result).resolve()
    try:
        manifest = load_graph_rag_input_manifest(args.manifest)
        policy_context = {}
        if args.policy_context:
            policy_context = json.loads(
                Path(args.policy_context).read_text(encoding="utf-8")
            )
        artifacts = GraphRagRunner().run(
            manifest=manifest,
            artifact_root=Path(args.artifact_root).resolve(),
            policy_context=policy_context,
        )
        payload = {
            **asdict(artifacts),
            "input_content_hash": manifest.input_content_hash,
            "entities": list(artifacts.entities),
            "relationships": list(artifacts.relationships),
            "text_units": list(artifacts.text_units),
            "documents": list(artifacts.documents),
            "warnings": list(artifacts.warnings),
        }
        return_code = 0
    except Exception as exc:
        payload = {"error": str(exc)[:1000]}
        return_code = 1
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
