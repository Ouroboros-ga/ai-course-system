from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.course_graph import ALLOWED_PREDICATES, build_snapshot, validate_snapshot
from src.fixture_io import load_jsonl
from tools.build_course_graph import build


FIXTURE = RESEARCH_ROOT / "datasets" / "reviewed_silver_v0_2"
TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"graph_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class CourseGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_graph_contains_only_course_closed_structural_edges(self) -> None:
        blocks = load_jsonl(FIXTURE / "source_blocks.jsonl")
        evidence = load_jsonl(FIXTURE / "evidence.jsonl")
        knowledge_points = load_jsonl(FIXTURE / "knowledge_points.jsonl")
        slides = load_jsonl(FIXTURE / "slides.jsonl")
        nodes, edges = build_snapshot(source_blocks=blocks, evidence=evidence, knowledge_points=knowledge_points, slides=slides)
        audit = validate_snapshot(nodes, edges, {row["research_evidence_id"] for row in evidence if row["status"] == "active"})
        self.assertTrue(audit["valid"])
        self.assertTrue({"CONTAINS", "GROUNDED_BY", "MAPPED_TO", "NEXT"} <= {row["predicate"] for row in edges})
        self.assertTrue(set(row["predicate"] for row in edges) <= ALLOWED_PREDICATES)
        self.assertFalse({"PREREQUISITE_OF", "RELATED_TO", "HAS_MISCONCEPTION", "USES", "EXPLAINS"} & {row["predicate"] for row in edges})
        node_by_id = {row["node_id"]: row for row in nodes}
        self.assertTrue(all(node_by_id[row["subject_node_id"]]["course_id"] == node_by_id[row["object_node_id"]]["course_id"] for row in edges))

    def test_snapshot_tool_is_immutable_and_hashes_output(self) -> None:
        with test_directory() as temp:
            snapshot = build(FIXTURE, temp)
            self.assertEqual(snapshot["snapshot_kind"], "deterministic_research_graph_not_production_graphrag")
            self.assertTrue((temp / "nodes.jsonl").is_file())
            self.assertTrue((temp / "edges.jsonl").is_file())
            with self.assertRaises(ValueError):
                build(FIXTURE, temp)


if __name__ == "__main__":
    unittest.main()
