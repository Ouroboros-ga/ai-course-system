"""Strict loader and validator for the B-G0 research fixture contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_json_bytes, sha256_bytes, sha256_file, sha256_text
from .identities import (
    production_compatible_citation_key,
    research_chunk_id,
    research_evidence_id,
    research_knowledge_point_id,
    research_query_id,
    research_slide_id,
)


FIXTURE_SCHEMA_VERSION = "product1-graph-retrieval-fixture/1.1"
RESEARCH_SIDECAR_SCHEMA_VERSION = "product1-graph-retrieval-research-sidecar/1.0"

REQUIRED_FILES = (
    "source_blocks.jsonl",
    "evidence.jsonl",
    "corpus.jsonl",
    "queries.jsonl",
    "retrieval_query_labels.jsonl",
    "retrieval_qrels.jsonl",
    "knowledge_points.jsonl",
    "slides.jsonl",
    "mapping_qrels.jsonl",
    "splits.json",
)

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
}

QUERY_STRATA = {
    "exact_term",
    "definition",
    "formula_or_code",
    "paraphrase",
    "cross_language_alias",
    "multi_hop_relation",
    "no_answer",
}
ANSWERABILITY = {
    "answerable",
    "unanswerable_in_course",
    "scope_not_available",
    "evidence_stale_only",
}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


class FixtureValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("\n".join(f"[{i.code}] {i.message}" for i in self.issues))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        records.append(value)
    return records


def _index(records: list[dict[str, Any]], key: str, issues: list[ValidationIssue]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(records, 1):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            issues.append(ValidationIssue("required_id", f"{key} missing at record {position}"))
            continue
        if value in result:
            issues.append(ValidationIssue("duplicate_id", f"duplicate {key}={value}"))
        result[value] = record
    return result


def _sidecar_ok(record: dict[str, Any]) -> bool:
    return (
        record.get("research_sidecar") is True
        and record.get("not_a_production_contract_field") is True
    )


def compute_fixture_content_hash(file_hashes: dict[str, str]) -> str:
    return sha256_bytes(canonical_json_bytes(file_hashes))


def manifest_sha256(fixture_dir: Path) -> str:
    return sha256_file(fixture_dir / "manifest.json")


def validate_fixture(fixture_dir: Path, *, verify_hashes: bool = True) -> dict[str, Any]:
    """Fail closed on schema, identity, citation, split, and leakage defects."""

    fixture_dir = Path(fixture_dir)
    issues: list[ValidationIssue] = []
    manifest_path = fixture_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FixtureValidationError([ValidationIssue("missing_manifest", str(manifest_path))])
    manifest = load_json(manifest_path)

    if manifest.get("fixture_schema_version") != FIXTURE_SCHEMA_VERSION:
        issues.append(ValidationIssue("schema_version", "unsupported fixture schema"))
    if manifest.get("research_sidecar_schema_version") != RESEARCH_SIDECAR_SCHEMA_VERSION:
        issues.append(ValidationIssue("sidecar_version", "unsupported research sidecar schema"))
    if manifest.get("dataset_level") not in {"micro_contract", "human_gold", "reviewed_silver"}:
        issues.append(ValidationIssue("dataset_level", "unsupported dataset_level"))

    course_ids = manifest.get("course_ids")
    if not isinstance(course_ids, list) or len(set(course_ids)) < 2:
        issues.append(ValidationIssue("course_count", "fixture must declare at least two courses"))
        course_set: set[str] = set()
    else:
        course_set = set(course_ids)

    declared_files = manifest.get("files", {})
    if set(declared_files) != set(REQUIRED_FILES):
        issues.append(ValidationIssue("manifest_files", "manifest files must exactly match required files"))
    for name in REQUIRED_FILES:
        path = fixture_dir / name
        if not path.is_file():
            issues.append(ValidationIssue("missing_file", name))
        elif verify_hashes and declared_files.get(name) != f"sha256:{sha256_file(path)}":
            issues.append(ValidationIssue("file_hash", f"hash mismatch for {name}"))
    if all((fixture_dir / name).is_file() for name in REQUIRED_FILES):
        actual_hashes = {name: f"sha256:{sha256_file(fixture_dir / name)}" for name in REQUIRED_FILES}
        if manifest.get("fixture_content_sha256") != compute_fixture_content_hash(actual_hashes):
            issues.append(ValidationIssue("content_hash", "fixture content hash mismatch"))

    access_policy = manifest.get("access_policy", {})
    if set(access_policy.get("index_inputs", [])) != PUBLIC_INPUT_FILES:
        issues.append(ValidationIssue("public_inputs", "index_inputs partition is not frozen"))
    if set(access_policy.get("gold_only", [])) != GOLD_ONLY_FILES:
        issues.append(ValidationIssue("gold_partition", "gold_only partition is not frozen"))
    if PUBLIC_INPUT_FILES & GOLD_ONLY_FILES:
        issues.append(ValidationIssue("gold_leak", "public and gold partitions overlap"))

    if issues and any(issue.code == "missing_file" for issue in issues):
        raise FixtureValidationError(issues)

    source_blocks = load_jsonl(fixture_dir / "source_blocks.jsonl")
    evidence = load_jsonl(fixture_dir / "evidence.jsonl")
    corpus = load_jsonl(fixture_dir / "corpus.jsonl")
    queries = load_jsonl(fixture_dir / "queries.jsonl")
    query_labels = load_jsonl(fixture_dir / "retrieval_query_labels.jsonl")
    retrieval_qrels = load_jsonl(fixture_dir / "retrieval_qrels.jsonl")
    knowledge_points = load_jsonl(fixture_dir / "knowledge_points.jsonl")
    slides = load_jsonl(fixture_dir / "slides.jsonl")
    mapping_qrels = load_jsonl(fixture_dir / "mapping_qrels.jsonl")
    splits = load_json(fixture_dir / "splits.json")

    block_index = _index(source_blocks, "block_id", issues)
    evidence_index = _index(evidence, "research_evidence_id", issues)
    chunk_index = _index(corpus, "research_chunk_id", issues)
    query_index = _index(queries, "research_query_id", issues)
    kp_index = _index(knowledge_points, "research_knowledge_point_id", issues)
    slide_index = _index(slides, "research_slide_id", issues)

    for block in source_blocks:
        if block.get("course_id") not in course_set:
            issues.append(ValidationIssue("block_course", f"unknown course for {block.get('block_id')}"))
        if block.get("text_sha256") != sha256_text(block.get("text", "")):
            issues.append(ValidationIssue("block_text_hash", str(block.get("block_id"))))

    for record in evidence:
        research_id = record.get("research_evidence_id")
        if not _sidecar_ok(record):
            issues.append(ValidationIssue("sidecar_marker", f"evidence {research_id}"))
        expected_id = research_evidence_id(
            course_id=record.get("course_id", ""),
            artifact_id=record.get("artifact_id", ""),
            document_id=record.get("document_id", ""),
            unit_id=record.get("unit_id", ""),
            block_id=record.get("block_id", ""),
            version_ref=record.get("version_ref", ""),
            char_start=record.get("char_start"),
            char_end=record.get("char_end"),
        )
        if research_id != expected_id:
            issues.append(ValidationIssue("evidence_id", f"unstable evidence ID {research_id}"))
        block = block_index.get(record.get("block_id"))
        if not block:
            issues.append(ValidationIssue("evidence_block", f"missing block for {research_id}"))
            continue
        coordinates = ("course_id", "artifact_id", "document_id", "unit_id", "block_id", "page_or_slide")
        if any(record.get(field) != block.get(field) for field in coordinates):
            issues.append(ValidationIssue("evidence_coordinates", str(research_id)))
        text = block.get("text", "")
        start, end = record.get("char_start"), record.get("char_end")
        if start is None and end is None:
            expected_snippet = text
        elif not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
            issues.append(ValidationIssue("evidence_offset", str(research_id)))
            expected_snippet = None
        else:
            expected_snippet = text[start:end]
        if expected_snippet is not None and record.get("text_snippet") != expected_snippet:
            issues.append(ValidationIssue("evidence_snippet", str(research_id)))
        if record.get("status") == "active" and (not record.get("version_ref") or not record.get("page_or_slide")):
            issues.append(ValidationIssue("active_evidence", str(research_id)))
        expected_citation = production_compatible_citation_key(
            artifact_id=record.get("artifact_id"),
            block_id=record.get("block_id"),
            char_start=start,
            char_end=end,
        )
        if record.get("citation_key") != expected_citation:
            issues.append(ValidationIssue("citation_key", str(research_id)))

    for record in corpus:
        research_id = record.get("research_chunk_id")
        if not _sidecar_ok(record):
            issues.append(ValidationIssue("sidecar_marker", f"chunk {research_id}"))
        if record.get("course_id") not in course_set:
            issues.append(ValidationIssue("chunk_course", str(research_id)))
        if record.get("text_sha256") != sha256_text(record.get("text", "")):
            issues.append(ValidationIssue("chunk_text_hash", str(research_id)))
        refs = record.get("research_evidence_ids", [])
        expected_id = research_chunk_id(
            course_id=record.get("course_id", ""),
            document_id=record.get("document_id", ""),
            unit_id=record.get("unit_id", ""),
            block_id=record.get("block_id", ""),
            research_evidence_ids=refs,
            text_sha256=record.get("text_sha256", ""),
        )
        if research_id != expected_id:
            issues.append(ValidationIssue("chunk_id", str(research_id)))
        if not refs:
            issues.append(ValidationIssue("chunk_evidence", f"no evidence for {research_id}"))
        for ref in refs:
            ev = evidence_index.get(ref)
            if not ev or ev.get("status") != "active":
                issues.append(ValidationIssue("chunk_evidence", f"inactive/missing {ref}"))
            elif any(ev.get(field) != record.get(field) for field in ("course_id", "document_id", "unit_id", "block_id", "page_or_slide")):
                issues.append(ValidationIssue("chunk_evidence_coordinates", str(research_id)))

    strata_seen: set[str] = set()
    for query in queries:
        research_id = query.get("research_query_id")
        if not _sidecar_ok(query):
            issues.append(ValidationIssue("sidecar_marker", f"query {research_id}"))
        if any(field in query for field in ("answerable", "answerability", "expected_behavior", "gold")):
            issues.append(ValidationIssue("gold_leak", f"query exposes label: {research_id}"))
        expected_id = research_query_id(course_id=query.get("course_id", ""), text=query.get("text", ""))
        if research_id != expected_id:
            issues.append(ValidationIssue("query_id", str(research_id)))
        stratum = query.get("query_stratum")
        if stratum not in QUERY_STRATA:
            issues.append(ValidationIssue("query_stratum", str(research_id)))
        else:
            strata_seen.add(stratum)
    if manifest.get("dataset_level") == "micro_contract" and strata_seen != QUERY_STRATA:
        issues.append(ValidationIssue("strata_coverage", "micro fixture must cover every query stratum"))

    label_index = _index(query_labels, "research_query_id", issues)
    if set(label_index) != set(query_index):
        issues.append(ValidationIssue("query_labels", "query labels must cover all queries exactly"))
    answerability_seen: set[str] = set()
    for query_id, label in label_index.items():
        answerability = label.get("answerability")
        if answerability not in ANSWERABILITY:
            issues.append(ValidationIssue("answerability", query_id))
            continue
        answerability_seen.add(answerability)
        query = query_index.get(query_id, {})
        if answerability == "scope_not_available":
            if query.get("course_id") in course_set:
                issues.append(ValidationIssue("scope_label", query_id))
        elif query.get("course_id") not in course_set:
            issues.append(ValidationIssue("query_course", query_id))
    if manifest.get("dataset_level") == "micro_contract" and answerability_seen != ANSWERABILITY:
        issues.append(ValidationIssue("answerability_coverage", "micro fixture must cover all answerability types"))

    qrel_pairs: set[tuple[str, str]] = set()
    relevance_seen: set[int] = set()
    qrels_by_query: dict[str, list[dict[str, Any]]] = {}
    for qrel in retrieval_qrels:
        pair = (qrel.get("research_query_id"), qrel.get("research_evidence_id"))
        if pair in qrel_pairs:
            issues.append(ValidationIssue("duplicate_qrel", str(pair)))
        qrel_pairs.add(pair)
        relevance = qrel.get("relevance")
        if relevance not in {0, 1, 2}:
            issues.append(ValidationIssue("qrel_grade", str(pair)))
        else:
            relevance_seen.add(relevance)
        if pair[0] not in query_index or pair[1] not in evidence_index:
            issues.append(ValidationIssue("qrel_reference", str(pair)))
        elif relevance in {1, 2}:
            query = query_index[pair[0]]
            ev = evidence_index[pair[1]]
            if ev.get("status") != "active" or ev.get("course_id") != query.get("course_id"):
                issues.append(ValidationIssue("positive_qrel_scope", str(pair)))
        qrels_by_query.setdefault(str(pair[0]), []).append(qrel)
    for query_id, label in label_index.items():
        positive = [q for q in qrels_by_query.get(query_id, []) if q.get("relevance", 0) >= 1]
        direct = [q for q in qrels_by_query.get(query_id, []) if q.get("relevance") == 2]
        if label.get("answerability") == "answerable" and not positive:
            issues.append(ValidationIssue("answerable_without_qrel", query_id))
        if label.get("answerability") == "answerable" and not direct:
            issues.append(ValidationIssue("answerable_without_direct_qrel", query_id))
        if label.get("answerability") != "answerable" and positive:
            issues.append(ValidationIssue("unanswerable_with_qrel", query_id))
    if manifest.get("dataset_level") == "micro_contract" and relevance_seen != {0, 1, 2}:
        issues.append(ValidationIssue("graded_qrels", "micro fixture must contain grades 0, 1, and 2"))

    for kp in knowledge_points:
        research_id = kp.get("research_knowledge_point_id")
        if not _sidecar_ok(kp):
            issues.append(ValidationIssue("sidecar_marker", f"knowledge point {research_id}"))
        expected_id = research_knowledge_point_id(
            course_id=kp.get("course_id", ""), canonical_label=kp.get("canonical_label", "")
        )
        if research_id != expected_id:
            issues.append(ValidationIssue("knowledge_point_id", str(research_id)))
        provenance = kp.get("alias_provenance", {})
        expected_alias_source = {
            "micro_contract": "synthetic_contract_fixture",
            "human_gold": "human_confirmed_pre_split",
            "reviewed_silver": "reviewed_silver_reconciled_pre_split",
        }.get(manifest.get("dataset_level"))
        if provenance.get("source") != expected_alias_source or provenance.get("frozen_before_split") is not True:
            issues.append(ValidationIssue("alias_provenance", str(research_id)))

    for slide in slides:
        research_id = slide.get("research_slide_id")
        if not _sidecar_ok(slide):
            issues.append(ValidationIssue("sidecar_marker", f"slide {research_id}"))
        expected_id = research_slide_id(
            course_id=slide.get("course_id", ""),
            document_id=slide.get("document_id", ""),
            unit_id=slide.get("unit_id", ""),
        )
        if research_id != expected_id:
            issues.append(ValidationIssue("slide_id", str(research_id)))
        for block_id in slide.get("block_ids", []):
            block = block_index.get(block_id)
            if not block or any(block.get(field) != slide.get(field) for field in ("course_id", "document_id", "unit_id")):
                issues.append(ValidationIssue("slide_block", f"{research_id}:{block_id}"))
        for ref in slide.get("research_evidence_ids", []):
            ev = evidence_index.get(ref)
            if not ev or ev.get("status") != "active" or ev.get("course_id") != slide.get("course_id"):
                issues.append(ValidationIssue("slide_evidence", f"{research_id}:{ref}"))

    mapping_pairs: set[tuple[str, str]] = set()
    positive_slides: dict[str, set[str]] = {}
    for qrel in mapping_qrels:
        pair = (qrel.get("research_knowledge_point_id"), qrel.get("research_slide_id"))
        if pair in mapping_pairs:
            issues.append(ValidationIssue("duplicate_mapping_qrel", str(pair)))
        mapping_pairs.add(pair)
        if pair[0] not in kp_index or pair[1] not in slide_index:
            issues.append(ValidationIssue("mapping_reference", str(pair)))
        if qrel.get("relevance") not in {0, 1, 2}:
            issues.append(ValidationIssue("mapping_grade", str(pair)))
        if qrel.get("relevance", 0) >= 1:
            positive_slides.setdefault(str(pair[0]), set()).add(str(pair[1]))
        for ref in qrel.get("research_evidence_ids", []):
            if ref not in evidence_index:
                issues.append(ValidationIssue("mapping_evidence", f"{pair}:{ref}"))
            elif pair[0] in kp_index and pair[1] in slide_index:
                slide_refs = set(slide_index[pair[1]].get("research_evidence_ids", []))
                kp_refs = set(kp_index[pair[0]].get("research_evidence_ids", []))
                if ref not in slide_refs:
                    issues.append(ValidationIssue("mapping_slide_evidence", f"{pair}:{ref}"))
                if qrel.get("relevance", 0) >= 1 and ref not in kp_refs:
                    issues.append(ValidationIssue("mapping_kp_evidence", f"{pair}:{ref}"))
        if pair[0] in kp_index and pair[1] in slide_index:
            if kp_index[pair[0]].get("course_id") != slide_index[pair[1]].get("course_id"):
                issues.append(ValidationIssue("mapping_course", str(pair)))
    if manifest.get("dataset_level") == "micro_contract" and not any(len(values) > 1 for values in positive_slides.values()):
        issues.append(ValidationIssue("multi_page_mapping", "micro fixture must include a multi-page mapping"))
    for kp_id in kp_index:
        if not any(
            row.get("research_knowledge_point_id") == kp_id and row.get("relevance") == 2
            for row in mapping_qrels
        ):
            issues.append(ValidationIssue("mapping_without_primary", kp_id))

    split_names = ("train_query_ids", "validation_query_ids", "test_query_ids")
    split_sets = [set(splits.get(name, [])) for name in split_names]
    if any(split_sets[i] & split_sets[j] for i in range(3) for j in range(i + 1, 3)):
        issues.append(ValidationIssue("split_overlap", "query splits overlap"))
    if set().union(*split_sets) != set(query_index):
        issues.append(ValidationIssue("split_coverage", "query splits must cover all queries"))
    if splits.get("test_gold_access") != "evaluation_only_after_run_freeze":
        issues.append(ValidationIssue("test_gold_policy", "test gold access policy missing"))
    mapping_split_sets = [
        set(splits.get("validation_knowledge_point_ids", [])),
        set(splits.get("test_knowledge_point_ids", [])),
    ]
    if mapping_split_sets[0] & mapping_split_sets[1]:
        issues.append(ValidationIssue("mapping_split_overlap", "knowledge point splits overlap"))
    if set().union(*mapping_split_sets) != set(kp_index):
        issues.append(ValidationIssue("mapping_split_coverage", "knowledge point splits must cover all knowledge points"))

    gold = manifest.get("gold", {})
    if manifest.get("dataset_level") == "micro_contract":
        if gold.get("status") != "synthetic_contract_oracle" or gold.get("eligible_for_algorithm_comparison") is not False:
            issues.append(ValidationIssue("micro_gold_status", "micro fixture cannot claim human gold"))
    elif manifest.get("dataset_level") == "human_gold":
        annotation = manifest.get("annotation", {})
        if gold.get("status") != "human_adjudicated" or gold.get("eligible_for_algorithm_comparison") is not True:
            issues.append(ValidationIssue("human_gold_status", "human gold status is incomplete"))
        if annotation.get("independent_human_annotator_count", 0) < 2 or annotation.get("adjudicated") is not True:
            issues.append(ValidationIssue("human_annotation", "two independent humans and adjudication are required"))
    elif manifest.get("dataset_level") == "reviewed_silver":
        annotation = manifest.get("annotation", {})
        if gold.get("status") != "reviewed_silver_llm_qrels" or gold.get("eligible_for_algorithm_comparison") is not False:
            issues.append(ValidationIssue("reviewed_silver_status", "reviewed silver must remain non-Gold"))
        if annotation.get("human_semantic_review_completed") is not True or annotation.get("llm_reconciliation_completed") is not True:
            issues.append(ValidationIssue("reviewed_silver_annotation", "reviewed silver reconciliation metadata missing"))

    if issues:
        raise FixtureValidationError(issues)

    canonical_digest = sha256_bytes(
        b"".join(
            canonical_json_bytes(load_json(fixture_dir / name))
            if name.endswith(".json")
            else b"".join(canonical_json_bytes(row) for row in load_jsonl(fixture_dir / name))
            for name in REQUIRED_FILES
        )
    )
    return {
        "fixture_id": manifest["fixture_id"],
        "dataset_level": manifest["dataset_level"],
        "manifest_sha256": manifest_sha256(fixture_dir),
        "canonical_dataset_sha256": canonical_digest,
        "counts": {
            "courses": len(course_set),
            "source_blocks": len(block_index),
            "evidence": len(evidence_index),
            "chunks": len(chunk_index),
            "queries": len(query_index),
            "knowledge_points": len(kp_index),
            "slides": len(slide_index),
        },
        "gold": manifest["gold"],
        "valid": True,
    }
