"""Fuse frozen BM25/Dense runs without access to labels or qrels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import canonical_json_bytes, sha256_bytes, write_jsonl  # noqa: E402
from src.fixture_io import load_json, load_jsonl, manifest_sha256  # noqa: E402
from src.rrf import RRF_VERSION, fuse  # noqa: E402


def run_rrf(fixture: Path, config_path: Path, *, bm25_run: Path, dense_run: Path, output: Path) -> dict:
    config, manifest = load_json(config_path), load_json(fixture / "manifest.json")
    bm_rows, dense_rows = load_jsonl(bm25_run), load_jsonl(dense_run)
    bm_header, dense_header = bm_rows[0], dense_rows[0]
    for header in (bm_header, dense_header):
        if header.get("task") != "retrieval" or header.get("fixture_manifest_sha256") != manifest_sha256(fixture):
            raise ValueError("invalid RRF source run")
        if header.get("gold_access_attestation", {}).get("qrels_accessed_during_run") is not False:
            raise ValueError("RRF source accessed qrels")
    if bm_header.get("split") != dense_header.get("split"):
        raise ValueError("RRF source split mismatch")
    queries = {row["research_query_id"]: row for row in load_jsonl(fixture / "queries.jsonl")}
    bm_index, dense_index = ({row["research_query_id"]: row for row in rows[1:]} for rows in (bm_rows, dense_rows))
    if set(bm_index) != set(dense_index):
        raise ValueError("RRF source query sets differ")
    rrf = config["rrf"]
    rows = [fuse(query_id, queries[query_id]["course_id"], bm_index[query_id], dense_index[query_id], k=rrf["k"], sparse_weight=rrf["bm25_weight"], dense_weight=rrf["dense_weight"], top_k=config["candidate_k"]) for query_id in sorted(bm_index)]
    header = {"record_type": "run_header", "run_schema_version": "product1-graph-retrieval-offline-run/1.0", "task": "retrieval", "run_id": config["run_name"], "implementation": {"rrf_version": RRF_VERSION}, "fixture_manifest_sha256": manifest_sha256(fixture), "configuration_sha256": sha256_bytes(canonical_json_bytes(config)), "split": bm_header["split"], "source_run_headers": {"bm25_configuration_sha256": bm_header["configuration_sha256"], "dense_configuration_sha256": dense_header["configuration_sha256"]}, "gold_access_attestation": {"qrels_accessed_during_run": False, "query_labels_accessed_during_run": False}}
    write_jsonl(output, [header, *rows])
    return {"run_path": str(output), "query_count": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path); parser.add_argument("--config", type=Path, required=True); parser.add_argument("--bm25-run", type=Path, required=True); parser.add_argument("--dense-run", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(run_rrf(args.fixture, args.config, bm25_run=args.bm25_run, dense_run=args.dense_run, output=args.output), ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
