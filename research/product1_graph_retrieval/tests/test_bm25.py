from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.bm25 import BM25Index, CourseBM25Retriever
from src.canonical import write_jsonl
from src.evaluation import evaluate_retrieval
from src.fixture_io import load_json, load_jsonl
from src.tokenizer import tokenize, unique_query_terms
from tools.report_retrieval_failures import build_failure_examples
from tools.run_bm25 import run_bm25
from tools.verify_run_reproducibility import verify


MICRO = RESEARCH_ROOT / "datasets" / "micro_contract_v1"
SILVER = RESEARCH_ROOT / "datasets" / "reviewed_silver_v0_2"
CONFIG = RESEARCH_ROOT / "configs" / "r0_bm25_reviewed_silver_v0_2.json"
TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"bm25_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class BM25Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_mixed_script_tokenization_is_frozen_and_query_terms_are_unique(self) -> None:
        self.assertEqual(tokenize("电机 ABC-12 电机"), ["电", "机", "电机", "abc-12", "电", "机", "电机"])
        self.assertEqual(unique_query_terms("电机 电机 abc-12 abc-12"), ["电", "机", "电机", "abc-12"])

    def test_index_rejects_mixed_courses_and_tie_breaks_by_chunk_id(self) -> None:
        chunks = [
            {"research_chunk_id": "rch_b", "course_id": "C1", "text": "电机"},
            {"research_chunk_id": "rch_a", "course_id": "C1", "text": "电机"},
        ]
        index = BM25Index("C1", chunks, k1=1.2, b=0.75)
        self.assertEqual([row.chunk["research_chunk_id"] for row in index.search("电机", top_k=2)], ["rch_a", "rch_b"])
        with self.assertRaises(ValueError):
            BM25Index("C1", [*chunks, {"research_chunk_id": "rch_c", "course_id": "C2", "text": "电机"}], k1=1.2, b=0.75)

    def test_retriever_is_course_scoped_and_returns_closed_citations(self) -> None:
        corpus = [
            {"research_chunk_id": "rch_a", "course_id": "C1", "text": "电机原理", "research_evidence_ids": ["rev_a"], "page_or_slide": 1, "block_id": "b1"},
            {"research_chunk_id": "rch_b", "course_id": "C2", "text": "电机原理", "research_evidence_ids": ["rev_b"], "page_or_slide": 1, "block_id": "b2"},
        ]
        evidence = [
            {"research_evidence_id": "rev_a", "course_id": "C1", "status": "active", "citation_key": "cite_a", "artifact_id": "a", "document_id": "d", "unit_id": "u", "block_id": "b1", "page_or_slide": 1},
            {"research_evidence_id": "rev_b", "course_id": "C2", "status": "active", "citation_key": "cite_b", "artifact_id": "a", "document_id": "d", "unit_id": "u", "block_id": "b2", "page_or_slide": 1},
        ]
        retriever = CourseBM25Retriever(corpus, evidence, k1=1.2, b=0.75)
        result = retriever.retrieve({"research_query_id": "rq_1", "course_id": "C1", "text": "电机"}, top_k=5)
        self.assertEqual(result["hits"][0]["course_id"], "C1")
        self.assertEqual(result["hits"][0]["citations"][0]["research_evidence_id"], "rev_a")
        self.assertEqual(result["hits"][0]["citations"][0]["citation_key"], "cite_a")
        self.assertEqual(retriever.retrieve({"research_query_id": "rq_2", "course_id": "C1", "text": "不存在"}, top_k=5)["status"], "abstain")

    def test_runner_uses_public_inputs_only_and_silver_evaluation_is_research_only(self) -> None:
        with test_directory() as temp:
            run = temp / "micro.jsonl"
            outcome = run_bm25(MICRO, CONFIG, split="validation", output=run)
            self.assertEqual(outcome["query_count"], len(load_json(MICRO / "splits.json")["validation_query_ids"]))
            rows = load_jsonl(run)
            self.assertFalse(rows[0]["gold_access_attestation"]["qrels_accessed_during_run"])
            self.assertFalse(rows[0]["gold_access_attestation"]["query_labels_accessed_during_run"])
            silver_run = temp / "silver.jsonl"
            run_bm25(SILVER, CONFIG, split="validation", output=silver_run)
            report = evaluate_retrieval(SILVER, silver_run)
            self.assertEqual(report["eligibility"], "reviewed_silver_offline_research_only")

    def test_failure_examples_are_generated_only_after_run(self) -> None:
        with test_directory() as temp:
            run = temp / "run.jsonl"
            run_bm25(MICRO, CONFIG, split="validation", output=run)
            examples, summary = build_failure_examples(MICRO, run)
            self.assertEqual(summary["run_id"], "r0_bm25_reviewed_silver_v0_2")
            self.assertIsInstance(examples, list)

    def test_ranked_records_are_byte_reproducible(self) -> None:
        with test_directory() as temp:
            left, right = temp / "left.jsonl", temp / "right.jsonl"
            run_bm25(MICRO, CONFIG, split="validation", output=left)
            run_bm25(MICRO, CONFIG, split="validation", output=right)
            self.assertEqual(verify(left, right)["status"], "byte_reproducible_rankings")


if __name__ == "__main__":
    unittest.main()
