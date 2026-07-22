"""Post-run mapping failure examples; this tool may read mapping qrels only after a run freezes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import write_json, write_jsonl  # noqa: E402
from src.fixture_io import load_jsonl, manifest_sha256  # noqa: E402


def build_mapping_failures(fixture: Path, run_path: Path) -> tuple[list[dict], dict]:
    rows = load_jsonl(run_path)
    header, results = rows[0], rows[1:]
    if header.get("fixture_manifest_sha256") != manifest_sha256(fixture):
        raise ValueError("run fixture manifest hash mismatch")
    qrels: dict[str, dict[str, dict]] = {}
    for row in load_jsonl(fixture / "mapping_qrels.jsonl"):
        qrels.setdefault(row["research_knowledge_point_id"], {})[row["research_slide_id"]] = row
    examples = []
    for result in sorted(results, key=lambda row: row["research_knowledge_point_id"]):
        kp_id = result["research_knowledge_point_id"]
        gold = qrels[kp_id]
        primary = {slide_id for slide_id, row in gold.items() if row["relevance"] == 2}
        useful = {slide_id for slide_id, row in gold.items() if row["relevance"] >= 1}
        ranked = result.get("slides", [])
        ids = [row["research_slide_id"] for row in ranked]
        failure_types = []
        if result["status"] == "abstain":
            failure_types.append("mapping_abstain")
        else:
            if not ids[:1] or ids[0] not in primary:
                failure_types.append("mapping_wrong_page")
            if not set(ids[:3]) & primary:
                failure_types.append("primary_miss_at_3")
            if not set(ids[:3]) & useful:
                failure_types.append("useful_miss_at_3")
        if failure_types:
            examples.append({
                "run_id": header.get("run_id"),
                "research_knowledge_point_id": kp_id,
                "failure_types": failure_types,
                "expected_primary_slide_ids": sorted(primary),
                "expected_useful_slide_ids": sorted(useful),
                "returned": ranked,
                "diagnosis": "feature_weight_or_slide_text_mismatch",
                "gold_issue_suspected": False,
            })
    return examples, {"run_id": header.get("run_id"), "failure_count": len(examples)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    examples, summary = build_mapping_failures(args.fixture, args.run)
    summary["failure_examples_path"] = str(args.output)
    write_jsonl(args.output, examples)
    write_json(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
