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

from src.fixture_io import FixtureValidationError, load_jsonl, validate_fixture
from src.micro_fixture import generate_micro_fixture

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


class FixtureValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_committed_micro_fixture_is_valid_and_contract_only(self) -> None:
        audit = validate_fixture(FIXTURE)
        self.assertTrue(audit["valid"])
        self.assertEqual(audit["counts"]["courses"], 2)
        self.assertEqual(audit["counts"]["chunks"], 20)
        self.assertEqual(audit["counts"]["queries"], 18)
        self.assertFalse(audit["gold"]["eligible_for_algorithm_comparison"])

    def test_generation_is_byte_reproducible(self) -> None:
        with test_directory() as first, test_directory() as second:
            generate_micro_fixture(first)
            generate_micro_fixture(second)
            first_files = {p.name: p.read_bytes() for p in first.iterdir() if p.is_file()}
            second_files = {p.name: p.read_bytes() for p in second.iterdir() if p.is_file()}
            self.assertEqual(first_files, second_files)

    def test_hash_tampering_fails_closed(self) -> None:
        with test_directory() as temp:
            target = temp / "fixture"
            shutil.copytree(FIXTURE, target)
            with (target / "queries.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            with self.assertRaises(FixtureValidationError) as raised:
                validate_fixture(target)
            self.assertIn("file_hash", {issue.code for issue in raised.exception.issues})

    def test_queries_do_not_expose_answerability_or_expected_behavior(self) -> None:
        for query in load_jsonl(FIXTURE / "queries.jsonl"):
            self.assertNotIn("answerable", query)
            self.assertNotIn("answerability", query)
            self.assertNotIn("expected_behavior", query)

    def test_research_identity_names_and_markers_are_explicit(self) -> None:
        evidence = load_jsonl(FIXTURE / "evidence.jsonl")
        self.assertTrue(all("research_evidence_id" in row for row in evidence))
        self.assertTrue(all("evidence_id" not in row for row in evidence))
        self.assertTrue(all(row["research_sidecar"] for row in evidence))
        self.assertTrue(all(row["not_a_production_contract_field"] for row in evidence))


if __name__ == "__main__":
    unittest.main()
