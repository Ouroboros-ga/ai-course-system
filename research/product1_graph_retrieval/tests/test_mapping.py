from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.evaluation import evaluate_mapping
from src.fixture_io import load_jsonl
from src.mapping import KnowledgePointSlideMapper
from tools.report_mapping_failures import build_mapping_failures
from tools.run_mapping import run_mapping


MICRO = RESEARCH_ROOT / "datasets" / "micro_contract_v1"
SILVER = RESEARCH_ROOT / "datasets" / "reviewed_silver_v0_2"
CONFIG = RESEARCH_ROOT / "configs" / "m0_mapping_reviewed_silver_v0_2.json"
TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"mapping_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class MappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_mapping_is_course_closed_explainable_and_reuses_slide_evidence(self) -> None:
        slides = load_jsonl(SILVER / "slides.jsonl")
        evidence = load_jsonl(SILVER / "evidence.jsonl")
        kp = load_jsonl(SILVER / "knowledge_points.jsonl")[0]
        mapper = KnowledgePointSlideMapper(slides, evidence, k1=1.2, b=0.75, title_weight=.45, bm25_weight=.4, chapter_weight=.15)
        result = mapper.map(kp, top_k=3)
        self.assertEqual(result["status"], "ok")
        for slide in result["slides"]:
            self.assertEqual(slide["course_id"], kp["course_id"])
            self.assertEqual(set(slide["feature_trace"]), {"title_match", "normalized_bm25", "chapter_proximity", "raw_bm25", "chapter_distance_basis", "chapter_distance", "chapter_distance_missing"})
            self.assertTrue(slide["research_evidence_ids"])
            self.assertEqual({row["research_evidence_id"] for row in slide["citations"]}, set(slide["research_evidence_ids"]))

    def test_micro_run_and_post_run_failure_report(self) -> None:
        with test_directory() as temp:
            run = temp / "mapping.jsonl"
            run_mapping(MICRO, CONFIG, split="validation", output=run)
            report = evaluate_mapping(MICRO, run, contract_test_only=True)
            self.assertEqual(report["task"], "mapping")
            examples, summary = build_mapping_failures(MICRO, run)
            self.assertEqual(summary["run_id"], "m0_title_bm25_chapter_reviewed_silver_v0_2")
            self.assertIsInstance(examples, list)


if __name__ == "__main__":
    unittest.main()
