"""Build an immutable deterministic research graph from public fixture inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file, write_json, write_jsonl  # noqa: E402
from src.course_graph import GRAPH_SCHEMA_VERSION, build_snapshot, validate_snapshot  # noqa: E402
from src.fixture_io import PUBLIC_INPUT_FILES, load_json, load_jsonl, manifest_sha256  # noqa: E402


def build(fixture: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("graph snapshot output must be empty; snapshots are immutable")
    manifest = load_json(fixture / "manifest.json")
    if set(manifest.get("access_policy", {}).get("index_inputs", [])) != PUBLIC_INPUT_FILES:
        raise ValueError("public fixture partition mismatch")
    names = ("source_blocks.jsonl", "evidence.jsonl", "knowledge_points.jsonl", "slides.jsonl")
    for name in names:
        if manifest["files"].get(name) != f"sha256:{sha256_file(fixture / name)}":
            raise ValueError(f"public input hash mismatch: {name}")
    source_blocks, evidence, knowledge_points, slides = (load_jsonl(fixture / name) for name in names)
    nodes, edges = build_snapshot(source_blocks=source_blocks, evidence=evidence, knowledge_points=knowledge_points, slides=slides)
    audit = validate_snapshot(nodes, edges, {row["research_evidence_id"] for row in evidence if row["status"] == "active"})
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "nodes.jsonl", nodes)
    write_jsonl(output / "edges.jsonl", edges)
    snapshot = {
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "snapshot_kind": "deterministic_research_graph_not_production_graphrag",
        "fixture_manifest_sha256": manifest_sha256(fixture),
        "nodes_sha256": f"sha256:{sha256_file(output / 'nodes.jsonl')}",
        "edges_sha256": f"sha256:{sha256_file(output / 'edges.jsonl')}",
        "graph_content_sha256": sha256_bytes(canonical_json_bytes({"nodes": nodes, "edges": edges})),
        "accepted_predicates": sorted({edge["predicate"] for edge in edges}),
        "forbidden_semantic_predicates": ["PREREQUISITE_OF", "RELATED_TO", "HAS_MISCONCEPTION", "USES", "EXPLAINS"],
        "audit": audit,
    }
    write_json(output / "snapshot.json", snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.fixture, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
