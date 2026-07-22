from __future__ import annotations

import copy
import csv
import io
import json
import shutil
import sys
import unittest
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import canonical_json_bytes
from src.fixture_io import load_json
from tools.human_selection_review import (
    FORBIDDEN_REVIEW_KEYS,
    HumanSelectionReviewError,
    finalize_selection_review,
    prepare_selection_review,
    validate_selection_review,
)


TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"
VARIANTS = ("direct_definition", "mechanism_application", "hard_negative", "cross_course_isolation")


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"selection_review_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def write_csv(path: Path, rows: list[dict[str, object]], encoding: str) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode(encoding))


def write_pptx(path: Path, count: int) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for number in range(1, count + 1):
            picture = "<p:pic/>" if number == 1 else ""
            text = "x" if number == 1 else f"Course content slide {number}"
            archive.writestr(f"ppt/slides/slide{number}.xml",
                f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
                f'{picture}<a:t>{text}</a:t></p:spTree></p:cSld></p:sld>')


def make_source(root: Path) -> None:
    queries, kps, pages = [], [], []
    for course_index, page_count in enumerate((10, 11, 12, 13)):
        cid = f"C{course_index}"
        pptx = root / f"course_{course_index}.pptx"
        write_pptx(pptx, page_count)
        pptx.with_suffix(".pdf").write_bytes(b"%PDF-1.4\nsynthetic contract input\n")
        for page in range(1, page_count + 1):
            pages.append({"course_id": cid, "course_name": f"Course {course_index}",
                "source_file": f"old_course_{course_index}(1).pptx", "ppt_page": page,
                "slide_title_or_first_text": f"Slide {page}", "content_preview": f"Content {page}",
                "is_blank_or_transition": "否"})
        for kp_index in range(10):
            kid = f"{cid}-KP{kp_index:02d}"
            kps.append({"knowledge_point_id": kid, "course_id": cid, "course_name": f"Course {course_index}",
                "source_file": f"old_course_{course_index}(1).pptx", "chapter_range": "Chapter 1",
                "knowledge_point": f"Knowledge {course_index}-{kp_index}", "ppt_page_start": kp_index + 1,
                "ppt_page_end": kp_index + 1, "ppt_page_range": str(kp_index + 1),
                "evidence_summary": "seed hint must not enter review", "seed_query_count": 4})
            for variant_index, variant in enumerate(VARIANTS):
                queries.append({"seed_id": f"{kid}-Q{variant_index}", "course_id": cid,
                    "knowledge_point": f"Knowledge {course_index}-{kp_index}",
                    "ppt_page_range": str(kp_index + 1), "query_text": f"Question {course_index}-{kp_index}-{variant}",
                    "expected_answerability": "answerable", "knowledge_point_id": kid,
                    "course_name": f"Course {course_index}", "source_file": f"old_course_{course_index}(1).pptx",
                    "chapter_range": "Chapter 1", "query_variant": variant,
                    "gold_answer_hint": "must be stripped", "review_status": "待复核", "reviewer_note": ""})
    write_csv(root / "queries.csv", queries, "gb18030")
    write_csv(root / "knowledge_points.csv", kps, "utf-8-sig")
    write_csv(root / "pages.csv", pages, "utf-8-sig")


def complete_review(packet: dict) -> dict:
    packet = copy.deepcopy(packet)
    packet["status"] = "human_review_complete"
    governance = packet["source_governance"]
    governance["authorization"].update({"status": "approved", "authorized_by": "member_owner",
        "valid_from": "2026-07-16T00:00:00+08:00", "no_expiry": True})
    governance["privacy"].update({"status": "approved", "reviewed_by": "member_privacy"})
    governance["repository_storage_authorized"] = True
    for course in packet["courses"]:
        course["file_mapping_review"] = {"status": "approved", "reviewed_by": "member_mapper",
            "evidence_ref": "controlled://page-pair"}
        course["redaction_review"] = {"status": "approved", "reviewed_by": "member_privacy",
            "evidence_ref": "controlled://redaction"}
    chapters_by_course = {}
    for row in packet["chapter_candidates"]:
        course = next(value for value in packet["courses"] if value["course_id"] == row["course_id"])
        chapter_id = f"{row['course_id']}_chapter_1"
        row.update({"final_start_slide": 1, "final_end_slide": course["page_count"],
            "final_chapter_id": chapter_id, "final_chapter_path": [row["course_id"], chapter_id]})
        row["human_review"] = {"status": "approved", "selected": True,
            "reviewed_by": "member_selector", "review_note": "confirmed"}
        chapters_by_course[row["course_id"]] = (chapter_id, [row["course_id"], chapter_id])
    for row in packet["query_candidates"]:
        row.update({"final_query_type": row["suggested_query_type_not_gold"],
            "final_query_stratum": row["suggested_query_stratum_not_gold"],
            "final_split": row["suggested_split_not_gold"]})
        row["human_review"] = {"status": "approved", "selected": True,
            "reviewed_by": "member_selector", "review_note": "confirmed"}
    for row in packet["knowledge_point_candidates"]:
        chapter_id, path = chapters_by_course[row["course_id"]]
        row.update({"final_chapter_id": chapter_id, "final_chapter_path": path,
            "final_split": row["suggested_split_not_gold"]})
        row["human_review"] = {"status": "approved", "selected": True,
            "reviewed_by": "member_selector", "review_note": "confirmed"}
    for row in packet["ocr_review_tasks"]:
        row["decision"] = "no_relevant_text"; row["blocks"] = []
        row["human_review"] = {"status": "approved", "selected": True,
            "reviewed_by": "member_visual", "review_note": "original page checked"}
    scope = packet["scope_query_candidates"][0]
    scope.update({"unavailable_course_id": "MISSING_COURSE", "text": "What is covered by the missing course?",
        "final_query_type": "scope_check", "final_split": "test"})
    scope["human_review"] = {"status": "approved", "selected": True,
        "reviewed_by": "member_selector", "review_note": "confirmed"}
    packet["human_finalization"] = {"status": "approved", "finalized_by": "member_selector",
        "finalized_at": "2026-07-16T01:00:00+08:00",
        "attestation": "human_selected_without_gold_labels_or_model_rankings"}
    return packet


class HumanSelectionReviewTests(unittest.TestCase):
    def test_prepare_is_reproducible_private_and_schema_valid(self) -> None:
        with test_directory() as root:
            make_source(root)
            first = prepare_selection_review(root, query_target=64)
            second = prepare_selection_review(root, query_target=64)
            self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
            self.assertEqual(validate_selection_review(first)["counts"], {
                "courses": 4, "queries": 64, "knowledge_points": 40, "chapters": 4,
                "ocr_review_tasks": 4})
            serialized = json.dumps(first, ensure_ascii=False)
            for key in FORBIDDEN_REVIEW_KEYS:
                self.assertNotIn(f'"{key}"', serialized)
            schema = load_json(RESEARCH_ROOT / "schemas" / "human_selection_review.schema.json")
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(first)

    def test_pending_review_cannot_finalize(self) -> None:
        with test_directory() as root:
            make_source(root); packet = prepare_selection_review(root, query_target=64)
            with self.assertRaises(HumanSelectionReviewError) as raised:
                finalize_selection_review(packet, root, root / "authorized_source_manifest.json", root / "selection.json")
            self.assertIn("human_finalization_attestation_missing", str(raised.exception))

    def test_completed_review_emits_schema_valid_source_and_selection_without_seed_hints(self) -> None:
        with test_directory() as root:
            make_source(root); packet = complete_review(prepare_selection_review(root, query_target=64))
            source_manifest, selection = root / "authorized_source_manifest.json", root / "selection.json"
            result = finalize_selection_review(packet, root, source_manifest, selection)
            self.assertEqual(result["status"], "human_selection_ready_for_candidate_build")
            for filename, schema_name in ((source_manifest, "authorized_source_manifest.schema.json"),
                (selection, "human_gold_selection.schema.json")):
                value = load_json(filename); schema = load_json(RESEARCH_ROOT / "schemas" / schema_name)
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
                serialized = json.dumps(value)
                self.assertNotIn("gold_answer_hint", serialized)
                self.assertNotIn("expected_answerability", serialized)


if __name__ == "__main__":
    unittest.main()
