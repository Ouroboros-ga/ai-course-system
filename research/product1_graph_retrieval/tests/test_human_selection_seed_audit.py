from __future__ import annotations

import csv
import io
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from tools.human_selection_seed_audit import FINAL_QUERY_STRATA, audit_seed_exports


TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"selection_audit_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def write_csv(path: Path, rows: list[dict[str, object]], *, encoding: str) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode(encoding))


def seed_exports(root: Path, *, reviewed: bool, query_count: int) -> None:
    strata = sorted(FINAL_QUERY_STRATA)
    queries = []
    for index in range(query_count):
        queries.append({
            "seed_id": f"Q{index:03d}",
            "course_id": f"C{index % 4}",
            "knowledge_point_id": f"KP{index % 40:03d}",
            "knowledge_point": f"Knowledge {index % 40}",
            "ppt_page_range": str(index % 10 + 1),
            "query_text": f"Query {index}",
            "query_variant": "human_seed",
            "query_stratum": strata[index % len(strata)],
            "review_status": "已复核" if reviewed else "待复核",
            "expected_answerability": "answerable",
            "gold_answer_hint": "seed only; strip before import",
        })
    knowledge_points = [{
        "knowledge_point_id": f"KP{index:03d}",
        "course_id": f"C{index % 4}",
        "knowledge_point": f"Knowledge {index}",
        "ppt_page_start": str(index % 10 + 1),
        "ppt_page_end": str(index % 10 + 1),
    } for index in range(40)]
    pages = [{"course_id": f"C{course}", "ppt_page": str(page),
        "source_file": f"course_{course}.pptx"}
        for course in range(4) for page in range(1, 11)]
    write_csv(root / "queries.csv", queries, encoding="gb18030")
    write_csv(root / "knowledge_points.csv", knowledge_points, encoding="utf-8-sig")
    write_csv(root / "pages.csv", pages, encoding="utf-8-sig")


class HumanSelectionSeedAuditTests(unittest.TestCase):
    def test_pending_oversized_seed_pool_is_blocked_and_gold_like_columns_warn(self) -> None:
        with test_directory() as root:
            seed_exports(root, reviewed=False, query_count=101)
            result = audit_seed_exports(root)
            self.assertFalse(result["ready_for_selection_import"])
            self.assertIn("queries_not_all_human_reviewed", result["reasons"])
            self.assertIn("final_query_count_must_be_60_to_100", result["reasons"])
            self.assertIn("seed_only_gold_like_columns_must_be_removed_before_selection", result["warnings"])
            query_export = next(row for row in result["exports"] if row["role"] == "query_seed_export")
            self.assertEqual(query_export["encoding"], "gb18030")

    def test_reviewed_size_bounded_all_strata_seed_pool_is_importable(self) -> None:
        with test_directory() as root:
            seed_exports(root, reviewed=True, query_count=70)
            result = audit_seed_exports(root)
            self.assertTrue(result["ready_for_selection_import"])
            self.assertEqual(result["counts"], {
                "queries": 70, "knowledge_points": 40, "pages": 40, "courses": 4})
            self.assertEqual(result["reasons"], [])


if __name__ == "__main__":
    unittest.main()
