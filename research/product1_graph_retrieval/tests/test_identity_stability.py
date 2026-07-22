from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.chapter_distance import chapter_distance
from src.identities import (
    production_compatible_citation_key,
    research_evidence_id,
)


class IdentityStabilityTests(unittest.TestCase):
    def test_evidence_identity_is_deterministic_and_field_sensitive(self) -> None:
        fields = {
            "course_id": "course_a",
            "artifact_id": "art_a",
            "document_id": "doc_a",
            "unit_id": "unit_a",
            "block_id": "block_a",
            "version_ref": "v1",
            "char_start": 0,
            "char_end": 4,
        }
        first = research_evidence_id(**fields)
        self.assertEqual(first, research_evidence_id(**dict(reversed(list(fields.items())))))
        self.assertNotEqual(first, research_evidence_id(**{**fields, "char_end": 5}))
        self.assertRegex(first, r"^rev_[0-9a-f]{24}$")

    def test_nul_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            research_evidence_id(
                course_id="course\x00a",
                artifact_id="art",
                document_id="doc",
                unit_id="unit",
                block_id="block",
                version_ref="v1",
                char_start=0,
                char_end=1,
            )

    def test_citation_key_matches_frozen_production_formula(self) -> None:
        expected = hashlib.sha256("art|block|0|4".encode("utf-8")).hexdigest()[:12]
        self.assertEqual(
            production_compatible_citation_key(
                artifact_id="art", block_id="block", char_start=0, char_end=4
            ),
            expected,
        )
        self.assertIsNone(
            production_compatible_citation_key(
                artifact_id="art", block_id=None, char_start=None, char_end=None
            )
        )

    def test_chapter_distance_tree_page_and_unknown(self) -> None:
        tree = chapter_distance(["course", "chapter", "a"], ["course", "chapter", "b"])
        self.assertEqual((tree.basis, tree.distance, tree.proximity), ("tree_edges", 2, 1 / 3))
        page = chapter_distance(
            None,
            None,
            left_document_id="doc",
            right_document_id="doc",
            left_page=3,
            right_page=6,
        )
        self.assertEqual((page.basis, page.distance, page.proximity), ("same_document_page_gap", 3, 0.25))
        missing = chapter_distance(None, None, left_document_id="a", right_document_id="b", left_page=1, right_page=1)
        self.assertTrue(missing.missing)
        self.assertEqual(missing.proximity, 0.0)

    def test_cross_course_chapter_paths_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            chapter_distance(["course_a", "chapter"], ["course_b", "chapter"])


if __name__ == "__main__":
    unittest.main()
