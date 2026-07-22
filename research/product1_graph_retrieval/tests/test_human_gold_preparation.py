from __future__ import annotations

import copy
import sys
import unittest
from unittest import mock
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))
sys.path.insert(0, str(RESEARCH_ROOT / "tools"))

from src.annotation import (
    COMPLETED_ATTESTATION,
    compare_independent_annotations,
    finalize_with_adjudication,
    prepare_annotation_packet,
)
import tools.human_gold_candidate as human_gold_candidate
from tools.human_gold_candidate import (
    CANDIDATE_SCHEMA_VERSION,
    GOLD_ONLY_FILES,
    PROTOCOL_VERSION,
    PUBLIC_INPUT_FILES,
    SOURCE_CONTRACTS,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    HumanGoldPreparationError,
    assert_evaluation_allowed,
    assert_public_input_access,
    augment_candidate_comparison,
    candidate_gate_status,
    enrich_blind_packet,
    finalize_candidate_with_adjudication,
    preflight_authorized_sources,
    scan_direct_identifiers,
    validate_adjudication_metadata,
    validate_annotation_pair_metadata,
    validate_blind_packet,
)

MICRO = RESEARCH_ROOT / "datasets" / "micro_contract_v1"


def candidate_manifest() -> dict:
    return {
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": "human_gold_candidate_v0_1",
        "fixture_id": "human_gold_candidate_v0_1",
        "research_sidecar_schema_version": "product1-graph-retrieval-research-sidecar/1.0",
        "created_at": "2026-07-16T00:00:00+08:00",
        "dataset_level": "human_gold_candidate",
        "contains_personal_data": False,
        "course_ids": ["course_1", "course_2", "course_3", "course_4"],
        "files": {name: "sha256:" + "f" * 64 for name in sorted(PUBLIC_INPUT_FILES)},
        "candidate_content_sha256": "e" * 64,
        "source_contracts": copy.deepcopy(SOURCE_CONTRACTS),
        "access_policy": {
            "public_index_inputs": sorted(PUBLIC_INPUT_FILES),
            "gold_only": sorted(GOLD_ONLY_FILES),
            "gold_access": "evaluation_only_after_frozen_run",
        },
        "source_authorization": {
            "source_manifest_sha256": "a" * 64,
            "authorization_record_ref": "controlled://authorization/record",
            "privacy_review_ref": "controlled://privacy/review",
        },
        "gold": {
            "status": "pending_human_annotation",
            "eligible_for_algorithm_comparison": False,
        },
        "annotation": {},
        "governance": {},
    }


def completed_packet(task: str, member_id: str, role: str, relevance: int = 0) -> dict:
    packet = prepare_annotation_packet(MICRO, task=task, member_id=member_id)
    packet = enrich_blind_packet(packet, manifest=candidate_manifest(), role=role, member_id=member_id)
    packet["annotator"]["attestation"] = COMPLETED_ATTESTATION
    for item in packet["items"]:
        if task == "retrieval":
            item["answerability"] = "unanswerable_in_course"
            item["needs_adjudication"] = False
            judgments = {0: "not_relevant", 1: "partial_support", 2: "direct_support"}
        else:
            judgments = {0: "irrelevant_hard_negative", 1: "supporting_slide", 2: "primary_slide"}
        for row in item["candidates"]:
            row["relevance"] = relevance
            row["judgment"] = judgments[relevance]
            row["needs_adjudication"] = False
    return packet


class HumanGoldPreparationTests(unittest.TestCase):
    def test_unauthorized_source_manifest_fails_closed(self) -> None:
        path = RESEARCH_ROOT / "tests" / "_unauthorized_source_manifest.json"
        # No file is created: a missing manifest is itself a hard preflight failure.
        with self.assertRaises(HumanGoldPreparationError):
            preflight_authorized_sources(path)

    def test_authorized_raw_pptx_pdf_pairs_pass_source_preflight(self) -> None:
        courses = []
        for index in range(3):
            courses.append(
                {
                    "course_id": f"course_{index}",
                    "page_count": 1,
                    "page_pair_review": {
                        "status": "approved",
                        "reviewed_by": "page_reviewer",
                        "evidence_ref": "controlled://page-pair",
                        "pptx_pdf_same_page_count": True,
                    },
                    "authorization": {
                        "status": "approved",
                        "authorized_by": "material_owner",
                        "purpose": "human_gold_research_evaluation",
                        "evidence_ref": "controlled://authorization",
                        "valid_from": "2026-07-16T00:00:00+08:00",
                        "no_expiry": True,
                    },
                    "privacy_review": {
                        "status": "approved",
                        "reviewed_by": "privacy_reviewer",
                        "evidence_ref": "controlled://privacy",
                        "raw_material_access_approved": True,
                        "candidate_must_be_deidentified": True,
                        "known_direct_identifiers_present": True,
                        "sanitization_plan_ref": "controlled://privacy/sanitization-plan",
                    },
                    "files": [
                        {
                            "role": "pptx_source",
                            "path": f"course_{index}.pptx",
                            "sha256": "a" * 64,
                        },
                        {
                            "role": "pdf_reference",
                            "path": f"course_{index}.pdf",
                            "sha256": "a" * 64,
                        },
                    ],
                }
            )
        manifest = {
            "source_manifest_schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
            "candidate_id": "human_gold_candidate_v0_1",
            "source_contracts": copy.deepcopy(SOURCE_CONTRACTS),
            "repository_storage_authorized": True,
            "contains_student_records": False,
            "courses": courses,
        }
        manifest_path = RESEARCH_ROOT / "tests" / "source_bundle" / "authorized_source_manifest.json"
        with (
            mock.patch.object(human_gold_candidate, "_load_json", return_value=manifest),
            mock.patch.object(Path, "is_file", return_value=True),
            mock.patch.object(human_gold_candidate, "_sha256_file", return_value="a" * 64),
        ):
            result = preflight_authorized_sources(manifest_path)
        self.assertEqual(result["status"], "authorized_inputs_ready")
        self.assertEqual(result["course_count"], 3)
        self.assertEqual(result["checked_files"], 6)
    def test_blind_packet_rejects_score_rank_gold_and_prefilled_labels(self) -> None:
        packet = prepare_annotation_packet(MICRO, task="retrieval", member_id="member_A")
        packet = enrich_blind_packet(packet, manifest=candidate_manifest(), role="A", member_id="member_A")
        target_item = next(item for item in packet["items"] if item["candidates"])
        target_item["candidates"][0]["score"] = 0.9
        target_item["candidates"][0]["rank"] = 1
        target_item["candidates"][0]["gold"] = 2
        target_item["answerability"] = "answerable"
        with self.assertRaises(HumanGoldPreparationError):
            validate_blind_packet(packet)

    def test_gold_only_files_cannot_be_public_index_inputs(self) -> None:
        with self.assertRaises(HumanGoldPreparationError):
            assert_public_input_access(candidate_manifest(), ["retrieval_qrels.jsonl"])

    def test_pending_candidate_cannot_be_evaluated_even_as_contract_test(self) -> None:
        with self.assertRaises(HumanGoldPreparationError):
            assert_evaluation_allowed(candidate_manifest(), contract_test_only=True)

    def test_same_member_cannot_fill_A_and_B(self) -> None:
        left = completed_packet("retrieval", "member_1", "A")
        right = completed_packet("retrieval", "member_1", "B")
        with self.assertRaises(HumanGoldPreparationError):
            validate_annotation_pair_metadata(left, right)

    def test_adjudicator_must_be_third_member(self) -> None:
        left = completed_packet("mapping", "member_A", "A")
        right = completed_packet("mapping", "member_B", "B")
        adjudication = compare_independent_annotations(left, right)
        adjudication.update(
            {
                "candidate_id": left["candidate_id"],
                "protocol_version": PROTOCOL_VERSION,
                "source_manifest_sha256": left["source_manifest_sha256"],
                "source_contracts": copy.deepcopy(SOURCE_CONTRACTS),
            }
        )
        adjudication["annotator"].update({"member_id": "member_A", "role": "adjudicator"})
        with self.assertRaises(HumanGoldPreparationError):
            validate_adjudication_metadata(adjudication, left=left, right=right)

    def test_missing_adjudication_entry_is_rejected(self) -> None:
        left = completed_packet("mapping", "member_A", "A", relevance=0)
        right = completed_packet("mapping", "member_B", "B", relevance=0)
        right["items"][0]["candidates"][0].update(
            {"relevance": 2, "judgment": "primary_slide"}
        )
        adjudication = compare_independent_annotations(left, right)
        adjudication["annotator"] = {
            "member_id": "member_C",
            "kind": "human_team_member",
            "attestation": COMPLETED_ATTESTATION,
        }
        adjudication["items"] = []
        with self.assertRaises(ValueError):
            finalize_with_adjudication(left, right, adjudication)

    def test_complete_governance_only_approves_candidate_not_B_R1(self) -> None:
        manifest = candidate_manifest()
        manifest["gold"]["status"] = "human_adjudicated_candidate"
        manifest["annotation"] = {
            "independent_annotators": [
                {
                    "member_id": "member_A", "role": "A",
                    "task_coverage": ["retrieval", "mapping"],
                    "bundle_sha256": "1" * 64,
                    "identity_record_ref": "controlled://identity/member_A",
                    "independence_attestation_sha256": "4" * 64,
                },
                {
                    "member_id": "member_B", "role": "B",
                    "task_coverage": ["retrieval", "mapping"],
                    "bundle_sha256": "2" * 64,
                    "identity_record_ref": "controlled://identity/member_B",
                    "independence_attestation_sha256": "5" * 64,
                },
            ],
            "adjudication": {
                "member_id": "member_C", "complete": True,
                "identity_record_ref": "controlled://identity/member_C",
                "total_disagreements": 7, "resolved_disagreements": 7,
                "record_sha256": "3" * 64,
            },
            "calibration": {"completed": True, "record_ref": "calibration.md"},
        }
        decision = {
            "status": "approved", "reviewer_id": "reviewer",
            "decision_ref": "decision.md", "reviewed_at": "2026-07-16T00:00:00+08:00",
        }
        manifest["governance"] = {"p1_00": copy.deepcopy(decision), "p1_10": copy.deepcopy(decision)}
        status = candidate_gate_status(manifest)
        self.assertEqual(status["candidate_status"], "approved_candidate")
        self.assertFalse(status["eligible_for_algorithm_comparison"])
        self.assertEqual(status["b_r1_release"], "blocked_requires_separate_explicit_authorization")
        self.assertIn("manual_external_check", status["identity_verification"])

    def test_incomplete_candidate_is_blocked(self) -> None:
        status = candidate_gate_status(candidate_manifest())
        self.assertEqual(status["candidate_status"], "blocked")
        self.assertTrue(status["reasons"])

    def test_uncertain_agreement_is_forced_through_adjudication(self) -> None:
        left = completed_packet("mapping", "member_A", "A", relevance=0)
        right = completed_packet("mapping", "member_B", "B", relevance=0)
        left["items"][0]["candidates"][0]["needs_adjudication"] = True
        comparison = augment_candidate_comparison(
            compare_independent_annotations(left, right), left=left, right=right
        )
        self.assertEqual(comparison["agreement"]["label_disagreements"], 0)
        self.assertEqual(comparison["agreement"]["adjudication_required"], 1)
        self.assertEqual(comparison["items"][0]["reason"], "uncertainty_escalation")
        adjudication = comparison
        adjudication.update(
            {
                "candidate_id": left["candidate_id"],
                "protocol_version": PROTOCOL_VERSION,
                "source_manifest_sha256": left["source_manifest_sha256"],
                "source_contracts": copy.deepcopy(SOURCE_CONTRACTS),
            }
        )
        adjudication["annotator"].update(
            {
                "member_id": "member_C",
                "role": "adjudicator",
                "identity_not_verified_by_tool": True,
                "attestation": COMPLETED_ATTESTATION,
            }
        )
        adjudication["items"][0]["final_value"] = adjudication["items"][0]["left_value"]
        result = finalize_candidate_with_adjudication(left, right, adjudication)
        self.assertEqual(result["human_annotation"]["adjudicator_id"], "member_C")

    def test_direct_identifier_scanner_covers_common_student_fields(self) -> None:
        findings = scan_direct_identifiers(
            {
                "teacher_name": "example",
                "note": "学号: 20260001; email: learner@example.edu",
                "identity": "110101199001011234",
            }
        )
        joined = "|".join(findings)
        self.assertIn("person_name_key", joined)
        self.assertIn("student_number_pattern", joined)
        self.assertIn("email_pattern", joined)
        self.assertIn("identity_card_pattern", joined)

    def test_malformed_governance_is_blocked_without_crashing(self) -> None:
        manifest = candidate_manifest()
        manifest["annotation"] = "not-an-object"
        manifest["governance"] = ["not-an-object"]
        status = candidate_gate_status(manifest)
        self.assertEqual(status["candidate_status"], "blocked")
        self.assertIn("annotation_governance_must_be_object", status["reasons"])
        self.assertIn("governance_must_be_object", status["reasons"])

if __name__ == "__main__":
    unittest.main()


