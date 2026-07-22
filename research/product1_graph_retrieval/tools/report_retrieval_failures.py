"""Produce post-run failure examples. This is the first tool allowed to read qrels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import write_json, write_jsonl  # noqa: E402
from src.fixture_io import load_json, load_jsonl, manifest_sha256  # noqa: E402


def build_failure_examples(fixture: Path, run_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_rows = load_jsonl(run_path)
    header, results = run_rows[0], run_rows[1:]
    if header.get("fixture_manifest_sha256") != manifest_sha256(fixture):
        raise ValueError("run fixture manifest hash mismatch")
    queries = {row["research_query_id"]: row for row in load_jsonl(fixture / "queries.jsonl")}
    labels = {row["research_query_id"]: row for row in load_jsonl(fixture / "retrieval_query_labels.jsonl")}
    qrels: dict[str, dict[str, int]] = {}
    for row in load_jsonl(fixture / "retrieval_qrels.jsonl"):
        qrels.setdefault(row["research_query_id"], {})[row["research_evidence_id"]] = row["relevance"]
    examples: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda row: row["research_query_id"]):
        query_id = result["research_query_id"]
        label = labels[query_id]["answerability"]
        hits = result.get("hits", [])
        returned_ids = [reference for hit in hits for reference in hit.get("research_evidence_ids", [])]
        expected = sorted(reference for reference, grade in qrels.get(query_id, {}).items() if grade >= 1)
        failure_types: list[str] = []
        if label == "answerable":
            if result["status"] == "abstain":
                failure_types.append("false_abstain")
            elif not set(returned_ids[:5]) & set(expected):
                failure_types.append("miss_at_5")
                if set(returned_ids) & set(expected):
                    failure_types.append("late_relevant_hit")
        elif result["status"] != "abstain":
            failure_types.append("false_answer")
        if any(hit.get("course_id") != queries[query_id]["course_id"] for hit in hits):
            failure_types.append("cross_course_contamination")
        if not failure_types:
            continue
        if result["status"] == "abstain":
            diagnosis = "no_positive_lexical_match"
        elif "false_answer" in failure_types:
            diagnosis = "lexical_overlap_on_unanswerable_query"
        else:
            diagnosis = "lexical_mismatch_or_granularity_gap"
        examples.append({
            "run_id": header.get("run_id"),
            "research_query_id": query_id,
            "course_id": queries[query_id]["course_id"],
            "query_stratum": queries[query_id]["query_stratum"],
            "failure_types": failure_types,
            "expected_research_evidence_ids": expected,
            "returned": hits,
            "diagnosis": diagnosis,
            "gold_issue_suspected": False,
        })
    return examples, {"run_id": header.get("run_id"), "failure_count": len(examples), "failure_examples_path": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    examples, summary = build_failure_examples(args.fixture, args.run)
    summary["failure_examples_path"] = str(args.output)
    write_jsonl(args.output, examples)
    write_json(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
