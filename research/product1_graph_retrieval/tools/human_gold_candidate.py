"""Fail-closed preparation helpers for B-G0b human gold candidates.

This module prepares and validates metadata and blind packets.  It never
creates labels, asserts that a member ID belongs to a human, or releases B-R1.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


CANDIDATE_SCHEMA_VERSION = "product1-graph-retrieval-human-gold-candidate/0.1"
SOURCE_MANIFEST_SCHEMA_VERSION = "product1-graph-retrieval-authorized-sources/1.0"
PROTOCOL_VERSION = "product1-graph-retrieval-human-annotation/1.0"

SOURCE_CONTRACTS = {
    "document_ir": "document-ir/1.0",
    "evidence": "evidence/1.0",
    "citation": "citation/1.0",
    "education_graph": "edu-graph/1.0",
}

PUBLIC_INPUT_FILES = {
    "source_blocks.jsonl",
    "evidence.jsonl",
    "corpus.jsonl",
    "queries.jsonl",
    "knowledge_points.jsonl",
    "slides.jsonl",
    "splits.json",
}
GOLD_ONLY_FILES = {
    "retrieval_query_labels.jsonl",
    "retrieval_qrels.jsonl",
    "mapping_qrels.jsonl",
    "annotation/retrieval_A.json",
    "annotation/retrieval_B.json",
    "annotation/mapping_A.json",
    "annotation/mapping_B.json",
    "annotation/retrieval_adjudication.json",
    "annotation/mapping_adjudication.json",
}

FORBIDDEN_PACKET_KEYS = {
    "score",
    "rank",
    "gold",
    "gold_label",
    "model_answer",
    "model_recommendation",
    "recommended_label",
    "suggested_label",
    "automatic_answer",
    "retrieval_score",
    "mapping_score",
}
DIRECT_IDENTIFIER_KEYS = {
    "name",
    "student_name",
    "student_id",
    "student_number",
    "phone",
    "mobile",
    "email",
    "id_card",
    "identity_number",
}

PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
STUDENT_NUMBER_PATTERN = re.compile(
    r"(?:学号|学生编号|student\s*(?:id|number))\s*[:：#-]?\s*[A-Z0-9_-]{4,}",
    re.IGNORECASE,
)
IDENTITY_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


class HumanGoldPreparationError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise HumanGoldPreparationError(f"source_manifest_unreadable:{path}") from exc
    except json.JSONDecodeError as exc:
        raise HumanGoldPreparationError(f"source_manifest_invalid_json:{path}") from exc
    if not isinstance(value, dict):
        raise HumanGoldPreparationError(f"expected JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, str(key), child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def validate_source_contracts(value: Any) -> None:
    if value != SOURCE_CONTRACTS:
        raise HumanGoldPreparationError(
            f"source_contracts must exactly equal frozen contracts: {SOURCE_CONTRACTS}"
        )


def scan_direct_identifiers(value: Any) -> list[str]:
    findings: list[str] = []
    for path, key, child in _walk(value):
        normalized_key = key.casefold()
        if normalized_key in DIRECT_IDENTIFIER_KEYS and child not in (None, "", [], {}):
            findings.append(f"{path}.{key}:direct_identifier_key")
        if (
            normalized_key.endswith("_name")
            and normalized_key not in {"course_name", "chapter_name", "section_name"}
            and child not in (None, "", [], {})
        ):
            findings.append(f"{path}.{key}:person_name_key")
        machine_identifier = (
            normalized_key.endswith(("_id", "_ids", "_sha256"))
            or normalized_key in {
                "block_id", "citation_key", "version_ref", "controlled_source_ref",
                "research_evidence_id", "research_chunk_id", "research_slide_id",
                "research_query_id", "research_knowledge_point_id",
            }
        )
        if isinstance(child, str) and not machine_identifier:
            if PHONE_PATTERN.search(child):
                findings.append(f"{path}.{key}:phone_pattern")
            if EMAIL_PATTERN.search(child):
                findings.append(f"{path}.{key}:email_pattern")
            if STUDENT_NUMBER_PATTERN.search(child):
                findings.append(f"{path}.{key}:student_number_pattern")
            if IDENTITY_CARD_PATTERN.search(child):
                findings.append(f"{path}.{key}:identity_card_pattern")
    return findings


def preflight_authorized_sources(source_manifest_path: Path) -> dict[str, Any]:
    """Validate authorization, privacy attestations, formats, and file hashes."""

    source_manifest_path = Path(source_manifest_path)
    manifest = _load_json(source_manifest_path)
    errors: list[str] = []
    if manifest.get("source_manifest_schema_version") != SOURCE_MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported_source_manifest_schema")
    if manifest.get("candidate_id") != "human_gold_candidate_v0_1":
        errors.append("candidate_id_must_be_human_gold_candidate_v0_1")
    try:
        validate_source_contracts(manifest.get("source_contracts"))
    except HumanGoldPreparationError:
        errors.append("source_contracts_not_frozen")

    courses = manifest.get("courses")
    if not isinstance(courses, list) or not 3 <= len(courses) <= 5:
        errors.append("course_count_must_be_3_to_5")
        courses = []
    valid_courses = [row for row in courses if isinstance(row, dict)]
    if len(valid_courses) != len(courses):
        errors.append("course_records_must_be_objects")
    courses = valid_courses
    course_ids = [row.get("course_id") for row in courses]
    if len(course_ids) != len(set(course_ids)) or any(not value for value in course_ids):
        errors.append("course_ids_must_be_nonempty_and_unique")

    base = source_manifest_path.parent
    checked_files = 0
    for course in courses:
        course_id = course.get("course_id", "<missing>")
        page_count = course.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
            errors.append(f"{course_id}:page_count_invalid")
        page_pair = course.get("page_pair_review", {})
        if page_pair.get("status") != "approved" or page_pair.get("pptx_pdf_same_page_count") is not True:
            errors.append(f"{course_id}:page_pair_not_approved")
        for field in ("reviewed_by", "evidence_ref"):
            if not page_pair.get(field):
                errors.append(f"{course_id}:page_pair_{field}_missing")
        authorization = course.get("authorization", {})
        if authorization.get("status") != "approved":
            errors.append(f"{course_id}:authorization_not_approved")
        for field in ("authorized_by", "purpose", "evidence_ref", "valid_from"):
            if not authorization.get(field):
                errors.append(f"{course_id}:authorization_{field}_missing")
        if authorization.get("purpose") != "human_gold_research_evaluation":
            errors.append(f"{course_id}:authorization_purpose_mismatch")
        if not authorization.get("expires_at") and authorization.get("no_expiry") is not True:
            errors.append(f"{course_id}:authorization_expiry_missing")

        privacy = course.get("privacy_review", {})
        if privacy.get("status") != "approved":
            errors.append(f"{course_id}:privacy_review_not_approved")
        for field in ("reviewed_by", "evidence_ref", "sanitization_plan_ref"):
            if not privacy.get(field):
                errors.append(f"{course_id}:privacy_{field}_missing")
        if privacy.get("raw_material_access_approved") is not True:
            errors.append(f"{course_id}:raw_material_access_not_approved")
        if privacy.get("candidate_must_be_deidentified") is not True:
            errors.append(f"{course_id}:candidate_deidentification_not_required")
        if not isinstance(privacy.get("known_direct_identifiers_present"), bool):
            errors.append(f"{course_id}:known_direct_identifiers_presence_not_declared")

        files = course.get("files")
        required_roles = {"pptx_source", "pdf_reference"}
        expected_suffixes = {"pptx_source": ".pptx", "pdf_reference": ".pdf"}
        if not isinstance(files, list):
            errors.append(f"{course_id}:files_missing")
            continue
        valid_files = [row for row in files if isinstance(row, dict)]
        if len(valid_files) != len(files):
            errors.append(f"{course_id}:file_records_must_be_objects")
        files = valid_files
        role_list = [row.get("role") for row in files]
        roles = set(role_list)
        for role in sorted(required_roles - roles):
            errors.append(f"{course_id}:required_file_role_missing:{role}")
        for role in sorted(roles - required_roles, key=str):
            errors.append(f"{course_id}:unsupported_file_role:{role}")
        if len(role_list) != len(roles):
            errors.append(f"{course_id}:duplicate_file_roles")
        for record in files:
            role = record.get("role")
            relative = record.get("path")
            expected_hash = record.get("sha256")
            if not relative or not expected_hash:
                errors.append(f"{course_id}:file_path_or_hash_missing")
                continue
            path = (base / relative).resolve()
            if base.resolve() not in path.parents:
                errors.append(f"{course_id}:file_outside_source_bundle:{relative}")
                continue
            if not path.is_file():
                errors.append(f"{course_id}:file_missing:{relative}")
                continue
            expected_suffix = expected_suffixes.get(role)
            if expected_suffix is None or path.suffix.casefold() != expected_suffix:
                errors.append(f"{course_id}:file_extension_mismatch:{role}:{relative}")
                continue
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                errors.append(f"{course_id}:file_hash_format_invalid:{relative}")
                continue
            if _sha256_file(path) != expected_hash:
                errors.append(f"{course_id}:file_hash_mismatch:{relative}")
                continue
            checked_files += 1
            if path.suffix.casefold() in {".json", ".jsonl"}:
                text = path.read_text(encoding="utf-8")
                records = [text] if path.suffix.casefold() == ".json" else text.splitlines()
                for line_number, line in enumerate(records, 1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        errors.append(f"{course_id}:invalid_json:{relative}:{line_number}")
                        continue
                    for finding in scan_direct_identifiers(value):
                        errors.append(f"{course_id}:pii:{relative}:{finding}")

    if manifest.get("repository_storage_authorized") is not True:
        errors.append("repository_storage_not_authorized")
    if manifest.get("contains_student_records") is not False:
        errors.append("student_records_must_not_be_present")
    if errors:
        raise HumanGoldPreparationError(";".join(errors))
    return {
        "status": "authorized_inputs_ready",
        "candidate_id": manifest["candidate_id"],
        "course_count": len(courses),
        "checked_files": checked_files,
        "source_manifest_sha256": _sha256_file(source_manifest_path),
    }


def validate_candidate_manifest(manifest: dict[str, Any]) -> None:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        raise HumanGoldPreparationError("candidate_manifest_must_be_object")
    if manifest.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
        errors.append("candidate_schema_version_invalid")
    if manifest.get("candidate_id") != "human_gold_candidate_v0_1":
        errors.append("candidate_id_invalid")
    if manifest.get("fixture_id") != "human_gold_candidate_v0_1":
        errors.append("fixture_id_invalid")
    if manifest.get("research_sidecar_schema_version") != (
        "product1-graph-retrieval-research-sidecar/1.0"
    ):
        errors.append("research_sidecar_schema_version_invalid")
    if not manifest.get("created_at"):
        errors.append("created_at_missing")
    if manifest.get("dataset_level") != "human_gold_candidate":
        errors.append("dataset_level_must_be_human_gold_candidate")
    if manifest.get("contains_personal_data") is not False:
        errors.append("contains_personal_data_must_be_false")
    content_hash = manifest.get("candidate_content_sha256")
    if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        errors.append("candidate_content_sha256_invalid")

    course_ids = manifest.get("course_ids")
    if not isinstance(course_ids, list) or not 3 <= len(course_ids) <= 5:
        errors.append("course_count_must_be_3_to_5")
        course_ids = []
    if any(not isinstance(value, str) or not value for value in course_ids):
        errors.append("course_ids_must_be_nonempty_strings")
    if len(course_ids) != len(set(value for value in course_ids if isinstance(value, str))):
        errors.append("course_ids_must_be_unique")

    try:
        validate_source_contracts(manifest.get("source_contracts"))
    except HumanGoldPreparationError:
        errors.append("source_contracts_invalid")

    gold = manifest.get("gold")
    if not isinstance(gold, dict):
        errors.append("gold_must_be_object")
        gold = {}
    gold_status = gold.get("status")
    if gold_status not in {
        "pending_human_annotation",
        "pending_adjudication",
        "pending_governance",
        "human_adjudicated_candidate",
    }:
        errors.append("gold_status_invalid")
    if gold.get("eligible_for_algorithm_comparison") is not False:
        errors.append("candidate_must_not_be_algorithm_eligible")

    access = manifest.get("access_policy")
    if not isinstance(access, dict):
        errors.append("access_policy_must_be_object")
        access = {}
    public_inputs = access.get("public_index_inputs")
    gold_only = access.get("gold_only")
    if not isinstance(public_inputs, list) or any(
        not isinstance(value, str) for value in public_inputs
    ):
        errors.append("public_input_partition_invalid")
        public_set: set[str] = set()
    else:
        public_set = set(public_inputs)
        if public_set != PUBLIC_INPUT_FILES or len(public_inputs) != len(public_set):
            errors.append("public_input_partition_invalid")
    if not isinstance(gold_only, list) or any(not isinstance(value, str) for value in gold_only):
        errors.append("gold_only_partition_invalid")
        gold_set: set[str] = set()
    else:
        gold_set = set(gold_only)
        if gold_set != GOLD_ONLY_FILES or len(gold_only) != len(gold_set):
            errors.append("gold_only_partition_invalid")
    if public_set & gold_set:
        errors.append("public_gold_partition_overlap")
    if access.get("gold_access") != "evaluation_only_after_frozen_run":
        errors.append("gold_access_policy_invalid")

    files = manifest.get("files")
    if not isinstance(files, dict):
        errors.append("files_must_be_hash_mapping")
        files = {}
    missing_public_files = PUBLIC_INPUT_FILES - set(files)
    if missing_public_files:
        errors.append(f"public_file_hashes_missing:{sorted(missing_public_files)}")
    unknown_files = set(files) - (PUBLIC_INPUT_FILES | GOLD_ONLY_FILES)
    if unknown_files:
        errors.append(f"unknown_manifest_files:{sorted(unknown_files)}")
    for name, digest in files.items():
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            errors.append(f"file_hash_invalid:{name}")
    label_files = {
        "retrieval_query_labels.jsonl",
        "retrieval_qrels.jsonl",
        "mapping_qrels.jsonl",
    }
    if gold_status == "pending_human_annotation" and set(files) & label_files:
        errors.append("pending_candidate_must_not_contain_gold_labels")

    authorization = manifest.get("source_authorization")
    if not isinstance(authorization, dict):
        errors.append("source_authorization_must_be_object")
        authorization = {}
    source_hash = authorization.get("source_manifest_sha256")
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        errors.append("source_authorization_source_manifest_sha256_invalid")
    for field in ("authorization_record_ref", "privacy_review_ref"):
        if not authorization.get(field):
            errors.append(f"source_authorization_{field}_missing")
    if errors:
        raise HumanGoldPreparationError(";".join(errors))

def validate_blind_packet(packet: dict[str, Any]) -> None:
    errors: list[str] = []
    if packet.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("protocol_version_invalid")
    if packet.get("candidate_id") != "human_gold_candidate_v0_1":
        errors.append("candidate_id_invalid")
    if not packet.get("source_manifest_sha256"):
        errors.append("source_manifest_sha256_missing")
    try:
        validate_source_contracts(packet.get("source_contracts"))
    except HumanGoldPreparationError:
        errors.append("source_contracts_invalid")
    annotator = packet.get("annotator", {})
    if annotator.get("role") not in {"A", "B"}:
        errors.append("annotator_role_must_be_A_or_B")
    if not annotator.get("member_id"):
        errors.append("annotator_member_id_missing")
    if annotator.get("attestation") != "PENDING_HUMAN_COMPLETION":
        errors.append("prepared_packet_must_have_pending_attestation")
    if annotator.get("identity_not_verified_by_tool") is not True:
        errors.append("identity_must_remain_explicitly_unverified")

    for item in packet.get("items", []):
        item_course = item.get("course_id")
        for candidate in item.get("candidates", []):
            if candidate.get("course_id") != item_course:
                errors.append(f"candidate_course_scope_mismatch:{item_course}")
            if packet.get("task") == "mapping":
                if not candidate.get("controlled_source_ref"):
                    errors.append("mapping_controlled_source_ref_missing")
                if candidate.get("requires_visual_review") is not True:
                    errors.append("mapping_visual_review_flag_missing")
    for path, key, value in _walk(packet):
        if key.casefold() in FORBIDDEN_PACKET_KEYS:
            errors.append(f"forbidden_packet_field:{path}.{key}")
        if key in {"answerability", "relevance", "judgment", "final_value", "needs_adjudication"} and value not in (
            None,
            "",
        ):
            errors.append(f"prepopulated_label:{path}.{key}")
    if errors:
        raise HumanGoldPreparationError(";".join(errors))


def enrich_blind_packet(
    packet: dict[str, Any],
    *,
    manifest: dict[str, Any],
    role: str,
    member_id: str,
) -> dict[str, Any]:
    validate_candidate_manifest(manifest)
    packet = json.loads(json.dumps(packet, ensure_ascii=False))
    packet.update(
        {
            "candidate_id": manifest["candidate_id"],
            "protocol_version": PROTOCOL_VERSION,
            "source_manifest_sha256": manifest["source_authorization"][
                "source_manifest_sha256"
            ],
            "source_contracts": SOURCE_CONTRACTS,
        }
    )
    packet["annotator"] = {
        "member_id": member_id,
        "role": role,
        "kind": "human_team_member",
        "attestation": "PENDING_HUMAN_COMPLETION",
        "identity_not_verified_by_tool": True,
    }
    for item in packet.get("items", []):
        if packet.get("task") == "retrieval":
            item["needs_adjudication"] = None
        for candidate in item.get("candidates", []):
            candidate["course_id"] = item.get("course_id")
            candidate["needs_adjudication"] = None
            if packet.get("task") == "mapping":
                candidate["controlled_source_ref"] = (
                    f"controlled-source://{item.get('course_id')}/pdf?page={candidate.get('slide_number')}"
                )
                candidate["requires_visual_review"] = True
                candidate["source_text_is_not_visual_ground_truth"] = True
    validate_blind_packet(packet)
    return packet


def validate_annotation_pair_metadata(
    left: dict[str, Any], right: dict[str, Any]
) -> None:
    """Validate candidate provenance before comparing completed human bundles."""

    errors: list[str] = []
    left_annotator = left.get("annotator", {})
    right_annotator = right.get("annotator", {})
    roles = {left_annotator.get("role"), right_annotator.get("role")}
    if roles != {"A", "B"}:
        errors.append("completed_bundles_must_have_roles_A_and_B")
    if any(
        annotator.get("identity_not_verified_by_tool") is not True
        for annotator in (left_annotator, right_annotator)
    ):
        errors.append("tool_must_not_claim_human_identity_verification")
    for field in (
        "candidate_id", "protocol_version", "source_manifest_sha256", "source_contracts"
    ):
        if left.get(field) != right.get(field):
            errors.append(f"annotation_pair_{field}_mismatch")
    if left.get("candidate_id") != "human_gold_candidate_v0_1":
        errors.append("candidate_id_invalid")
    if left.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("protocol_version_invalid")
    try:
        validate_source_contracts(left.get("source_contracts"))
    except HumanGoldPreparationError:
        errors.append("source_contracts_invalid")
    left_id = left.get("annotator", {}).get("member_id")
    right_id = right.get("annotator", {}).get("member_id")
    if not left_id or not right_id or left_id == right_id:
        errors.append("two_distinct_member_ids_required")
    if errors:
        raise HumanGoldPreparationError(";".join(errors))


def enrich_adjudication_packet(
    packet: dict[str, Any], *, left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    validate_annotation_pair_metadata(left, right)
    packet = json.loads(json.dumps(packet, ensure_ascii=False))
    packet.update(
        {
            "candidate_id": left["candidate_id"],
            "protocol_version": left["protocol_version"],
            "source_manifest_sha256": left["source_manifest_sha256"],
            "source_contracts": SOURCE_CONTRACTS,
        }
    )
    packet["annotator"].update(
        {"role": "adjudicator", "identity_not_verified_by_tool": True}
    )
    return packet


def validate_adjudication_metadata(
    adjudication: dict[str, Any], *, left: dict[str, Any], right: dict[str, Any]
) -> None:
    validate_annotation_pair_metadata(left, right)
    errors: list[str] = []
    for field in (
        "candidate_id", "protocol_version", "source_manifest_sha256", "source_contracts"
    ):
        if adjudication.get(field) != left.get(field):
            errors.append(f"adjudication_{field}_mismatch")
    annotator = adjudication.get("annotator", {})
    if annotator.get("role") != "adjudicator":
        errors.append("adjudicator_role_invalid")
    if annotator.get("identity_not_verified_by_tool") is not True:
        errors.append("tool_must_not_claim_adjudicator_identity_verification")
    member_id = annotator.get("member_id")
    source_ids = {
        left.get("annotator", {}).get("member_id"),
        right.get("annotator", {}).get("member_id"),
    }
    if not member_id or member_id in source_ids:
        errors.append("third_distinct_adjudicator_required")
    if errors:
        raise HumanGoldPreparationError(";".join(errors))

def _candidate_label_entries(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    task = bundle.get("task")
    for item in bundle.get("items", []):
        if task == "retrieval":
            query_id = item.get("research_query_id")
            key = f"answerability|{query_id}"
            entries[key] = {
                "value": item.get("answerability"),
                "needs_adjudication": item.get("needs_adjudication"),
            }
            for candidate in item.get("candidates", []):
                evidence_id = candidate.get("research_evidence_id")
                key = f"retrieval|{query_id}|{evidence_id}"
                entries[key] = {
                    "value": candidate.get("relevance"),
                    "needs_adjudication": candidate.get("needs_adjudication"),
                }
        elif task == "mapping":
            knowledge_point_id = item.get("research_knowledge_point_id")
            for candidate in item.get("candidates", []):
                slide_id = candidate.get("research_slide_id")
                key = f"mapping|{knowledge_point_id}|{slide_id}"
                entries[key] = {
                    "value": candidate.get("relevance"),
                    "needs_adjudication": candidate.get("needs_adjudication"),
                }
        else:
            raise HumanGoldPreparationError("candidate_bundle_task_invalid")
    invalid = [
        key
        for key, value in entries.items()
        if value.get("needs_adjudication") not in {True, False}
    ]
    if invalid:
        raise HumanGoldPreparationError(
            f"completed_candidate_needs_adjudication_boolean_required:{sorted(invalid)}"
        )
    return entries


def augment_candidate_comparison(
    comparison: dict[str, Any], *, left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    """Escalate every uncertain label even when A and B chose the same value."""

    validate_annotation_pair_metadata(left, right)
    left_entries = _candidate_label_entries(left)
    right_entries = _candidate_label_entries(right)
    if set(left_entries) != set(right_entries):
        raise HumanGoldPreparationError("candidate_annotation_key_sets_differ")
    result = json.loads(json.dumps(comparison, ensure_ascii=False))
    existing = {item.get("key") for item in result.get("items", [])}
    label_disagreements = len(existing)
    uncertainty_keys = {
        key
        for key in left_entries
        if left_entries[key]["needs_adjudication"]
        or right_entries[key]["needs_adjudication"]
    }
    for key in sorted(uncertainty_keys - existing):
        result.setdefault("items", []).append(
            {
                "key": key,
                "left_value": left_entries[key]["value"],
                "right_value": right_entries[key]["value"],
                "final_value": None,
                "reason": "uncertainty_escalation",
            }
        )
    result["items"].sort(key=lambda item: item["key"])
    agreement = result.setdefault("agreement", {})
    agreement["label_disagreements"] = label_disagreements
    agreement["uncertainty_escalations"] = len(uncertainty_keys)
    agreement["adjudication_required"] = len(result["items"])
    return result


def _set_candidate_label(bundle: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split("|")
    if parts[0] == "answerability":
        for item in bundle["items"]:
            if item.get("research_query_id") == parts[1]:
                item["answerability"] = value
                return
    elif parts[0] == "retrieval":
        judgments = {0: "not_relevant", 1: "partial_support", 2: "direct_support"}
        for item in bundle["items"]:
            if item.get("research_query_id") == parts[1]:
                for candidate in item.get("candidates", []):
                    if candidate.get("research_evidence_id") == parts[2]:
                        candidate["relevance"] = value
                        candidate["judgment"] = judgments[value]
                        return
    elif parts[0] == "mapping":
        judgments = {0: "irrelevant_hard_negative", 1: "supporting_slide", 2: "primary_slide"}
        for item in bundle["items"]:
            if item.get("research_knowledge_point_id") == parts[1]:
                for candidate in item.get("candidates", []):
                    if candidate.get("research_slide_id") == parts[2]:
                        candidate["relevance"] = value
                        candidate["judgment"] = judgments[value]
                        return
    raise HumanGoldPreparationError(f"candidate_label_key_not_found:{key}")


def _force_uncertainty_disagreements(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    left_entries = _candidate_label_entries(left)
    right_entries = _candidate_label_entries(right)
    modified = json.loads(json.dumps(right, ensure_ascii=False))
    answerability_values = (
        "answerable",
        "unanswerable_in_course",
        "scope_not_available",
        "evidence_stale_only",
    )
    for key in sorted(left_entries):
        left_entry, right_entry = left_entries[key], right_entries[key]
        if not (
            left_entry["needs_adjudication"] or right_entry["needs_adjudication"]
        ) or left_entry["value"] != right_entry["value"]:
            continue
        current = right_entry["value"]
        if key.startswith("answerability|"):
            replacement = next(value for value in answerability_values if value != current)
        else:
            replacement = (int(current) + 1) % 3
        _set_candidate_label(modified, key, replacement)
    return modified


def finalize_candidate_with_adjudication(
    left: dict[str, Any],
    right: dict[str, Any],
    adjudication: dict[str, Any],
) -> dict[str, Any]:
    """Finalize candidate labels while requiring uncertain labels to be adjudicated."""

    validate_adjudication_metadata(adjudication, left=left, right=right)
    modified_right = _force_uncertainty_disagreements(left, right)
    from src.annotation import finalize_with_adjudication as core_finalize

    return core_finalize(left, modified_right, adjudication)

def assert_public_input_access(manifest: dict[str, Any], requested_files: Iterable[str]) -> None:
    validate_candidate_manifest(manifest)
    requested = set(requested_files)
    forbidden = requested & set(manifest["access_policy"]["gold_only"])
    unknown = requested - set(manifest["access_policy"]["public_index_inputs"])
    if forbidden:
        raise HumanGoldPreparationError(f"gold_only_access_forbidden:{sorted(forbidden)}")
    if unknown:
        raise HumanGoldPreparationError(f"unknown_public_input:{sorted(unknown)}")


def assert_evaluation_allowed(manifest: dict[str, Any], *, contract_test_only: bool) -> None:
    level = manifest.get("dataset_level")
    if level == "micro_contract" and contract_test_only:
        return
    if level == "reviewed_silver" and manifest.get("gold", {}).get("status") == "reviewed_silver_llm_qrels":
        return
    if level == "human_gold_candidate":
        raise HumanGoldPreparationError("pending_human_gold_cannot_be_evaluated")
    gold = manifest.get("gold", {})
    if not (
        level == "human_gold"
        and gold.get("status") == "human_adjudicated"
        and gold.get("eligible_for_algorithm_comparison") is True
    ):
        raise HumanGoldPreparationError("fixture_not_eligible_for_algorithm_comparison")


def candidate_gate_status(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compute candidate approval while keeping B-R1 independently blocked."""

    validate_candidate_manifest(manifest)
    reasons: list[str] = []
    annotation = manifest.get("annotation")
    if not isinstance(annotation, dict):
        reasons.append("annotation_governance_must_be_object")
        annotation = {}

    annotators = annotation.get("independent_annotators")
    if not isinstance(annotators, list):
        reasons.append("independent_annotators_must_be_list")
        annotators = []
    valid_annotators = [row for row in annotators if isinstance(row, dict)]
    if len(valid_annotators) != len(annotators):
        reasons.append("annotator_records_must_be_objects")
    member_ids = [row.get("member_id") for row in valid_annotators]
    if (
        len(valid_annotators) != 2
        or len(set(member_ids)) != 2
        or any(not isinstance(value, str) or not value for value in member_ids)
    ):
        reasons.append("two_distinct_human_annotators_not_recorded")
    roles = {row.get("role") for row in valid_annotators}
    if roles != {"A", "B"}:
        reasons.append("annotator_roles_A_and_B_required")
    if any(
        set(row.get("task_coverage", [])) != {"retrieval", "mapping"}
        for row in valid_annotators
    ):
        reasons.append("annotator_task_coverage_incomplete")
    if any(
        not isinstance(row.get("bundle_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", row["bundle_sha256"])
        for row in valid_annotators
    ):
        reasons.append("annotation_bundle_hash_missing_or_invalid")
    if any(not row.get("identity_record_ref") for row in valid_annotators):
        reasons.append("annotator_identity_record_reference_missing")
    if any(
        not isinstance(row.get("independence_attestation_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", row["independence_attestation_sha256"])
        for row in valid_annotators
    ):
        reasons.append("annotator_independence_attestation_missing_or_invalid")

    adjudication = annotation.get("adjudication")
    if not isinstance(adjudication, dict):
        reasons.append("adjudication_record_must_be_object")
        adjudication = {}
    adjudicator = adjudication.get("member_id")
    if (
        not isinstance(adjudicator, str)
        or not adjudicator
        or adjudicator in set(member_ids)
    ):
        reasons.append("third_distinct_adjudicator_not_recorded")
    if not adjudication.get("identity_record_ref"):
        reasons.append("adjudicator_identity_record_reference_missing")
    if adjudication.get("complete") is not True:
        reasons.append("adjudication_incomplete")
    total = adjudication.get("total_disagreements")
    resolved = adjudication.get("resolved_disagreements")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or not isinstance(resolved, int)
        or isinstance(resolved, bool)
        or resolved < 0
        or resolved != total
    ):
        reasons.append("unresolved_or_invalid_adjudication_items")
    record_hash = adjudication.get("record_sha256")
    if not isinstance(record_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", record_hash):
        reasons.append("adjudication_record_hash_missing_or_invalid")

    calibration = annotation.get("calibration")
    if not isinstance(calibration, dict):
        reasons.append("calibration_record_must_be_object")
        calibration = {}
    if calibration.get("completed") is not True or not calibration.get("record_ref"):
        reasons.append("calibration_record_incomplete")

    governance = manifest.get("governance")
    if not isinstance(governance, dict):
        reasons.append("governance_must_be_object")
        governance = {}
    for owner in ("p1_00", "p1_10"):
        decision = governance.get(owner)
        if not isinstance(decision, dict):
            reasons.append(f"{owner}_decision_must_be_object")
            decision = {}
        if decision.get("status") != "approved":
            reasons.append(f"{owner}_not_approved")
        for field in ("reviewer_id", "decision_ref", "reviewed_at"):
            if not decision.get(field):
                reasons.append(f"{owner}_{field}_missing")
    if manifest.get("gold", {}).get("status") != "human_adjudicated_candidate":
        reasons.append("candidate_gold_not_human_adjudicated")

    status = "approved_candidate" if not reasons else "blocked"
    return {
        "gate": "B-G0b-human-gold-candidate",
        "candidate_status": status,
        "reasons": reasons,
        "eligible_for_algorithm_comparison": False,
        "b_r1_release": "blocked_requires_separate_explicit_authorization",
        "identity_verification": "P1-10_manual_external_check_required",
    }
