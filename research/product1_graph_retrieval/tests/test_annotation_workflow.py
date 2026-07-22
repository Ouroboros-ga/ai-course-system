from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.annotation import (
    COMPLETED_ATTESTATION,
    compare_independent_annotations,
    finalize_with_adjudication,
    prepare_annotation_packet,
)

FIXTURE = RESEARCH_ROOT / "datasets" / "micro_contract_v1"


def complete_for_contract_test(packet: dict, *, member_id: str, relevance: int = 0) -> dict:
    result = copy.deepcopy(packet)
    result["annotator"] = {
        "member_id": member_id,
        "kind": "human_team_member",
        "attestation": COMPLETED_ATTESTATION,
    }
    for item in result["items"]:
        if result["task"] == "retrieval":
            item["answerability"] = "unanswerable_in_course"
            for candidate in item["candidates"]:
                candidate["relevance"] = relevance
                candidate["judgment"] = {0: "not_relevant", 1: "partial_support", 2: "direct_support"}[relevance]
        else:
            for candidate in item["candidates"]:
                candidate["relevance"] = relevance
                candidate["judgment"] = {
                    0: "irrelevant_hard_negative",
                    1: "supporting_slide",
                    2: "primary_slide",
                }[relevance]
    return result


class AnnotationWorkflowTests(unittest.TestCase):
    def test_packets_use_stable_id_order_not_algorithm_rank(self) -> None:
        packet = prepare_annotation_packet(FIXTURE, task="retrieval", member_id="pending_member")
        self.assertEqual(packet["candidate_order"], "stable_research_id_ascending_not_algorithm_rank")
        for item in packet["items"]:
            ids = [candidate["research_evidence_id"] for candidate in item["candidates"]]
            self.assertEqual(ids, sorted(ids))
            self.assertTrue(all("rank" not in candidate and "score" not in candidate for candidate in item["candidates"]))

    def test_distinct_members_are_required(self) -> None:
        packet = prepare_annotation_packet(FIXTURE, task="retrieval", member_id="pending")
        left = complete_for_contract_test(packet, member_id="test_human_1")
        right = complete_for_contract_test(packet, member_id="test_human_1")
        with self.assertRaises(ValueError):
            compare_independent_annotations(left, right)

    def test_disagreement_requires_distinct_human_adjudicator(self) -> None:
        packet = prepare_annotation_packet(FIXTURE, task="mapping", member_id="pending")
        left = complete_for_contract_test(packet, member_id="test_human_1")
        right = complete_for_contract_test(packet, member_id="test_human_2")
        right["items"][0]["candidates"][0]["relevance"] = 2
        right["items"][0]["candidates"][0]["judgment"] = "primary_slide"
        comparison = compare_independent_annotations(left, right)
        self.assertEqual(comparison["agreement"]["disagreed"], 1)
        adjudication = copy.deepcopy(comparison)
        adjudication["annotator"] = {
            "member_id": "test_human_adjudicator",
            "kind": "human_team_member",
            "attestation": COMPLETED_ATTESTATION,
        }
        adjudication["items"][0]["final_value"] = 2
        frozen = finalize_with_adjudication(left, right, adjudication)
        self.assertEqual(frozen["human_annotation"]["adjudicator_id"], "test_human_adjudicator")
        self.assertIn("mapping_qrels", frozen)


if __name__ == "__main__":
    unittest.main()
