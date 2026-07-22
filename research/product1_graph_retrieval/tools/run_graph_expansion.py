"""Run constrained R3 graph expansion from a frozen R2 run without gold access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import canonical_json_bytes, sha256_bytes, write_jsonl  # noqa: E402
from src.fixture_io import load_json, load_jsonl, manifest_sha256  # noqa: E402
from src.graph_expansion import GRAPH_EXPANSION_VERSION, OneHopStructuralExpander  # noqa: E402


def run_graph_expansion(fixture: Path, config_path: Path, *, r2_run: Path, graph_dir: Path, output: Path) -> dict:
    config, manifest, snapshot = load_json(config_path), load_json(fixture / "manifest.json"), load_json(graph_dir / "snapshot.json")
    if snapshot.get("fixture_manifest_sha256") != manifest_sha256(fixture):
        raise ValueError("graph snapshot fixture mismatch")
    if snapshot.get("snapshot_kind") != "deterministic_research_graph_not_production_graphrag":
        raise ValueError("unsupported graph snapshot")
    rows = load_jsonl(r2_run)
    header, baseline_rows = rows[0], rows[1:]
    if header.get("task") != "retrieval" or header.get("fixture_manifest_sha256") != manifest_sha256(fixture):
        raise ValueError("invalid R3 source run")
    if header.get("gold_access_attestation", {}).get("qrels_accessed_during_run") is not False:
        raise ValueError("R3 source accessed qrels")
    queries = {row["research_query_id"]: row for row in load_jsonl(fixture / "queries.jsonl")}
    baselines = {row["research_query_id"]: row for row in baseline_rows}
    if not set(baselines) <= set(queries):
        raise ValueError("R3 source contains unknown query")
    expander = OneHopStructuralExpander(
        corpus=load_jsonl(fixture / "corpus.jsonl"),
        evidence=load_jsonl(fixture / "evidence.jsonl"),
        nodes=load_jsonl(graph_dir / "nodes.jsonl"),
        edges=load_jsonl(graph_dir / "edges.jsonl"),
    )
    graph = config["graph_expansion"]
    results = [
        expander.expand(queries[query_id], baselines[query_id], **graph)
        for query_id in sorted(baselines)
    ]
    out_header = {
        "record_type": "run_header",
        "run_schema_version": "product1-graph-retrieval-offline-run/1.0",
        "task": "retrieval",
        "run_id": config["run_name"],
        "implementation": {"graph_expansion_version": GRAPH_EXPANSION_VERSION, "mode": "constrained_one_hop_structural_not_graphrag"},
        "fixture_manifest_sha256": manifest_sha256(fixture),
        "configuration_sha256": sha256_bytes(canonical_json_bytes(config)),
        "split": header["split"],
        "source_run_headers": {"r2_configuration_sha256": header["configuration_sha256"], "graph_content_sha256": snapshot["graph_content_sha256"]},
        "gold_access_attestation": {"qrels_accessed_during_run": False, "query_labels_accessed_during_run": False},
    }
    write_jsonl(output, [out_header, *results])
    return {"run_path": str(output), "query_count": len(results)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--r2-run", type=Path, required=True)
    parser.add_argument("--graph-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_graph_expansion(args.fixture, args.config, r2_run=args.r2_run, graph_dir=args.graph_dir, output=args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
