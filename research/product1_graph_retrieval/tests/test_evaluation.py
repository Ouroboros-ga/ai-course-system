from __future__ import annotations

import copy
import shutil
import sys
import unittest
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import write_jsonl
from src.evaluation import evaluate_mapping, evaluate_retrieval
from src.fixture_io import load_json, load_jsonl, manifest_sha256

FIXTURE = RESEARCH_ROOT / "datasets" / "micro_contract_v1"
TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def header(task: str, split: str) -> dict:
    return {
        "record_type": "run_header",
        "run_schema_version": "product1-graph-retrieval-offline-run/1.0",
        "task": task,
        "fixture_manifest_sha256": manifest_sha256(FIXTURE),
        "split": split,
        "configuration_sha256": "0" * 64,
        "gold_access_attestation": {
            "qrels_accessed_during_run": False,
            "query_labels_accessed_during_run": False,
        },
        "contract_test_oracle": True,
    }


def retrieval_oracle_rows(split: str) -> list[dict]:
    splits = load_json(FIXTURE / "splits.json")
    target_ids = splits[f"{split}_query_ids"]
    labels = {row["research_query_id"]: row for row in load_jsonl(FIXTURE / "retrieval_query_labels.jsonl")}
    qrels = defaultdict(list)
    for row in load_jsonl(FIXTURE / "retrieval_qrels.jsonl"):
        if row["relevance"] >= 1:
            qrels[row["research_query_id"]].append(row)
    chunks_by_evidence = {}
    for chunk in load_jsonl(FIXTURE / "corpus.jsonl"):
        for evidence_id in chunk["research_evidence_ids"]:
            chunks_by_evidence[evidence_id] = chunk
    evidence = {row["research_evidence_id"]: row for row in load_jsonl(FIXTURE / "evidence.jsonl")}
    rows = [header("retrieval", split)]
    for query_id in sorted(target_ids):
        if labels[query_id]["answerability"] != "answerable":
            rows.append(
                {
                    "research_query_id": query_id,
                    "status": "abstain",
                    "abstain_reason": labels[query_id]["answerability"],
                    "hits": [],
                }
            )
            continue
        hits = []
        ordered = sorted(qrels[query_id], key=lambda row: (-row["relevance"], row["research_evidence_id"]))
        for rank, qrel in enumerate(ordered, 1):
            evidence_id = qrel["research_evidence_id"]
            chunk = chunks_by_evidence[evidence_id]
            hits.append(
                {
                    "rank": rank,
                    "research_chunk_id": chunk["research_chunk_id"],
                    "course_id": chunk["course_id"],
                    "research_evidence_ids": [evidence_id],
                    "citations": [
                        {
                            "research_evidence_id": evidence_id,
                            "citation_key": evidence[evidence_id]["citation_key"],
                        }
                    ],
                }
            )
        rows.append({"research_query_id": query_id, "status": "ok", "hits": hits})
    return rows


def mapping_oracle_rows(split: str) -> list[dict]:
    splits = load_json(FIXTURE / "splits.json")
    target_ids = splits[f"{split}_knowledge_point_ids"]
    qrels = defaultdict(list)
    for row in load_jsonl(FIXTURE / "mapping_qrels.jsonl"):
        if row["relevance"] >= 1:
            qrels[row["research_knowledge_point_id"]].append(row)
    rows = [header("mapping", split)]
    for kp_id in sorted(target_ids):
        ranked = []
        ordered = sorted(qrels[kp_id], key=lambda row: (-row["relevance"], row["research_slide_id"]))
        for rank, qrel in enumerate(ordered, 1):
            ranked.append(
                {
                    "rank": rank,
                    "research_slide_id": qrel["research_slide_id"],
                    "research_evidence_ids": qrel["research_evidence_ids"],
                }
            )
        rows.append({"research_knowledge_point_id": kp_id, "status": "ok", "slides": ranked})
    return rows


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_retrieval_contract_oracle_exercises_all_metrics(self) -> None:
        with test_directory() as temp:
            run = temp / "retrieval.jsonl"
            write_jsonl(run, retrieval_oracle_rows("validation"))
            report = evaluate_retrieval(FIXTURE, run, contract_test_only=True)
        aggregate = report["aggregate"]
        self.assertEqual(report["eligibility"], "contract_only_not_algorithm_comparison")
        self.assertEqual(aggregate["mrr"], 1.0)
        self.assertEqual(aggregate["recall@10"], 1.0)
        self.assertEqual(aggregate["cross_course_contamination_rate"], 0.0)
        self.assertEqual(aggregate["evidence_completeness_rate"], 1.0)
        self.assertEqual(aggregate["citation_key_validity_rate"], 1.0)
        self.assertEqual(aggregate["correct_abstain_rate"], 1.0)

    def test_micro_oracle_cannot_be_reported_as_algorithm_comparison(self) -> None:
        with test_directory() as temp:
            run = temp / "retrieval.jsonl"
            write_jsonl(run, retrieval_oracle_rows("validation"))
            with self.assertRaises(ValueError):
                evaluate_retrieval(FIXTURE, run)

    def test_run_with_gold_access_is_ineligible(self) -> None:
        rows = retrieval_oracle_rows("validation")
        rows[0] = copy.deepcopy(rows[0])
        rows[0]["gold_access_attestation"]["qrels_accessed_during_run"] = True
        with test_directory() as temp:
            run = temp / "leaked.jsonl"
            write_jsonl(run, rows)
            with self.assertRaises(ValueError):
                evaluate_retrieval(FIXTURE, run, contract_test_only=True)

    def test_mapping_contract_oracle_supports_multi_page_gold(self) -> None:
        with test_directory() as temp:
            run = temp / "mapping.jsonl"
            write_jsonl(run, mapping_oracle_rows("validation"))
            report = evaluate_mapping(FIXTURE, run, contract_test_only=True)
        self.assertEqual(report["aggregate"]["top1_primary_accuracy"], 1.0)
        self.assertEqual(report["aggregate"]["top3_primary_accuracy"], 1.0)
        self.assertEqual(report["aggregate"]["top3_useful_coverage"], 1.0)
        self.assertEqual(report["aggregate"]["mapping_mrr"], 1.0)
        self.assertEqual(report["aggregate"]["evidence_binding_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
