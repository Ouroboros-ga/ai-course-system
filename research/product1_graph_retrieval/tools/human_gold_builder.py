"""Fail-closed builder for an unlabelled B-G0b human-gold candidate."""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file, sha256_text, write_json, write_jsonl
from src.fixture_io import QUERY_STRATA, load_json, load_jsonl
from src.identities import (production_compatible_citation_key, research_chunk_id,
    research_evidence_id, research_knowledge_point_id, research_query_id, research_slide_id)
from tools.human_gold_candidate import (CANDIDATE_SCHEMA_VERSION, GOLD_ONLY_FILES,
    PUBLIC_INPUT_FILES, SOURCE_CONTRACTS, HumanGoldPreparationError,
    preflight_authorized_sources, scan_direct_identifiers, validate_candidate_manifest)

SELECTION_SCHEMA_VERSION = "product1-graph-retrieval-human-selection/0.1"
SELECTION_ATTESTATION = "human_selected_without_gold_labels_or_model_rankings"
OCR_REVIEW_STATUS = "human_reviewed_for_candidate"
OCR_NO_TEXT_STATUS = "human_reviewed_no_relevant_text"
LOW_TEXT_OCR_THRESHOLD = 30
TEXT_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
PICTURE_TAG = "{http://schemas.openxmlformats.org/presentationml/2006/main}pic"
QUERY_SPLITS = {"train", "validation", "test"}
MAPPING_SPLITS = {"validation", "test"}
FORBIDDEN_KEYS = {"answerable", "answerability", "expected_behavior", "gold", "gold_label",
    "relevance", "judgment", "score", "rank", "primary_slides", "supporting_slides",
    "irrelevant_hard_negatives", "model_answer", "model_recommendation"}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
STUDENT_RE = re.compile(r"(?:学号|学生编号|student\s*(?:id|number))\s*[:：#-]?\s*[A-Z0-9_-]{4,}", re.I)
IDENTITY_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

class HumanGoldBuildError(HumanGoldPreparationError):
    pass

def _stable(prefix: str, *parts: object) -> str:
    values = ["" if part is None else str(part) for part in parts]
    if any("\x00" in value for value in values):
        raise HumanGoldBuildError("stable_id_part_contains_nul")
    return prefix + hashlib.sha256("\x00".join(values).encode()).hexdigest()[:24]

def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, str(key), child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")

def _normalize(value: str) -> str:
    lines: list[str] = []
    for raw in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = " ".join(raw.split())
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines)

def _combine(values: Iterable[str]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for value in values:
        for line in _normalize(value).splitlines():
            if line and line not in seen:
                seen.add(line); lines.append(line)
    return "\n".join(lines)

def _redact(value: str, terms: Iterable[str]) -> tuple[str, int]:
    text, count = _normalize(value), 0
    for pattern, token in ((EMAIL_RE, "[REDACTED_EMAIL]"), (PHONE_RE, "[REDACTED_PHONE]"),
        (STUDENT_RE, "[REDACTED_STUDENT_ID]"), (IDENTITY_RE, "[REDACTED_IDENTITY]")):
        text, replaced = pattern.subn(token, text); count += replaced
    clean_terms = {str(term).strip() for term in terms if str(term).strip()}
    for term in sorted(clean_terms, key=len, reverse=True):
        count += text.count(term); text = text.replace(term, "[REDACTED_PERSONAL]")
    return _normalize(text), count

def _inside(base: Path, relative: str) -> Path:
    path, root = (base / relative).resolve(), base.resolve()
    if root not in path.parents:
        raise HumanGoldBuildError(f"path_outside_controlled_bundle:{relative}")
    return path

def _source_file(course: dict[str, Any], role: str, base: Path) -> Path:
    matches = [row for row in course.get("files", []) if isinstance(row, dict) and row.get("role") == role]
    if len(matches) != 1:
        raise HumanGoldBuildError(f"source_role_not_unique:{course.get('course_id')}:{role}")
    return _inside(base, matches[0]["path"])

def _extract_pptx(path: Path) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = []
            for name in archive.namelist():
                match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
                if match: names.append((int(match.group(1)), name))
            if not names: raise HumanGoldBuildError(f"pptx_has_no_slides:{path.name}")
            result = []
            for number, name in sorted(names):
                root = ElementTree.fromstring(archive.read(name))
                lines = [_normalize(node.text or "") for node in root.iter(TEXT_TAG)]
                result.append({"slide_number": number, "native_lines": [x for x in lines if x],
                    "picture_count": sum(1 for _ in root.iter(PICTURE_TAG))})
            return result
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise HumanGoldBuildError(f"pptx_parse_failed:{path.name}") from exc
def _validate_selection(selection: dict[str, Any], source_hash: str, course_ids: set[str]) -> None:
    errors: list[str] = []
    checks = ((selection.get("selection_schema_version") == SELECTION_SCHEMA_VERSION, "selection_schema_version_invalid"),
        (selection.get("candidate_id") == "human_gold_candidate_v0_1", "selection_candidate_id_invalid"),
        (selection.get("source_manifest_sha256") == source_hash, "selection_source_manifest_hash_mismatch"),
        (selection.get("attestation") == SELECTION_ATTESTATION, "selection_human_attestation_missing"),
        (bool(selection.get("created_at") and selection.get("created_by_member_id")), "selection_creation_metadata_missing"))
    errors.extend(message for ok, message in checks if not ok)
    privacy = selection.get("candidate_privacy_plan")
    if not isinstance(privacy, dict):
        errors.append("candidate_privacy_plan_missing"); privacy = {}
    if privacy.get("status") != "approved": errors.append("candidate_privacy_plan_not_approved")
    if privacy.get("candidate_must_be_deidentified") is not True: errors.append("candidate_deidentification_not_required")
    for field in ("reviewed_by", "evidence_ref"):
        if not privacy.get(field): errors.append(f"candidate_privacy_plan_{field}_missing")
    for path, key, value in _walk(selection):
        if key.casefold() in FORBIDDEN_KEYS: errors.append(f"selection_gold_or_algorithm_leak:{path}.{key}")
        if isinstance(value, str) and "\x00" in value: errors.append(f"selection_nul:{path}.{key}")
    courses = selection.get("courses")
    if not isinstance(courses, list): errors.append("selection_courses_must_be_list"); courses = []
    valid = [row for row in courses if isinstance(row, dict)]
    ids = [row.get("course_id") for row in valid]
    if len(valid) != len(courses): errors.append("selection_course_records_must_be_objects")
    if set(ids) != course_ids or len(ids) != len(set(ids)): errors.append("selection_courses_must_match_sources")
    for course in valid:
        cid = course.get("course_id", "<missing>")
        if not course.get("redaction_terms_reviewed_by") or not course.get("redaction_evidence_ref"):
            errors.append(f"{cid}:redaction_review_missing")
        if not isinstance(course.get("slide_chapter_ranges"), list) or not course.get("slide_chapter_ranges"):
            errors.append(f"{cid}:slide_chapter_ranges_missing")
        queries = course.get("queries")
        if not isinstance(queries, list): errors.append(f"{cid}:queries_must_be_list"); queries = []
        for query in queries:
            if not isinstance(query, dict): errors.append(f"{cid}:query_record_invalid"); continue
            if not query.get("text") or not query.get("query_type"): errors.append(f"{cid}:query_text_or_type_missing")
            if query.get("query_stratum") not in QUERY_STRATA: errors.append(f"{cid}:query_stratum_invalid")
            if query.get("split") not in QUERY_SPLITS: errors.append(f"{cid}:query_split_invalid")
        ocr_rows = course.get("ocr_records", [])
        provenance = course.get("ocr_provenance")
        if any(isinstance(row, dict) and row.get("review_status") == OCR_REVIEW_STATUS for row in ocr_rows):
            if not isinstance(provenance, dict):
                errors.append(f"{cid}:ocr_provenance_missing")
            else:
                for field in ("engine", "engine_version", "config_sha256"):
                    if not provenance.get(field): errors.append(f"{cid}:ocr_provenance_{field}_missing")
        kps = course.get("knowledge_points")
        if not isinstance(kps, list): errors.append(f"{cid}:knowledge_points_must_be_list"); kps = []
        for kp in kps:
            if not isinstance(kp, dict) or not kp.get("canonical_label"): errors.append(f"{cid}:knowledge_point_invalid"); continue
            if kp.get("split") not in MAPPING_SPLITS: errors.append(f"{cid}:knowledge_point_split_invalid")
            if not isinstance(kp.get("aliases"), list): errors.append(f"{cid}:knowledge_point_aliases_invalid")
    scope_queries = selection.get("scope_queries", [])
    if not isinstance(scope_queries, list): errors.append("scope_queries_must_be_list"); scope_queries = []
    for query in scope_queries:
        if not isinstance(query, dict): errors.append("scope_query_invalid"); continue
        if not query.get("course_id") or query.get("course_id") in course_ids: errors.append("scope_query_course_must_be_unavailable")
        if not query.get("text") or query.get("query_stratum") != "no_answer": errors.append("scope_query_must_be_no_answer")
        if query.get("split") not in QUERY_SPLITS: errors.append("scope_query_split_invalid")
    if errors: raise HumanGoldBuildError(";".join(errors))

def _chapter(course: dict[str, Any], number: int, page_count: int) -> tuple[str, list[str]]:
    matches = [row for row in course.get("slide_chapter_ranges", []) if isinstance(row, dict)
        and isinstance(row.get("start_slide"), int) and isinstance(row.get("end_slide"), int)
        and row["start_slide"] <= number <= row["end_slide"]]
    if len(matches) != 1: raise HumanGoldBuildError(f"chapter_range_must_cover_once:{course.get('course_id')}:{number}")
    row, path = matches[0], matches[0].get("chapter_path")
    if not isinstance(path, list) or len(path) < 2 or path[0] != course.get("course_id"):
        raise HumanGoldBuildError(f"chapter_path_invalid:{course.get('course_id')}:{number}")
    if not row.get("chapter_id") or not 1 <= number <= page_count:
        raise HumanGoldBuildError(f"chapter_or_page_invalid:{course.get('course_id')}:{number}")
    return str(row["chapter_id"]), [str(value) for value in path]

def _ocr_records(course: dict[str, Any], page_count: int) -> dict[int, dict[str, Any]]:
    result = {}
    for row in course.get("ocr_records", []):
        if not isinstance(row, dict): raise HumanGoldBuildError(f"ocr_record_invalid:{course.get('course_id')}")
        number = row.get("slide_number")
        if not isinstance(number, int) or not 1 <= number <= page_count or number in result:
            raise HumanGoldBuildError(f"ocr_slide_invalid_or_duplicate:{course.get('course_id')}:{number}")
        if row.get("review_status") not in {OCR_REVIEW_STATUS, OCR_NO_TEXT_STATUS} or not isinstance(row.get("blocks"), list):
            raise HumanGoldBuildError(f"ocr_not_human_reviewed:{course.get('course_id')}:{number}")
        if row.get("review_status") == OCR_NO_TEXT_STATUS and row["blocks"]:
            raise HumanGoldBuildError(f"ocr_no_text_review_must_have_no_blocks:{course.get('course_id')}:{number}")
        orders: set[int] = set()
        for block in row["blocks"]:
            order = block.get("order") if isinstance(block, dict) else None
            bbox = block.get("bbox") if isinstance(block, dict) else None
            confidence = block.get("confidence") if isinstance(block, dict) else None
            if not isinstance(order, int) or isinstance(order, bool) or order < 1:
                raise HumanGoldBuildError(f"ocr_block_order_invalid:{number}")
            if order in orders:
                raise HumanGoldBuildError(f"ocr_block_order_duplicate:{number}:{order}")
            orders.add(order)
            if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox):
                raise HumanGoldBuildError(f"ocr_block_bbox_invalid:{number}:{order}")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
                raise HumanGoldBuildError(f"ocr_block_confidence_invalid:{number}:{order}")
        result[number] = row
    return result

def _append_course_queries(selected: dict[str, Any], queries: list[dict[str, Any]], splits: dict[str, list[str]]) -> None:
    cid = selected["course_id"]
    for row in selected.get("queries", []):
        text = _normalize(row["text"]); qid = research_query_id(course_id=cid, text=text)
        queries.append({"research_query_id": qid, "research_sidecar": True,
            "not_a_production_contract_field": True, "course_id": cid, "text": text,
            "query_type": row["query_type"], "query_stratum": row["query_stratum"],
            "tags": sorted(set(row.get("tags", []))), "authorship": "human_prepared_before_gold_annotation"})
        splits[row["split"]].append(qid)

def _append_course_kps(selected: dict[str, Any], kps: list[dict[str, Any]], splits: dict[str, list[str]]) -> None:
    cid = selected["course_id"]
    for row in selected.get("knowledge_points", []):
        label = _normalize(row["canonical_label"]); kid = research_knowledge_point_id(course_id=cid, canonical_label=label)
        kps.append({"research_knowledge_point_id": kid, "research_sidecar": True,
            "not_a_production_contract_field": True, "course_id": cid, "canonical_label": label,
            "aliases": sorted({_normalize(x) for x in row.get("aliases", []) if _normalize(x)}),
            "alias_provenance": {"source": "human_confirmed_pre_split", "frozen_before_split": True,
                "identity_not_verified_by_tool": True}, "chapter_id": row.get("chapter_id"),
            "chapter_path": row.get("chapter_path", [cid, "unassigned"]), "research_evidence_ids": [],
            "review_status": "human_selected_candidate_not_mapping_gold"})
        splits[row["split"]].append(kid)
def build_human_gold_candidate(source_manifest_path: Path, selection_path: Path, output_dir: Path) -> dict[str, Any]:
    source_manifest_path, selection_path, output_dir = map(Path, (source_manifest_path, selection_path, output_dir))
    if output_dir.name != "human_gold_candidate_v0_1": raise HumanGoldBuildError("output_directory_name_invalid")
    if output_dir.exists() and any(output_dir.iterdir()): raise HumanGoldBuildError("candidate_output_must_be_empty")
    preflight = preflight_authorized_sources(source_manifest_path)
    source, selection = load_json(source_manifest_path), load_json(selection_path)
    courses = [row for row in source["courses"] if isinstance(row, dict)]
    course_ids = {row["course_id"] for row in courses}
    _validate_selection(selection, preflight["source_manifest_sha256"], course_ids)
    selected = {row["course_id"]: row for row in selection["courses"]}
    blocks: list[dict[str, Any]] = []; evidence: list[dict[str, Any]] = []
    corpus: list[dict[str, Any]] = []; slides: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []; kps: list[dict[str, Any]] = []
    query_splits = {name: [] for name in QUERY_SPLITS}; mapping_splits = {name: [] for name in MAPPING_SPLITS}
    redactions, ocr_reviewed, ocr_missing = 0, 0, []
    ocr_provenance: dict[str, dict[str, Any]] = {}
    for source_course in sorted(courses, key=lambda row: row["course_id"]):
        cid, chosen = source_course["course_id"], selected[source_course["course_id"]]
        page_count = source_course.get("page_count")
        if not isinstance(page_count, int) or page_count < 1: raise HumanGoldBuildError(f"authorized_page_count_invalid:{cid}")
        pptx = _source_file(source_course, "pptx_source", source_manifest_path.parent)
        pdf = _source_file(source_course, "pdf_reference", source_manifest_path.parent)
        pptx_hash, pdf_hash = sha256_file(pptx), sha256_file(pdf)
        extracted = _extract_pptx(pptx)
        if len(extracted) != page_count: raise HumanGoldBuildError(f"pptx_page_count_mismatch:{cid}")
        reviewed_ocr, terms = _ocr_records(chosen, page_count), chosen.get("redaction_terms", [])
        artifact_id = _stable("rart_", cid, pptx_hash, pdf_hash)
        document_id = _stable("rdoc_", cid, pptx_hash); version_ref = f"sha256:{pptx_hash}"
        for raw in extracted:
            number = raw["slide_number"]; chapter_id, chapter_path = _chapter(chosen, number, page_count)
            native, count = _redact(_combine(raw["native_lines"]), terms); redactions += count
            ocr = reviewed_ocr.get(number)
            if raw["picture_count"] > 0 and len(native.replace("\n", "")) < LOW_TEXT_OCR_THRESHOLD and ocr is None:
                ocr_missing.append(f"{cid}:{number}")
            ocr_text = ""; structured_ocr: list[dict[str, Any]] = []
            if ocr is not None and ocr["review_status"] == OCR_REVIEW_STATUS:
                ocr_reviewed += 1
                ocr_provenance[cid] = chosen["ocr_provenance"]
                for ocr_block in ocr["blocks"]:
                    if not isinstance(ocr_block, dict): continue
                    clean, count = _redact(str(ocr_block.get("text", "")), terms); redactions += count
                    if clean:
                        structured_ocr.append({"order": ocr_block.get("order"), "text": clean, "bbox": ocr_block.get("bbox"),
                            "confidence": ocr_block.get("confidence")})
                ocr_text = _combine(row["text"] for row in structured_ocr)
            body = _combine((native, ocr_text)); title = (native.splitlines() or ocr_text.splitlines() or [""])[0]
            unit_id = _stable("runit_", cid, document_id, number)
            slide_id = research_slide_id(course_id=cid, document_id=document_id, unit_id=unit_id)
            block_ids: list[str] = []; evidence_ids: list[str] = []
            sources = ["pptx_native_text"] + (["human_reviewed_ocr"] if ocr and ocr["review_status"] == OCR_REVIEW_STATUS else [])
            if body:
                block_id = _stable("rblk_", cid, document_id, number, body); block_ids.append(block_id)
                block = {"course_id": cid, "artifact_id": artifact_id, "document_id": document_id,
                    "unit_id": unit_id, "unit_type": "slide", "unit_index": number, "block_id": block_id,
                    "block_type": "slide_text", "page_or_slide": number, "chapter_id": chapter_id,
                    "chapter_path": chapter_path, "title": title, "text": body, "text_sha256": sha256_text(body)}
                blocks.append(block)
                eid = research_evidence_id(course_id=cid, artifact_id=artifact_id, document_id=document_id,
                    unit_id=unit_id, block_id=block_id, version_ref=version_ref, char_start=0, char_end=len(body))
                evidence_ids.append(eid)
                evidence.append({"research_evidence_id": eid, "research_sidecar": True,
                    "not_a_production_contract_field": True, "course_id": cid, "artifact_id": artifact_id,
                    "document_id": document_id, "unit_id": unit_id, "block_id": block_id,
                    "page_or_slide": number, "char_start": 0, "char_end": len(body), "text_snippet": body,
                    "citation_key": production_compatible_citation_key(artifact_id=artifact_id, block_id=block_id,
                        char_start=0, char_end=len(body)), "version_ref": version_ref, "status": "active",
                    "metadata": {"unit_type": "slide", "content_sources": sources, "ocr_reviewed": bool(ocr and ocr["review_status"] == OCR_REVIEW_STATUS),
                        "no_relevant_text_reviewed": bool(ocr and ocr["review_status"] == OCR_NO_TEXT_STATUS),
                        "research_ocr_blocks": structured_ocr}})
                chunk_id = research_chunk_id(course_id=cid, document_id=document_id, unit_id=unit_id,
                    block_id=block_id, research_evidence_ids=evidence_ids, text_sha256=sha256_text(body))
                corpus.append({**block, "research_chunk_id": chunk_id, "research_evidence_ids": evidence_ids,
                    "research_sidecar": True, "not_a_production_contract_field": True, "language": "zh-CN"})
            slides.append({"research_slide_id": slide_id, "research_sidecar": True,
                "not_a_production_contract_field": True, "course_id": cid, "document_id": document_id,
                "unit_id": unit_id, "slide_number": number, "chapter_id": chapter_id,
                "chapter_path": chapter_path, "title": title, "body_text": body, "block_ids": block_ids,
                "research_evidence_ids": evidence_ids, "controlled_source_ref": f"controlled-source://{cid}/pdf?page={number}",
                "requires_visual_review": True, "content_sources": sources,
                "ocr_review_status": ocr["review_status"] if ocr else "not_required_by_low_text_gate",
                "research_ocr_blocks": structured_ocr})
        _append_course_queries(chosen, queries, query_splits); _append_course_kps(chosen, kps, mapping_splits)
    for row in selection.get("scope_queries", []):
        text = _normalize(row["text"]); qid = research_query_id(course_id=row["course_id"], text=text)
        queries.append({"research_query_id": qid, "research_sidecar": True,
            "not_a_production_contract_field": True, "course_id": row["course_id"], "text": text,
            "query_type": row.get("query_type", "scope_probe"), "query_stratum": "no_answer",
            "tags": sorted(set(row.get("tags", ["scope_probe"]))), "authorship": "human_prepared_before_gold_annotation"})
        query_splits[row["split"]].append(qid)
    if ocr_missing: raise HumanGoldBuildError(f"human_reviewed_ocr_required:{sorted(ocr_missing)}")
    findings = scan_direct_identifiers(blocks + evidence + corpus + slides + queries + kps)
    if findings: raise HumanGoldBuildError(f"candidate_direct_identifiers_detected:{findings[:20]}")
    if not 100 <= len(corpus) <= 300: raise HumanGoldBuildError(f"candidate_chunk_count_must_be_100_to_300:{len(corpus)}")
    if not 60 <= len(queries) <= 100: raise HumanGoldBuildError(f"candidate_query_count_must_be_60_to_100:{len(queries)}")
    if not 40 <= len(kps) <= 80: raise HumanGoldBuildError(f"candidate_knowledge_point_count_must_be_40_to_80:{len(kps)}")
    if {row["query_stratum"] for row in queries} != QUERY_STRATA: raise HumanGoldBuildError("candidate_query_strata_incomplete")
    for records, key in ((blocks, "block_id"), (evidence, "research_evidence_id"), (corpus, "research_chunk_id"),
        (slides, "research_slide_id"), (queries, "research_query_id"), (kps, "research_knowledge_point_id")):
        values = [row[key] for row in records]
        if len(values) != len(set(values)): raise HumanGoldBuildError(f"duplicate_candidate_identity:{key}")
    splits = {"split_version": "human-gold-candidate/0.1", "assignment": "human_preassigned_before_gold_annotation",
        "train_query_ids": sorted(query_splits["train"]), "validation_query_ids": sorted(query_splits["validation"]),
        "test_query_ids": sorted(query_splits["test"]), "validation_knowledge_point_ids": sorted(mapping_splits["validation"]),
        "test_knowledge_point_ids": sorted(mapping_splits["test"]), "test_gold_access": "evaluation_only_after_run_freeze"}
    by_file = {"source_blocks.jsonl": sorted(blocks, key=lambda x: x["block_id"]),
        "evidence.jsonl": sorted(evidence, key=lambda x: x["research_evidence_id"]),
        "corpus.jsonl": sorted(corpus, key=lambda x: x["research_chunk_id"]),
        "queries.jsonl": sorted(queries, key=lambda x: x["research_query_id"]),
        "knowledge_points.jsonl": sorted(kps, key=lambda x: x["research_knowledge_point_id"]),
        "slides.jsonl": sorted(slides, key=lambda x: x["research_slide_id"])}
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, records in by_file.items(): write_jsonl(output_dir / name, records)
    write_json(output_dir / "splits.json", splits)
    hashes = {name: f"sha256:{sha256_file(output_dir / name)}" for name in sorted(PUBLIC_INPUT_FILES)}
    content_hash = sha256_bytes(canonical_json_bytes(hashes)); source_hash = preflight["source_manifest_sha256"]
    manifest = {"candidate_schema_version": CANDIDATE_SCHEMA_VERSION, "candidate_id": "human_gold_candidate_v0_1",
        "fixture_id": "human_gold_candidate_v0_1", "research_sidecar_schema_version": "product1-graph-retrieval-research-sidecar/1.0",
        "created_at": selection["created_at"], "dataset_level": "human_gold_candidate", "course_ids": sorted(course_ids),
        "files": hashes, "candidate_content_sha256": content_hash, "source_contracts": SOURCE_CONTRACTS,
        "access_policy": {"public_index_inputs": sorted(PUBLIC_INPUT_FILES), "gold_only": sorted(GOLD_ONLY_FILES),
            "gold_access": "evaluation_only_after_frozen_run"},
        "source_authorization": {"source_manifest_sha256": source_hash,
            "authorization_record_ref": f"source-manifest://{source_hash}#authorization",
            "privacy_review_ref": f"source-manifest://{source_hash}#privacy"}, "contains_personal_data": False,
        "normalization": {"pptx_parser": "stdlib_zip_xml_visible_text_v1", "notes_excluded": True,
            "document_metadata_excluded": True, "low_text_ocr_threshold": LOW_TEXT_OCR_THRESHOLD,
            "ocr_reviewed_slides": ocr_reviewed, "ocr_provenance_by_course": ocr_provenance,
            "redaction_replacements": redactions,
            "selection_sha256": sha256_file(selection_path)},
        "identity_fields": {"artifact_id_prefix": "rart_", "document_id_prefix": "rdoc_",
            "unit_id_prefix": "runit_", "block_id_prefix": "rblk_", "research_evidence_id_prefix": "rev_",
            "research_chunk_id_prefix": "rch_", "research_slide_id_prefix": "rsl_",
            "research_query_id_prefix": "rq_", "research_knowledge_point_id_prefix": "rkp_"},
        "gold": {"status": "pending_human_annotation", "eligible_for_algorithm_comparison": False},
        "annotation": {}, "governance": {}}
    write_json(output_dir / "manifest.json", manifest)
    return validate_human_gold_candidate_bundle(output_dir)
def validate_human_gold_candidate_bundle(candidate_dir: Path) -> dict[str, Any]:
    root = Path(candidate_dir); manifest = load_json(root / "manifest.json"); validate_candidate_manifest(manifest)
    errors: list[str] = []
    for name in PUBLIC_INPUT_FILES:
        path = root / name
        if not path.is_file(): errors.append(f"public_file_missing:{name}")
        elif manifest["files"].get(name) != f"sha256:{sha256_file(path)}": errors.append(f"public_file_hash_mismatch:{name}")
    for name in GOLD_ONLY_FILES:
        if (root / name).exists(): errors.append(f"pending_candidate_contains_gold_only_file:{name}")
    if manifest.get("candidate_content_sha256") != sha256_bytes(canonical_json_bytes(manifest["files"])):
        errors.append("candidate_content_hash_mismatch")
    blocks = load_jsonl(root / "source_blocks.jsonl"); evidence = load_jsonl(root / "evidence.jsonl")
    corpus = load_jsonl(root / "corpus.jsonl"); queries = load_jsonl(root / "queries.jsonl")
    kps = load_jsonl(root / "knowledge_points.jsonl"); slides = load_jsonl(root / "slides.jsonl")
    splits = load_json(root / "splits.json"); course_ids = set(manifest["course_ids"])
    def make_index(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        result = {}
        for row in records:
            value = row.get(key)
            if not isinstance(value, str) or not value or value in result: errors.append(f"invalid_or_duplicate_identity:{key}:{value}")
            else: result[value] = row
        return result
    block_idx = make_index(blocks, "block_id"); ev_idx = make_index(evidence, "research_evidence_id")
    chunk_idx = make_index(corpus, "research_chunk_id"); query_idx = make_index(queries, "research_query_id")
    kp_idx = make_index(kps, "research_knowledge_point_id"); slide_idx = make_index(slides, "research_slide_id")
    for row in blocks:
        bid = row.get("block_id")
        if row.get("course_id") not in course_ids: errors.append(f"block_course_scope:{bid}")
        if row.get("text_sha256") != sha256_text(row.get("text", "")): errors.append(f"block_text_hash:{bid}")
        if not str(bid).startswith("rblk_"): errors.append(f"block_not_explicitly_research:{bid}")
    for row in evidence:
        eid, block = row.get("research_evidence_id"), block_idx.get(row.get("block_id"))
        if not block: errors.append(f"evidence_block_missing:{eid}"); continue
        fields = ("course_id", "artifact_id", "document_id", "unit_id", "block_id", "page_or_slide")
        if any(row.get(field) != block.get(field) for field in fields): errors.append(f"evidence_coordinate_mismatch:{eid}")
        start, end, text = row.get("char_start"), row.get("char_end"), block.get("text", "")
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= len(text):
            errors.append(f"evidence_offset_invalid:{eid}")
        elif row.get("text_snippet") != text[start:end]: errors.append(f"evidence_snippet_mismatch:{eid}")
        expected = research_evidence_id(course_id=row.get("course_id", ""), artifact_id=row.get("artifact_id", ""),
            document_id=row.get("document_id", ""), unit_id=row.get("unit_id", ""), block_id=row.get("block_id", ""),
            version_ref=row.get("version_ref", ""), char_start=start, char_end=end)
        if eid != expected: errors.append(f"evidence_id_unstable:{eid}")
        citation = production_compatible_citation_key(artifact_id=row.get("artifact_id"), block_id=row.get("block_id"),
            char_start=start, char_end=end)
        if row.get("citation_key") != citation: errors.append(f"citation_key_mismatch:{eid}")
        if row.get("status") != "active": errors.append(f"candidate_evidence_not_active:{eid}")
    for row in corpus:
        cid = row.get("research_chunk_id"); block = block_idx.get(row.get("block_id")); refs = row.get("research_evidence_ids", [])
        if not block or row.get("text") != block.get("text"): errors.append(f"chunk_block_mismatch:{cid}")
        if not refs: errors.append(f"chunk_has_no_evidence:{cid}")
        if any(not ev_idx.get(ref) or ev_idx[ref].get("course_id") != row.get("course_id") for ref in refs):
            errors.append(f"chunk_evidence_scope:{cid}")
        expected = research_chunk_id(course_id=row.get("course_id", ""), document_id=row.get("document_id", ""),
            unit_id=row.get("unit_id", ""), block_id=row.get("block_id", ""), research_evidence_ids=refs,
            text_sha256=row.get("text_sha256", ""))
        if cid != expected: errors.append(f"chunk_id_unstable:{cid}")
    for row in queries:
        qid = row.get("research_query_id")
        if any(key in row for key in FORBIDDEN_KEYS): errors.append(f"query_gold_or_algorithm_leak:{qid}")
        if row.get("query_stratum") not in QUERY_STRATA: errors.append(f"query_stratum_invalid:{qid}")
        if qid != research_query_id(course_id=row.get("course_id", ""), text=row.get("text", "")):
            errors.append(f"query_id_unstable:{qid}")
    for row in kps:
        kid = row.get("research_knowledge_point_id")
        if row.get("course_id") not in course_ids: errors.append(f"knowledge_point_course_scope:{kid}")
        if kid != research_knowledge_point_id(course_id=row.get("course_id", ""), canonical_label=row.get("canonical_label", "")):
            errors.append(f"knowledge_point_id_unstable:{kid}")
        provenance = row.get("alias_provenance", {})
        if provenance.get("source") != "human_confirmed_pre_split" or provenance.get("frozen_before_split") is not True:
            errors.append(f"alias_provenance_invalid:{kid}")
        if row.get("research_evidence_ids") != []: errors.append(f"pending_kp_prebinds_mapping_gold:{kid}")
    for row in slides:
        sid = row.get("research_slide_id")
        if row.get("course_id") not in course_ids: errors.append(f"slide_course_scope:{sid}")
        if sid != research_slide_id(course_id=row.get("course_id", ""), document_id=row.get("document_id", ""), unit_id=row.get("unit_id", "")):
            errors.append(f"slide_id_unstable:{sid}")
        if not row.get("controlled_source_ref") or row.get("requires_visual_review") is not True:
            errors.append(f"slide_visual_review_ref_missing:{sid}")
        if any(not block_idx.get(ref) or block_idx[ref].get("course_id") != row.get("course_id") for ref in row.get("block_ids", [])):
            errors.append(f"slide_block_scope:{sid}")
        if any(not ev_idx.get(ref) or ev_idx[ref].get("course_id") != row.get("course_id") for ref in row.get("research_evidence_ids", [])):
            errors.append(f"slide_evidence_scope:{sid}")
    qsets = [set(splits.get(name, [])) for name in ("train_query_ids", "validation_query_ids", "test_query_ids")]
    if any(qsets[i] & qsets[j] for i in range(3) for j in range(i + 1, 3)): errors.append("query_split_overlap")
    if set().union(*qsets) != set(query_idx): errors.append("query_split_coverage")
    msets = [set(splits.get(name, [])) for name in ("validation_knowledge_point_ids", "test_knowledge_point_ids")]
    if msets[0] & msets[1]: errors.append("mapping_split_overlap")
    if set().union(*msets) != set(kp_idx): errors.append("mapping_split_coverage")
    if splits.get("test_gold_access") != "evaluation_only_after_run_freeze": errors.append("test_gold_policy_missing")
    findings = scan_direct_identifiers(blocks + evidence + corpus + queries + kps + slides)
    if findings: errors.append(f"candidate_direct_identifier_findings:{findings[:20]}")
    if not 100 <= len(chunk_idx) <= 300: errors.append("candidate_chunk_count_out_of_range")
    if not 60 <= len(query_idx) <= 100: errors.append("candidate_query_count_out_of_range")
    if not 40 <= len(kp_idx) <= 80: errors.append("candidate_knowledge_point_count_out_of_range")
    if {row.get("query_stratum") for row in queries} != QUERY_STRATA: errors.append("candidate_query_strata_incomplete")
    if errors: raise HumanGoldBuildError(";".join(errors))
    return {"status": "human_gold_candidate_ready_for_blind_packet_generation",
        "candidate_id": manifest["candidate_id"], "candidate_content_sha256": manifest["candidate_content_sha256"],
        "counts": {"courses": len(course_ids), "source_blocks": len(block_idx), "evidence": len(ev_idx),
            "chunks": len(chunk_idx), "queries": len(query_idx), "knowledge_points": len(kp_idx), "slides": len(slide_idx)},
        "gold": manifest["gold"], "valid": True}
def make_human_selection_template(source_manifest_path: Path) -> dict[str, Any]:
    """Return a deliberately pending template; humans must complete and attest it."""
    source_manifest_path = Path(source_manifest_path)
    audit = preflight_authorized_sources(source_manifest_path)
    source = load_json(source_manifest_path)
    courses = []
    for row in sorted(source["courses"], key=lambda value: value["course_id"]):
        cid, count = row["course_id"], row["page_count"]
        courses.append({"course_id": cid, "redaction_terms": [],
            "redaction_terms_reviewed_by": "PENDING_HUMAN_REVIEWER",
            "redaction_evidence_ref": "PENDING_CONTROLLED_REFERENCE",
            "ocr_provenance": None,
            "slide_chapter_ranges": [{"start_slide": 1, "end_slide": count,
                "chapter_id": "PENDING_HUMAN_CHAPTER_ID", "chapter_path": [cid, "PENDING_HUMAN_CHAPTER"]}],
            "ocr_records": [], "queries": [], "knowledge_points": []})
    return {"selection_schema_version": SELECTION_SCHEMA_VERSION,
        "candidate_id": "human_gold_candidate_v0_1", "source_manifest_sha256": audit["source_manifest_sha256"],
        "created_at": "PENDING_HUMAN_TIMESTAMP", "created_by_member_id": "PENDING_HUMAN_MEMBER",
        "attestation": "PENDING_HUMAN_ATTESTATION",
        "candidate_privacy_plan": {"status": "pending", "reviewed_by": "PENDING_HUMAN_REVIEWER",
            "evidence_ref": "PENDING_CONTROLLED_REFERENCE", "candidate_must_be_deidentified": True},
        "courses": courses,
        "scope_queries": [{"course_id": "PENDING_UNAVAILABLE_SCOPE_ID", "text": "PENDING_HUMAN_SCOPE_QUERY",
            "query_type": "scope_probe", "query_stratum": "no_answer", "split": "test", "tags": ["scope_probe"]}]}