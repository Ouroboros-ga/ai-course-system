from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import sha256_file, write_json
from src.fixture_io import QUERY_STRATA, load_json
from tools.human_gold_builder import (
    LOW_TEXT_OCR_THRESHOLD,
    OCR_NO_TEXT_STATUS,
    OCR_REVIEW_STATUS,
    SELECTION_ATTESTATION,
    SELECTION_SCHEMA_VERSION,
    HumanGoldBuildError,
    _extract_pptx,
    _validate_selection,
)
from tools.human_gold_candidate import (
    SOURCE_CONTRACTS,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    preflight_authorized_sources,
)
from tools.human_selection_seed_audit import (
    KP_HEADERS,
    PAGE_HEADERS,
    QUERY_HEADERS,
    _read_csv,
)


REVIEW_SCHEMA_VERSION = "product1-graph-retrieval-human-selection-review/0.1"
INTERNAL_USE_POLICY = "smart_course_system_internal_offline_evaluation_no_external_distribution"
SAMPLING_METHOD = "course_variant_even_coverage_v1"
FORBIDDEN_REVIEW_KEYS = {
    "answerable", "answerability", "expected_answerability", "gold", "gold_answer_hint",
    "gold_label", "judgment", "model_answer", "model_recommendation", "rank", "relevance", "score",
}


class HumanSelectionReviewError(ValueError):
    pass


def _stable(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return prefix + hashlib.sha256(payload).hexdigest()[:24]


def _walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, key, child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _discover(source_dir: Path) -> dict[str, tuple[Path, str, list[dict[str, str]]]]:
    found: dict[str, tuple[Path, str, list[dict[str, str]]]] = {}
    for path in sorted(Path(source_dir).glob("*.csv"), key=lambda value: value.name):
        encoding, rows = _read_csv(path)
        headers = set(rows[0]) if rows else set()
        role = None
        if QUERY_HEADERS <= headers:
            role = "query_seed_export"
        elif KP_HEADERS <= headers:
            role = "knowledge_point_export"
        elif PAGE_HEADERS <= headers:
            role = "page_index_export"
        if role:
            if role in found:
                raise HumanSelectionReviewError(f"duplicate_seed_export_role:{role}")
            found[role] = (path, encoding, rows)
    missing = {"query_seed_export", "knowledge_point_export", "page_index_export"} - set(found)
    if missing:
        raise HumanSelectionReviewError(f"seed_exports_missing:{sorted(missing)}")
    return found


def _evenly(rows: list[dict[str, str]], count: int) -> list[dict[str, str]]:
    if count > len(rows):
        raise HumanSelectionReviewError(f"sampling_group_too_small:{count}:{len(rows)}")
    if count == len(rows):
        return rows
    return [rows[(index * len(rows)) // count] for index in range(count)]


def _pending_review() -> dict[str, Any]:
    return {"status": "pending", "selected": None, "reviewed_by": None, "review_note": None}


def _approval_pending(*, evidence_ref: str | None = None) -> dict[str, Any]:
    return {"status": "pending_record_completion", "reviewed_by": None, "evidence_ref": evidence_ref}


def _course_index(page_rows: list[dict[str, str]], source_dir: Path) -> list[dict[str, Any]]:
    by_course: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in page_rows:
        by_course[row["course_id"]].append(row)
    pptx_by_count: dict[int, list[tuple[Path, list[dict[str, Any]]]]] = defaultdict(list)
    for path in sorted(source_dir.glob("*.pptx"), key=lambda value: value.name):
        slides = _extract_pptx(path)
        pptx_by_count[len(slides)].append((path, slides))
    result = []
    for course_id in sorted(by_course):
        rows = by_course[course_id]
        page_count = max(int(row["ppt_page"]) for row in rows)
        matches = pptx_by_count.get(page_count, [])
        if len(matches) != 1:
            raise HumanSelectionReviewError(f"actual_pptx_page_count_mapping_not_unique:{course_id}:{page_count}")
        pptx, slides = matches[0]
        pdf = pptx.with_suffix(".pdf")
        if not pdf.is_file():
            raise HumanSelectionReviewError(f"matching_pdf_missing:{pptx.name}")
        names = {row.get("course_name", "") for row in rows}
        aliases = {row.get("source_file", "") for row in rows}
        if len(names) != 1 or len(aliases) != 1:
            raise HumanSelectionReviewError(f"page_index_course_metadata_not_unique:{course_id}")
        result.append({
            "course_id": course_id,
            "course_name": next(iter(names)),
            "workbook_source_file": next(iter(aliases)),
            "actual_pptx": pptx.name,
            "actual_pdf": pdf.name,
            "page_count": page_count,
            "pptx_sha256": sha256_file(pptx),
            "pdf_sha256": sha256_file(pdf),
            "_slides": slides,
        })
    return result


def _sample_queries(query_rows: list[dict[str, str]], target: int) -> list[dict[str, Any]]:
    if not 60 <= target <= 100:
        raise HumanSelectionReviewError("query_target_must_be_60_to_100")
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in query_rows:
        groups[(row["course_id"], row["query_variant"])].append(row)
    keys = sorted(groups)
    if not keys or target < len(keys):
        raise HumanSelectionReviewError("query_target_smaller_than_course_variant_groups")
    base, remainder = divmod(target, len(keys))
    selected: list[dict[str, Any]] = []
    direct_cycle = ("exact_term", "definition", "cross_language_alias")
    mechanism_cycle = ("formula_or_code", "paraphrase", "multi_hop_relation")
    split_cycle = ("train", "train", "validation", "test")
    for group_index, key in enumerate(keys):
        count = base + (1 if group_index < remainder else 0)
        rows = sorted(groups[key], key=lambda row: row["seed_id"])
        for local_index, row in enumerate(_evenly(rows, count)):
            variant = row["query_variant"]
            if variant == "direct_definition":
                stratum = direct_cycle[local_index % len(direct_cycle)]
            elif variant == "mechanism_application":
                stratum = mechanism_cycle[local_index % len(mechanism_cycle)]
            else:
                stratum = "no_answer"
            selected.append({
                "candidate_query_id": _stable("rqreview_", row["course_id"], row["seed_id"], row["query_text"]),
                "seed_id": row["seed_id"],
                "course_id": row["course_id"],
                "knowledge_point_seed_id": row["knowledge_point_id"],
                "knowledge_point_label": row["knowledge_point"],
                "source_page_range_for_author_review_only": row["ppt_page_range"],
                "text": row["query_text"].strip(),
                "source_variant": variant,
                "suggested_query_type_not_gold": variant,
                "suggested_query_stratum_not_gold": stratum,
                "suggested_split_not_gold": split_cycle[local_index % len(split_cycle)],
                "final_query_type": None,
                "final_query_stratum": None,
                "final_split": None,
                "tags": [],
                "human_review": _pending_review(),
            })
    return sorted(selected, key=lambda row: (row["course_id"], row["candidate_query_id"]))


def _knowledge_points(kp_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for row in sorted(kp_rows, key=lambda value: (value["course_id"], value["knowledge_point_id"])):
        seed_id = row["knowledge_point_id"]
        result.append({
            "candidate_knowledge_point_id": _stable("rkpreview_", row["course_id"], seed_id, row["knowledge_point"]),
            "seed_knowledge_point_id": seed_id,
            "course_id": row["course_id"],
            "canonical_label": row["knowledge_point"].strip(),
            "source_chapter_for_author_review_only": row.get("chapter_range", "").strip() or "UNSPECIFIED",
            "source_page_range_for_author_review_only": row.get("ppt_page_range", "").strip()
                or f"{row['ppt_page_start']}-{row['ppt_page_end']}",
            "suggested_split_not_gold": "validation" if int(hashlib.sha256(seed_id.encode()).hexdigest(), 16) % 2 == 0 else "test",
            "aliases": [],
            "final_chapter_id": None,
            "final_chapter_path": None,
            "final_split": None,
            "human_review": _pending_review(),
        })
    return result


def _chapters(kp_rows: list[dict[str, str]], courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    page_counts = {row["course_id"]: row["page_count"] for row in courses}
    grouped: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in kp_rows:
        grouped[row["course_id"]][row.get("chapter_range", "").strip() or "UNSPECIFIED"].append(row)
    result = []
    for course_id in sorted(grouped):
        groups = []
        for label, rows in grouped[course_id].items():
            groups.append((min(int(row["ppt_page_start"]) for row in rows), label, rows))
        groups.sort(key=lambda value: (value[0], value[1]))
        cursor = 1
        for index, (first_page, label, rows) in enumerate(groups):
            next_page = groups[index + 1][0] if index + 1 < len(groups) else page_counts[course_id] + 1
            end = max(cursor, min(page_counts[course_id], next_page - 1))
            chapter_id = _stable("rchreview_", course_id, label)
            result.append({
                "candidate_chapter_id": chapter_id,
                "course_id": course_id,
                "source_chapter_label": label,
                "suggested_start_slide_not_gold": cursor,
                "suggested_end_slide_not_gold": end,
                "final_start_slide": None,
                "final_end_slide": None,
                "final_chapter_id": None,
                "final_chapter_path": None,
                "human_review": _pending_review(),
            })
            cursor = end + 1
        if cursor <= page_counts[course_id]:
            result[-1]["suggested_end_slide_not_gold"] = page_counts[course_id]
    return result


def _ocr_tasks(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for course in courses:
        for slide in course["_slides"]:
            chars = len("".join(slide["native_lines"]))
            if slide["picture_count"] and chars < LOW_TEXT_OCR_THRESHOLD:
                number = slide["slide_number"]
                result.append({
                    "task_id": _stable("rocrreview_", course["course_id"], number),
                    "course_id": course["course_id"],
                    "slide_number": number,
                    "native_text_chars": chars,
                    "picture_count": slide["picture_count"],
                    "controlled_source_ref": f"controlled-source://{course['course_id']}/pdf?page={number}",
                    "decision": None,
                    "blocks": [],
                    "human_review": _pending_review(),
                })
    return sorted(result, key=lambda row: (row["course_id"], row["slide_number"]))


def prepare_selection_review(source_dir: Path, *, query_target: int = 96) -> dict[str, Any]:
    source_dir = Path(source_dir).resolve()
    discovered = _discover(source_dir)
    query_rows = discovered["query_seed_export"][2]
    kp_rows = discovered["knowledge_point_export"][2]
    page_rows = discovered["page_index_export"][2]
    courses_private = _course_index(page_rows, source_dir)
    courses = []
    for row in courses_private:
        courses.append({key: value for key, value in row.items() if key != "_slides"} | {
            "file_mapping_review": _approval_pending(),
            "redaction_terms": [],
            "redaction_review": _approval_pending(),
            "ocr_provenance": None,
        })
    source_seed_files = []
    for role in sorted(discovered):
        path, encoding, _ = discovered[role]
        source_seed_files.append({"file": path.name, "role": role, "encoding": encoding, "sha256": sha256_file(path)})
    packet = {
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "candidate_id": "human_gold_candidate_v0_1",
        "status": "pending_human_review",
        "internal_use_policy": INTERNAL_USE_POLICY,
        "source_seed_files": source_seed_files,
        "sampling": {"method": SAMPLING_METHOD, "query_target": query_target,
            "seed_hints_excluded": True, "suggestions_are_not_gold": True},
        "source_governance": {
            "authorization": {"status": "pending_record_completion", "authorized_by": None,
                "evidence_ref": "codex-thread://019f68f2-8e32-7c61-a706-bb8d77fd5efe#authorization-attestation-2026-07-16",
                "valid_from": None, "expires_at": None, "no_expiry": None},
            "privacy": {"status": "pending_record_completion", "reviewed_by": None,
                "evidence_ref": "codex-thread://019f68f2-8e32-7c61-a706-bb8d77fd5efe#privacy-attestation-2026-07-16",
                "known_direct_identifiers_present": True,
                "sanitization_plan_ref": "research-report://human_gold_source_ocr_preflight#privacy"},
            "repository_storage_authorized": None,
        },
        "courses": courses,
        "query_candidates": _sample_queries(query_rows, query_target),
        "knowledge_point_candidates": _knowledge_points(kp_rows),
        "chapter_candidates": _chapters(kp_rows, courses),
        "ocr_review_tasks": _ocr_tasks(courses_private),
        "scope_query_candidates": [{
            "candidate_scope_query_id": "scope_review_01", "unavailable_course_id": None,
            "text": None, "final_query_type": None, "final_split": None, "tags": ["scope_not_available"],
            "human_review": _pending_review(),
        }],
        "human_finalization": {"status": "pending", "finalized_by": None,
            "finalized_at": None, "attestation": None},
    }
    validate_selection_review(packet)
    return packet


def validate_selection_review(packet: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if packet.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
        errors.append("review_schema_version_invalid")
    if packet.get("internal_use_policy") != INTERNAL_USE_POLICY:
        errors.append("internal_use_policy_invalid")
    for path, key, _ in _walk(packet):
        if key.casefold() in FORBIDDEN_REVIEW_KEYS:
            errors.append(f"forbidden_seed_or_gold_field:{path}.{key}")
    queries = packet.get("query_candidates", [])
    kps = packet.get("knowledge_point_candidates", [])
    if not isinstance(queries, list) or not 60 <= len(queries) <= 100:
        errors.append("query_candidate_count_invalid")
        queries = []
    if not isinstance(kps, list) or not 40 <= len(kps) <= 80:
        errors.append("knowledge_point_candidate_count_invalid")
        kps = []
    for field, rows, key in (("query", queries, "candidate_query_id"),
        ("knowledge_point", kps, "candidate_knowledge_point_id")):
        ids = [row.get(key) for row in rows if isinstance(row, dict)]
        if len(ids) != len(rows) or len(ids) != len(set(ids)) or any(not value for value in ids):
            errors.append(f"{field}_candidate_ids_invalid")
    suggested = {row.get("suggested_query_stratum_not_gold") for row in queries if isinstance(row, dict)}
    if suggested != QUERY_STRATA:
        errors.append("suggested_query_strata_incomplete")
    course_ids = {row.get("course_id") for row in packet.get("courses", []) if isinstance(row, dict)}
    if not 3 <= len(course_ids) <= 5 or None in course_ids:
        errors.append("course_ids_invalid")
    for collection in (queries, kps, packet.get("chapter_candidates", []), packet.get("ocr_review_tasks", [])):
        if any(not isinstance(row, dict) or row.get("course_id") not in course_ids for row in collection):
            errors.append("review_record_course_scope_invalid")
    if errors:
        raise HumanSelectionReviewError(";".join(sorted(set(errors))))
    return {"status": packet.get("status"), "valid": True,
        "counts": {"courses": len(course_ids), "queries": len(queries), "knowledge_points": len(kps),
            "chapters": len(packet.get("chapter_candidates", [])), "ocr_review_tasks": len(packet.get("ocr_review_tasks", []))}}


def _require_reviewed(rows: list[dict[str, Any]], *, label: str) -> None:
    for row in rows:
        review = row.get("human_review", {})
        if review.get("status") not in {"approved", "rejected"} or not isinstance(review.get("selected"), bool) or not review.get("reviewed_by"):
            raise HumanSelectionReviewError(f"{label}_not_fully_human_reviewed:{row}")
        if review["status"] == "approved" and review["selected"] is not True:
            raise HumanSelectionReviewError(f"{label}_approved_must_be_selected")
        if review["status"] == "rejected" and review["selected"] is not False:
            raise HumanSelectionReviewError(f"{label}_rejected_must_not_be_selected")


def finalize_selection_review(packet: dict[str, Any], source_dir: Path,
    source_manifest_output: Path, selection_output: Path) -> dict[str, Any]:
    validate_selection_review(packet)
    source_dir = Path(source_dir).resolve()
    source_manifest_output = Path(source_manifest_output).resolve()
    if source_manifest_output.parent != source_dir:
        raise HumanSelectionReviewError("source_manifest_must_be_written_inside_source_bundle")
    finalization = packet.get("human_finalization", {})
    if finalization.get("status") != "approved" or finalization.get("attestation") != SELECTION_ATTESTATION:
        raise HumanSelectionReviewError("human_finalization_attestation_missing")
    for field in ("finalized_by", "finalized_at"):
        if not finalization.get(field):
            raise HumanSelectionReviewError(f"human_finalization_{field}_missing")
    governance = packet.get("source_governance", {})
    authorization, privacy = governance.get("authorization", {}), governance.get("privacy", {})
    if authorization.get("status") != "approved" or not all(authorization.get(field) for field in ("authorized_by", "evidence_ref", "valid_from")):
        raise HumanSelectionReviewError("authorization_record_incomplete")
    if not authorization.get("expires_at") and authorization.get("no_expiry") is not True:
        raise HumanSelectionReviewError("authorization_validity_missing")
    if privacy.get("status") != "approved" or not all(privacy.get(field) for field in ("reviewed_by", "evidence_ref", "sanitization_plan_ref")):
        raise HumanSelectionReviewError("privacy_record_incomplete")
    if not isinstance(privacy.get("known_direct_identifiers_present"), bool):
        raise HumanSelectionReviewError("privacy_identifier_presence_missing")
    if governance.get("repository_storage_authorized") is not True:
        raise HumanSelectionReviewError("repository_storage_not_authorized")

    courses = packet["courses"]
    for course in courses:
        for field in ("file_mapping_review", "redaction_review"):
            review = course.get(field, {})
            if review.get("status") != "approved" or not review.get("reviewed_by") or not review.get("evidence_ref"):
                raise HumanSelectionReviewError(f"{course['course_id']}:{field}_incomplete")

    queries = packet["query_candidates"]
    kps = packet["knowledge_point_candidates"]
    chapters = packet["chapter_candidates"]
    ocr_tasks = packet["ocr_review_tasks"]
    scopes = packet["scope_query_candidates"]
    for rows, label in ((queries, "query"), (kps, "knowledge_point"), (chapters, "chapter"),
        (ocr_tasks, "ocr_task"), (scopes, "scope_query")):
        _require_reviewed(rows, label=label)
    selected_queries = [row for row in queries if row["human_review"]["selected"]]
    selected_kps = [row for row in kps if row["human_review"]["selected"]]
    selected_chapters = [row for row in chapters if row["human_review"]["selected"]]
    selected_scopes = [row for row in scopes if row["human_review"]["selected"]]
    if not 60 <= len(selected_queries) <= 100:
        raise HumanSelectionReviewError("selected_query_count_invalid")
    if {row.get("final_query_stratum") for row in selected_queries} != QUERY_STRATA:
        raise HumanSelectionReviewError("selected_queries_do_not_cover_all_strata")
    for row in selected_queries:
        if not row.get("final_query_type") or row.get("final_split") not in {"train", "validation", "test"}:
            raise HumanSelectionReviewError(f"selected_query_final_fields_missing:{row['candidate_query_id']}")
    if not 40 <= len(selected_kps) <= 80:
        raise HumanSelectionReviewError("selected_knowledge_point_count_invalid")
    for row in selected_kps:
        if not row.get("final_chapter_id") or not row.get("final_chapter_path") or row.get("final_split") not in {"validation", "test"}:
            raise HumanSelectionReviewError(f"selected_kp_final_fields_missing:{row['candidate_knowledge_point_id']}")
    if not selected_scopes:
        raise HumanSelectionReviewError("selected_scope_query_missing")
    course_ids = {row["course_id"] for row in courses}
    for row in selected_scopes:
        if not row.get("unavailable_course_id") or row["unavailable_course_id"] in course_ids or not row.get("text") or not row.get("final_query_type") or row.get("final_split") not in {"train", "validation", "test"}:
            raise HumanSelectionReviewError("selected_scope_query_invalid")

    chapter_by_course: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_chapters:
        if not all(row.get(field) for field in ("final_start_slide", "final_end_slide", "final_chapter_id", "final_chapter_path")):
            raise HumanSelectionReviewError(f"selected_chapter_final_fields_missing:{row['candidate_chapter_id']}")
        chapter_by_course[row["course_id"]].append(row)
    for course in courses:
        cid, cursor = course["course_id"], 1
        rows = sorted(chapter_by_course[cid], key=lambda row: row["final_start_slide"])
        for row in rows:
            if row["final_start_slide"] != cursor or row["final_end_slide"] < cursor or row["final_chapter_path"][0] != cid:
                raise HumanSelectionReviewError(f"chapter_coverage_invalid:{cid}")
            cursor = row["final_end_slide"] + 1
        if cursor != course["page_count"] + 1:
            raise HumanSelectionReviewError(f"chapter_coverage_incomplete:{cid}")

    ocr_by_course: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ocr_tasks:
        if row["human_review"]["selected"] is not True or row.get("decision") not in {"use_reviewed_ocr", "no_relevant_text"}:
            raise HumanSelectionReviewError(f"ocr_task_decision_missing:{row['task_id']}")
        if row["decision"] == "use_reviewed_ocr" and not row.get("blocks"):
            raise HumanSelectionReviewError(f"ocr_blocks_missing:{row['task_id']}")
        if row["decision"] == "no_relevant_text" and row.get("blocks"):
            raise HumanSelectionReviewError(f"ocr_no_text_has_blocks:{row['task_id']}")
        ocr_by_course[row["course_id"]].append(row)

    auth_payload = {"status": "approved", "authorized_by": authorization["authorized_by"],
        "purpose": "human_gold_research_evaluation", "evidence_ref": authorization["evidence_ref"],
        "valid_from": authorization["valid_from"]}
    if authorization.get("expires_at"):
        auth_payload["expires_at"] = authorization["expires_at"]
    else:
        auth_payload["no_expiry"] = True
    source_manifest = {"source_manifest_schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "candidate_id": "human_gold_candidate_v0_1", "source_contracts": SOURCE_CONTRACTS,
        "repository_storage_authorized": True, "contains_student_records": False, "courses": []}
    for course in courses:
        cid = course["course_id"]
        mapping = course["file_mapping_review"]
        source_manifest["courses"].append({"course_id": cid, "page_count": course["page_count"],
            "page_pair_review": {"status": "approved", "reviewed_by": mapping["reviewed_by"],
                "evidence_ref": mapping["evidence_ref"], "pptx_pdf_same_page_count": True},
            "authorization": auth_payload,
            "privacy_review": {"status": "approved", "reviewed_by": privacy["reviewed_by"],
                "evidence_ref": privacy["evidence_ref"], "raw_material_access_approved": True,
                "candidate_must_be_deidentified": True,
                "known_direct_identifiers_present": privacy["known_direct_identifiers_present"],
                "sanitization_plan_ref": privacy["sanitization_plan_ref"]},
            "files": [{"role": "pptx_source", "path": course["actual_pptx"], "sha256": course["pptx_sha256"]},
                {"role": "pdf_reference", "path": course["actual_pdf"], "sha256": course["pdf_sha256"]}]})
    write_json(source_manifest_output, source_manifest)
    preflight = preflight_authorized_sources(source_manifest_output)

    selection_courses = []
    for course in courses:
        cid = course["course_id"]
        selected_course_queries = [row for row in selected_queries if row["course_id"] == cid]
        selected_course_kps = [row for row in selected_kps if row["course_id"] == cid]
        selected_course_chapters = sorted(chapter_by_course[cid], key=lambda row: row["final_start_slide"])
        ocr_records = []
        for row in sorted(ocr_by_course[cid], key=lambda value: value["slide_number"]):
            ocr_records.append({"slide_number": row["slide_number"],
                "review_status": OCR_REVIEW_STATUS if row["decision"] == "use_reviewed_ocr" else OCR_NO_TEXT_STATUS,
                "blocks": row["blocks"]})
        record = {"course_id": cid, "redaction_terms": course["redaction_terms"],
            "redaction_terms_reviewed_by": course["redaction_review"]["reviewed_by"],
            "redaction_evidence_ref": course["redaction_review"]["evidence_ref"],
            "slide_chapter_ranges": [{"start_slide": row["final_start_slide"], "end_slide": row["final_end_slide"],
                "chapter_id": row["final_chapter_id"], "chapter_path": row["final_chapter_path"]}
                for row in selected_course_chapters],
            "ocr_records": ocr_records,
            "queries": [{"text": row["text"], "query_type": row["final_query_type"],
                "query_stratum": row["final_query_stratum"], "split": row["final_split"], "tags": row["tags"]}
                for row in selected_course_queries],
            "knowledge_points": [{"canonical_label": row["canonical_label"], "aliases": row["aliases"],
                "chapter_id": row["final_chapter_id"], "chapter_path": row["final_chapter_path"],
                "split": row["final_split"]} for row in selected_course_kps]}
        if any(row["decision"] == "use_reviewed_ocr" for row in ocr_by_course[cid]):
            if not course.get("ocr_provenance"):
                raise HumanSelectionReviewError(f"ocr_provenance_missing:{cid}")
            record["ocr_provenance"] = course["ocr_provenance"]
        selection_courses.append(record)
    selection = {"selection_schema_version": SELECTION_SCHEMA_VERSION,
        "candidate_id": "human_gold_candidate_v0_1", "source_manifest_sha256": preflight["source_manifest_sha256"],
        "created_at": finalization["finalized_at"], "created_by_member_id": finalization["finalized_by"],
        "attestation": SELECTION_ATTESTATION,
        "candidate_privacy_plan": {"status": "approved", "reviewed_by": privacy["reviewed_by"],
            "evidence_ref": privacy["evidence_ref"], "candidate_must_be_deidentified": True},
        "courses": selection_courses,
        "scope_queries": [{"course_id": row["unavailable_course_id"], "text": row["text"],
            "query_type": row["final_query_type"], "query_stratum": "no_answer", "split": row["final_split"],
            "tags": row["tags"]} for row in selected_scopes]}
    _validate_selection(selection, preflight["source_manifest_sha256"], course_ids)
    write_json(selection_output, selection)
    return {"status": "human_selection_ready_for_candidate_build", "source_manifest": str(source_manifest_output),
        "selection": str(Path(selection_output).resolve()), "source_manifest_sha256": preflight["source_manifest_sha256"],
        "counts": {"courses": len(courses), "queries": len(selected_queries), "knowledge_points": len(selected_kps),
            "ocr_review_tasks": len(ocr_tasks)}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or finalize B-G0b human selection review")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("source_dir", type=Path)
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--query-target", type=int, default=96)
    validate = sub.add_parser("validate")
    validate.add_argument("review", type=Path)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("review", type=Path)
    finalize.add_argument("source_dir", type=Path)
    finalize.add_argument("source_manifest_output", type=Path)
    finalize.add_argument("selection_output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            packet = prepare_selection_review(args.source_dir, query_target=args.query_target)
            write_json(args.output, packet)
            result = validate_selection_review(packet) | {"output": str(args.output.resolve())}
        elif args.command == "validate":
            result = validate_selection_review(load_json(args.review))
        else:
            result = finalize_selection_review(load_json(args.review), args.source_dir,
                args.source_manifest_output, args.selection_output)
    except (HumanSelectionReviewError, HumanGoldBuildError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reasons": str(exc).split(";")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
