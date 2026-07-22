from __future__ import annotations

import copy
import html
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

from src.annotation import prepare_annotation_packet
from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file, write_json, write_jsonl
from src.fixture_io import load_json, load_jsonl
from tools.human_gold_builder import (HumanGoldBuildError, build_human_gold_candidate,
    make_human_selection_template, validate_human_gold_candidate_bundle)
from tools.human_gold_candidate import enrich_blind_packet

TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"
STRATA = ["exact_term", "definition", "formula_or_code", "paraphrase", "cross_language_alias", "multi_hop_relation", "no_answer"]

@contextmanager
def test_directory():
    path = TEMP_ROOT / f"builder_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)

def write_pptx(path: Path, count: int, *, picture_on_first: bool = False) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for number in range(1, count + 1):
            pic = "<p:pic/>" if picture_on_first and number == 1 else ""
            text = "x" if picture_on_first and number == 1 else f"Course slide {number} content for grounded retrieval"
            if number == 2: text += " contact@example.edu"
            xml = (f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
                f'<p:sp><p:txBody><a:p><a:r><a:t>{html.escape(text)}</a:t></a:r></a:p></p:txBody></p:sp>'
                f'{pic}</p:spTree></p:cSld></p:sld>')
            archive.writestr(f"ppt/slides/slide{number}.xml", xml.encode("utf-8"))

def make_inputs(root: Path, *, picture_on_first: bool = False) -> tuple[Path, Path]:
    bundle = root / "source_bundle"; bundle.mkdir()
    courses = []
    for index in range(3):
        cid = f"course_{index}"
        pptx, pdf = bundle / f"{cid}.pptx", bundle / f"{cid}.pdf"
        write_pptx(pptx, 34, picture_on_first=picture_on_first and index == 0)
        pdf.write_bytes(f"synthetic contract PDF {cid}".encode())
        courses.append({"course_id": cid, "page_count": 34,
            "page_pair_review": {"status": "approved", "reviewed_by": "page_reviewer",
                "evidence_ref": "controlled://page-pair", "pptx_pdf_same_page_count": True},
            "authorization": {"status": "approved", "authorized_by": "material_owner",
                "purpose": "human_gold_research_evaluation", "evidence_ref": "controlled://authorization",
                "valid_from": "2026-07-16T00:00:00+08:00", "no_expiry": True},
            "privacy_review": {"status": "approved", "reviewed_by": "privacy_reviewer",
                "evidence_ref": "controlled://privacy", "raw_material_access_approved": True,
                "candidate_must_be_deidentified": True, "known_direct_identifiers_present": True,
                "sanitization_plan_ref": "controlled://privacy/plan"},
            "files": [{"role": "pptx_source", "path": pptx.name, "sha256": sha256_file(pptx)},
                {"role": "pdf_reference", "path": pdf.name, "sha256": sha256_file(pdf)}]})
    source = {"source_manifest_schema_version": "product1-graph-retrieval-authorized-sources/1.0",
        "candidate_id": "human_gold_candidate_v0_1", "source_contracts": {"document_ir": "document-ir/1.0",
            "evidence": "evidence/1.0", "citation": "citation/1.0", "education_graph": "edu-graph/1.0"},
        "repository_storage_authorized": True, "contains_student_records": False, "courses": courses}
    source_path = bundle / "authorized_source_manifest.json"; write_json(source_path, source)
    source_hash = sha256_file(source_path)
    selected_courses = []
    query_number = 0; kp_number = 0
    query_counts, kp_counts = [20, 20, 19], [14, 13, 13]
    for index, cid in enumerate(["course_0", "course_1", "course_2"]):
        queries = []
        for _ in range(query_counts[index]):
            stratum = STRATA[query_number % len(STRATA)]
            queries.append({"text": f"Human query {query_number} for {cid}", "query_type": "human_authored",
                "query_stratum": stratum, "split": ["train", "validation", "test"][query_number % 3],
                "tags": [stratum]}); query_number += 1
        kps = []
        for _ in range(kp_counts[index]):
            kps.append({"canonical_label": f"Knowledge point {kp_number} for {cid}",
                "aliases": [f"KP alias {kp_number}"], "chapter_id": f"chapter_{cid}",
                "chapter_path": [cid, f"chapter_{cid}"], "split": ["validation", "test"][kp_number % 2]}); kp_number += 1
        selected_courses.append({"course_id": cid, "redaction_terms": [],
            "redaction_terms_reviewed_by": "privacy_reviewer", "redaction_evidence_ref": "controlled://redaction",
            "slide_chapter_ranges": [{"start_slide": 1, "end_slide": 34, "chapter_id": f"chapter_{cid}",
                "chapter_path": [cid, f"chapter_{cid}"]}], "ocr_records": [], "queries": queries,
            "knowledge_points": kps})
    selection = {"selection_schema_version": "product1-graph-retrieval-human-selection/0.1",
        "candidate_id": "human_gold_candidate_v0_1", "source_manifest_sha256": source_hash,
        "created_at": "2026-07-16T12:00:00+08:00", "created_by_member_id": "query_kp_curator",
        "attestation": "human_selected_without_gold_labels_or_model_rankings",
        "candidate_privacy_plan": {"status": "approved", "reviewed_by": "privacy_reviewer",
            "evidence_ref": "controlled://candidate-privacy", "candidate_must_be_deidentified": True},
        "courses": selected_courses, "scope_queries": [{"course_id": "course_unavailable",
            "text": "Human scope query", "query_type": "scope_probe", "query_stratum": "no_answer",
            "split": "test", "tags": ["scope_probe"]}]}
    selection_path = bundle / "human_selection.json"; write_json(selection_path, selection)
    return source_path, selection_path
class HumanGoldBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_template_is_pending_and_contains_no_gold_labels(self) -> None:
        with test_directory() as root:
            source, _ = make_inputs(root)
            template = make_human_selection_template(source)
            self.assertEqual(len(template["courses"]), 3)
            self.assertEqual(template["attestation"], "PENDING_HUMAN_ATTESTATION")
            serialized = json.dumps(template)
            self.assertNotIn("answerability", serialized)
            self.assertNotIn("relevance", serialized)
            self.assertNotIn("model_recommendation", serialized)
    def test_build_is_reproducible_unlabelled_and_reference_closed(self) -> None:
        with test_directory() as root:
            source, selection = make_inputs(root)
            first = root / "first" / "human_gold_candidate_v0_1"
            second = root / "second" / "human_gold_candidate_v0_1"
            audit = build_human_gold_candidate(source, selection, first)
            build_human_gold_candidate(source, selection, second)
            self.assertTrue(audit["valid"])
            self.assertEqual(audit["counts"]["courses"], 3)
            self.assertEqual(audit["counts"]["chunks"], 102)
            self.assertEqual(audit["counts"]["queries"], 60)
            self.assertEqual(audit["counts"]["knowledge_points"], 40)
            first_files = {p.name: p.read_bytes() for p in first.iterdir() if p.is_file()}
            second_files = {p.name: p.read_bytes() for p in second.iterdir() if p.is_file()}
            self.assertEqual(first_files, second_files)
            self.assertFalse(any((first / name).exists() for name in (
                "retrieval_qrels.jsonl", "retrieval_query_labels.jsonl", "mapping_qrels.jsonl")))
            manifest = load_json(first / "manifest.json")
            self.assertEqual(manifest["gold"]["status"], "pending_human_annotation")
            self.assertFalse(manifest["gold"]["eligible_for_algorithm_comparison"])
            self.assertGreater(manifest["normalization"]["redaction_replacements"], 0)
            self.assertFalse(any("contact@example.edu" in row["text"] for row in load_jsonl(first / "corpus.jsonl")))

    def test_source_selection_and_candidate_instances_match_schemas(self) -> None:
        with test_directory() as root:
            source, selection = make_inputs(root)
            candidate = root / "human_gold_candidate_v0_1"
            build_human_gold_candidate(source, selection, candidate)
            pairs = (
                (RESEARCH_ROOT / "schemas" / "authorized_source_manifest.schema.json", source),
                (RESEARCH_ROOT / "schemas" / "human_gold_selection.schema.json", selection),
                (RESEARCH_ROOT / "schemas" / "human_gold_candidate_manifest.schema.json", candidate / "manifest.json"),
            )
            for schema_path, instance_path in pairs:
                schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(load_json(instance_path))
    def test_actual_candidate_packet_is_course_closed_and_has_visual_refs(self) -> None:
        with test_directory() as root:
            source, selection = make_inputs(root)
            candidate = root / "human_gold_candidate_v0_1"
            build_human_gold_candidate(source, selection, candidate)
            manifest = load_json(candidate / "manifest.json")
            packet = prepare_annotation_packet(candidate, task="mapping", member_id="member_A")
            packet = enrich_blind_packet(packet, manifest=manifest, role="A", member_id="member_A")
            for item in packet["items"]:
                for row in item["candidates"]:
                    self.assertEqual(row["course_id"], item["course_id"])
                    self.assertTrue(row["controlled_source_ref"].startswith("controlled-source://"))
                    self.assertTrue(row["requires_visual_review"])
                    self.assertNotIn("score", row); self.assertNotIn("rank", row); self.assertNotIn("gold", row)
            schema = json.loads((RESEARCH_ROOT / "schemas" / "annotation.schema.json").read_text(encoding="utf-8-sig"))
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            validator.validate(packet)
            retrieval = prepare_annotation_packet(candidate, task="retrieval", member_id="member_A")
            retrieval = enrich_blind_packet(retrieval, manifest=manifest, role="A", member_id="member_A")
            validator.validate(retrieval)
    def test_record_level_validator_detects_tampering_after_hash_refresh(self) -> None:
        with test_directory() as root:
            source, selection = make_inputs(root)
            candidate = root / "human_gold_candidate_v0_1"
            build_human_gold_candidate(source, selection, candidate)
            rows = load_jsonl(candidate / "evidence.jsonl"); rows[0]["text_snippet"] = "tampered"
            write_jsonl(candidate / "evidence.jsonl", rows)
            manifest = load_json(candidate / "manifest.json")
            manifest["files"]["evidence.jsonl"] = f"sha256:{sha256_file(candidate / 'evidence.jsonl')}"
            manifest["candidate_content_sha256"] = sha256_bytes(canonical_json_bytes(manifest["files"]))
            write_json(candidate / "manifest.json", manifest)
            with self.assertRaises(HumanGoldBuildError) as raised:
                validate_human_gold_candidate_bundle(candidate)
            self.assertIn("evidence_snippet_mismatch", str(raised.exception))

    def test_selection_rejects_gold_or_algorithm_leak(self) -> None:
        with test_directory() as root:
            source, selection_path = make_inputs(root)
            selection = load_json(selection_path)
            selection["courses"][0]["queries"][0]["answerability"] = "answerable"
            write_json(selection_path, selection)
            with self.assertRaises(HumanGoldBuildError) as raised:
                build_human_gold_candidate(source, selection_path, root / "human_gold_candidate_v0_1")
            self.assertIn("selection_gold_or_algorithm_leak", str(raised.exception))

    def test_human_reviewed_ocr_preserves_structure_without_score_leak_to_packet(self) -> None:
        with test_directory() as root:
            source, selection_path = make_inputs(root, picture_on_first=True)
            selection = load_json(selection_path)
            selection["courses"][0]["ocr_provenance"] = {
                "engine": "PP-StructureV3", "engine_version": "3.7.0", "config_sha256": "a" * 64
            }
            selection["courses"][0]["ocr_records"] = [{
                "slide_number": 1, "review_status": "human_reviewed_for_candidate",
                "blocks": [{"order": 1, "text": "reviewed diagram label", "bbox": [1, 2, 3, 4], "confidence": 0.91}],
            }]
            write_json(selection_path, selection)
            candidate = root / "human_gold_candidate_v0_1"
            build_human_gold_candidate(source, selection_path, candidate)
            slides = load_jsonl(candidate / "slides.jsonl")
            reviewed = next(row for row in slides if row["course_id"] == "course_0" and row["slide_number"] == 1)
            self.assertEqual(reviewed["research_ocr_blocks"][0]["order"], 1)
            self.assertEqual(reviewed["research_ocr_blocks"][0]["bbox"], [1, 2, 3, 4])
            self.assertEqual(reviewed["research_ocr_blocks"][0]["confidence"], 0.91)
            manifest = load_json(candidate / "manifest.json")
            self.assertEqual(manifest["normalization"]["ocr_provenance_by_course"]["course_0"]["engine"], "PP-StructureV3")
            packet = prepare_annotation_packet(candidate, task="mapping", member_id="member_A")
            packet = enrich_blind_packet(packet, manifest=manifest, role="A", member_id="member_A")
            self.assertNotIn("confidence", json.dumps(packet))
            self.assertNotIn("bbox", json.dumps(packet))
    def test_low_text_picture_requires_human_reviewed_ocr(self) -> None:
        with test_directory() as root:
            source, selection = make_inputs(root, picture_on_first=True)
            with self.assertRaises(HumanGoldBuildError) as raised:
                build_human_gold_candidate(source, selection, root / "human_gold_candidate_v0_1")
            self.assertIn("human_reviewed_ocr_required", str(raised.exception))

    def test_visual_review_can_confirm_no_relevant_text_without_fake_ocr(self) -> None:
        with test_directory() as root:
            source, selection_path = make_inputs(root, picture_on_first=True)
            selection = load_json(selection_path)
            selection["courses"][0]["ocr_records"] = [{
                "slide_number": 1,
                "review_status": "human_reviewed_no_relevant_text",
                "blocks": [],
            }]
            write_json(selection_path, selection)
            candidate = root / "human_gold_candidate_v0_1"
            build_human_gold_candidate(source, selection_path, candidate)
            slide = next(row for row in load_jsonl(candidate / "slides.jsonl")
                if row["course_id"] == "course_0" and row["slide_number"] == 1)
            self.assertEqual(slide["ocr_review_status"], "human_reviewed_no_relevant_text")
            self.assertNotIn("human_reviewed_ocr", slide["content_sources"])
            self.assertEqual(slide["research_ocr_blocks"], [])

    def test_no_relevant_text_review_rejects_ocr_blocks(self) -> None:
        with test_directory() as root:
            source, selection_path = make_inputs(root, picture_on_first=True)
            selection = load_json(selection_path)
            selection["courses"][0]["ocr_records"] = [{
                "slide_number": 1,
                "review_status": "human_reviewed_no_relevant_text",
                "blocks": [{"order": 1, "text": "must not coexist", "bbox": [1, 2, 3, 4], "confidence": 1.0}],
            }]
            write_json(selection_path, selection)
            with self.assertRaises(HumanGoldBuildError) as raised:
                build_human_gold_candidate(source, selection_path, root / "human_gold_candidate_v0_1")
            self.assertIn("ocr_no_text_review_must_have_no_blocks", str(raised.exception))

if __name__ == "__main__":
    unittest.main()