"""Human annotation packet preparation and independence checks.

The tooling can verify structure, distinct member IDs, agreement, and complete
adjudication.  It cannot prove that an identity belongs to a human; P1-10 must
verify that evidence outside this tool before accepting a gold release.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .fixture_io import load_json, load_jsonl


ANNOTATION_SCHEMA_VERSION = "product1-graph-retrieval-human-annotation/1.0"
COMPLETED_ATTESTATION = "completed_independently_without_algorithm_rankings"


def prepare_annotation_packet(
    fixture_dir: Path,
    *,
    task: str,
    member_id: str,
) -> dict[str, Any]:
    """Create an unlabelled, stable-ID-ordered packet without algorithm ranks."""

    fixture_dir = Path(fixture_dir)
    manifest = load_json(fixture_dir / "manifest.json")
    evidence = load_jsonl(fixture_dir / "evidence.jsonl")
    if task == "retrieval":
        queries = load_jsonl(fixture_dir / "queries.jsonl")
        items = []
        for query in sorted(queries, key=lambda row: row["research_query_id"]):
            candidates = [
                {
                    "research_evidence_id": row["research_evidence_id"],
                    "artifact_id": row["artifact_id"],
                    "document_id": row["document_id"],
                    "unit_id": row["unit_id"],
                    "block_id": row["block_id"],
                    "page_or_slide": row["page_or_slide"],
                    "text_snippet": row["text_snippet"],
                    "status": row["status"],
                    "relevance": None,
                    "judgment": None,
                }
                for row in evidence
                if row["course_id"] == query["course_id"]
            ]
            candidates.sort(key=lambda row: row["research_evidence_id"])
            items.append(
                {
                    "research_query_id": query["research_query_id"],
                    "course_id": query["course_id"],
                    "query_text": query["text"],
                    "query_stratum": query["query_stratum"],
                    "answerability": None,
                    "candidates": candidates,
                    "annotation_note": "",
                }
            )
    elif task == "mapping":
        knowledge_points = load_jsonl(fixture_dir / "knowledge_points.jsonl")
        slides = load_jsonl(fixture_dir / "slides.jsonl")
        items = []
        for kp in sorted(knowledge_points, key=lambda row: row["research_knowledge_point_id"]):
            candidates = [
                {
                    "research_slide_id": row["research_slide_id"],
                    "slide_number": row["slide_number"],
                    "title": row["title"],
                    "body_text": row["body_text"],
                    "research_evidence_ids": row["research_evidence_ids"],
                    "relevance": None,
                    "judgment": None,
                }
                for row in slides
                if row["course_id"] == kp["course_id"]
            ]
            candidates.sort(key=lambda row: row["research_slide_id"])
            items.append(
                {
                    "research_knowledge_point_id": kp["research_knowledge_point_id"],
                    "course_id": kp["course_id"],
                    "canonical_label": kp["canonical_label"],
                    "aliases": kp["aliases"],
                    "candidates": candidates,
                    "annotation_note": "",
                }
            )
    else:
        raise ValueError("task must be retrieval or mapping")

    return {
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "fixture_id": manifest["fixture_id"],
        "task": task,
        "candidate_order": "stable_research_id_ascending_not_algorithm_rank",
        "annotator": {
            "member_id": member_id,
            "kind": "human_team_member",
            "attestation": "PENDING_HUMAN_COMPLETION",
        },
        "independent": True,
        "items": items,
    }


def validate_completed_annotation_bundle(bundle: dict[str, Any]) -> None:
    if bundle.get("annotation_schema_version") != ANNOTATION_SCHEMA_VERSION:
        raise ValueError("unsupported annotation schema")
    if bundle.get("task") not in {"retrieval", "mapping", "adjudication"}:
        raise ValueError("invalid annotation task")
    annotator = bundle.get("annotator", {})
    if annotator.get("kind") != "human_team_member":
        raise ValueError("only a human team member may attest a gold annotation")
    if annotator.get("attestation") != COMPLETED_ATTESTATION:
        raise ValueError("human completion attestation is missing")
    if not annotator.get("member_id"):
        raise ValueError("member_id is required")
    if bundle.get("task") != "adjudication" and bundle.get("independent") is not True:
        raise ValueError("primary annotations must be independent")

    for item in bundle.get("items", []):
        if bundle["task"] == "retrieval":
            if item.get("answerability") not in {
                "answerable",
                "unanswerable_in_course",
                "scope_not_available",
                "evidence_stale_only",
            }:
                raise ValueError("every retrieval item needs answerability")
            for candidate in item.get("candidates", []):
                if candidate.get("relevance") not in {0, 1, 2}:
                    raise ValueError("every retrieval candidate needs relevance 0/1/2")
                expected = {0: "not_relevant", 1: "partial_support", 2: "direct_support"}[
                    candidate["relevance"]
                ]
                if candidate.get("judgment") != expected:
                    raise ValueError("retrieval judgment does not match relevance")
        elif bundle["task"] == "mapping":
            for candidate in item.get("candidates", []):
                if candidate.get("relevance") not in {0, 1, 2}:
                    raise ValueError("every mapping candidate needs relevance 0/1/2")
                expected = {
                    0: "irrelevant_hard_negative",
                    1: "supporting_slide",
                    2: "primary_slide",
                }[candidate["relevance"]]
                if candidate.get("judgment") != expected:
                    raise ValueError("mapping judgment does not match relevance")


def _flatten(bundle: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if bundle["task"] == "retrieval":
        for item in bundle["items"]:
            query_id = item["research_query_id"]
            flat[f"answerability|{query_id}"] = item["answerability"]
            for candidate in item["candidates"]:
                key = f"retrieval|{query_id}|{candidate['research_evidence_id']}"
                flat[key] = candidate["relevance"]
    elif bundle["task"] == "mapping":
        for item in bundle["items"]:
            kp_id = item["research_knowledge_point_id"]
            for candidate in item["candidates"]:
                key = f"mapping|{kp_id}|{candidate['research_slide_id']}"
                flat[key] = candidate["relevance"]
    else:
        for item in bundle["items"]:
            flat[item["key"]] = item["final_value"]
    return flat


def compare_independent_annotations(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    validate_completed_annotation_bundle(left)
    validate_completed_annotation_bundle(right)
    if left["task"] != right["task"] or left["fixture_id"] != right["fixture_id"]:
        raise ValueError("annotation bundles must target the same fixture and task")
    left_member = left["annotator"]["member_id"]
    right_member = right["annotator"]["member_id"]
    if left_member == right_member:
        raise ValueError("two distinct human team members are required")
    left_flat, right_flat = _flatten(left), _flatten(right)
    if set(left_flat) != set(right_flat):
        raise ValueError("independent annotation candidate sets differ")
    disagreements = [
        {"key": key, "left_value": left_flat[key], "right_value": right_flat[key], "final_value": None}
        for key in sorted(left_flat)
        if left_flat[key] != right_flat[key]
    ]
    agreed = len(left_flat) - len(disagreements)
    return {
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "fixture_id": left["fixture_id"],
        "task": "adjudication",
        "source_task": left["task"],
        "candidate_order": "stable_key_ascending",
        "source_annotator_ids": [left_member, right_member],
        "agreement": {
            "judgments": len(left_flat),
            "agreed": agreed,
            "disagreed": len(disagreements),
            "raw_agreement": 1.0 if not left_flat else agreed / len(left_flat),
        },
        "annotator": {
            "member_id": "PENDING_HUMAN_ADJUDICATOR",
            "kind": "human_team_member",
            "attestation": "PENDING_HUMAN_COMPLETION",
        },
        "independent": False,
        "items": disagreements,
    }


def finalize_with_adjudication(
    left: dict[str, Any],
    right: dict[str, Any],
    adjudication: dict[str, Any],
) -> dict[str, Any]:
    """Return frozen gold records after a third human resolves all conflicts."""

    comparison = compare_independent_annotations(left, right)
    validate_completed_annotation_bundle(adjudication)
    if adjudication.get("task") != "adjudication":
        raise ValueError("an adjudication bundle is required")
    if (
        adjudication.get("fixture_id") != left["fixture_id"]
        or adjudication.get("source_task") != left["task"]
    ):
        raise ValueError("adjudication targets a different fixture or source task")
    adjudicator = adjudication["annotator"]["member_id"]
    if adjudicator in comparison["source_annotator_ids"]:
        raise ValueError("adjudicator must be distinct from both primary annotators")
    expected = {item["key"] for item in comparison["items"]}
    supplied = {item.get("key") for item in adjudication.get("items", [])}
    if expected != supplied:
        raise ValueError("adjudication must resolve every disagreement exactly once")
    final_values = _flatten(adjudication)
    for key, value in final_values.items():
        if key.startswith("answerability|"):
            if value not in {
                "answerable",
                "unanswerable_in_course",
                "scope_not_available",
                "evidence_stale_only",
            }:
                raise ValueError(f"invalid adjudicated answerability for {key}")
        elif value not in {0, 1, 2}:
            raise ValueError(f"invalid adjudicated relevance for {key}")
    left_flat, right_flat = _flatten(left), _flatten(right)
    for key in left_flat:
        if left_flat[key] == right_flat[key]:
            final_values[key] = left_flat[key]

    result: dict[str, Any] = {
        "fixture_id": left["fixture_id"],
        "source_task": left["task"],
        "human_annotation": {
            "independent_human_annotator_ids": comparison["source_annotator_ids"],
            "adjudicator_id": adjudicator,
            "agreement": comparison["agreement"],
        },
    }
    if left["task"] == "retrieval":
        labels = []
        qrels = []
        for key, value in sorted(final_values.items()):
            parts = key.split("|")
            if parts[0] == "answerability":
                labels.append({"research_query_id": parts[1], "answerability": value})
            else:
                relevance = int(value)
                qrels.append(
                    {
                        "research_query_id": parts[1],
                        "research_evidence_id": parts[2],
                        "relevance": relevance,
                        "judgment": {0: "not_relevant", 1: "partial_support", 2: "direct_support"}[relevance],
                    }
                )
        result["retrieval_query_labels"] = labels
        result["retrieval_qrels"] = qrels
    else:
        qrels = []
        source_items = {
            (item["research_knowledge_point_id"], candidate["research_slide_id"]): candidate
            for item in left["items"]
            for candidate in item["candidates"]
        }
        for key, value in sorted(final_values.items()):
            _, kp_id, slide_id = key.split("|")
            relevance = int(value)
            qrels.append(
                {
                    "research_knowledge_point_id": kp_id,
                    "research_slide_id": slide_id,
                    "relevance": relevance,
                    "judgment": {0: "irrelevant_hard_negative", 1: "supporting_slide", 2: "primary_slide"}[relevance],
                    "research_evidence_ids": deepcopy(source_items[(kp_id, slide_id)]["research_evidence_ids"]),
                }
            )
        result["mapping_qrels"] = qrels
    return result
