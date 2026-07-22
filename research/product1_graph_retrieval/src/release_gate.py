"""Mechanical preparation and release gates before any B-R1 implementation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, sha256_bytes
from .fixture_io import load_json, validate_fixture


class ReleaseGateBlocked(ValueError):
    pass


ALGORITHM_PREPARATION_SPEC: dict[str, Any] = {
    "spec_version": "graph-retrieval-algorithm-preparation/1.0",
    "scope": {
        "index_partition": "one_index_per_course",
        "selection_order": ["select_course_index", "score_candidates"],
        "global_score_then_filter": False,
    },
    "tokenizer": {
        "version": "mixed-script-ngram/1.0",
        "search_view_unicode": "NFKC",
        "case_normalization": "casefold",
        "source_text_mutated": False,
        "latin_code_pattern": r"[a-z0-9]+(?:[._:/#+-][a-z0-9]+)*",
        "cjk_ranges": ["3400-4DBF", "4E00-9FFF", "F900-FAFF"],
        "cjk_ngrams": [1, 2],
        "stopwords": "none",
        "query_term_frequency": "unique_terms_first_occurrence_order",
        "document_term_frequency": "count_all_occurrences",
    },
    "bm25": {
        "idf": "log(1+(N-df+0.5)/(df+0.5))",
        "k1": 1.2,
        "b": 0.75,
        "validation_grid": {
            "k1": [0.9, 1.2, 1.5, 1.8],
            "b": [0.5, 0.75, 0.9],
        },
        "score_eligibility": "strictly_greater_than_zero",
        "tie_break": ["score_desc", "research_chunk_id_asc"],
        "float_serialization_digits": 12,
    },
    "result": {
        "statuses": ["ok", "abstain"],
        "abstain_reasons": [
            "empty_query",
            "scope_not_available",
            "no_lexical_match",
            "no_active_evidence",
        ],
        "abstain_hits": [],
        "citation_on_abstain": False,
        "required_active_evidence_fields": [
            "research_evidence_id",
            "artifact_id",
            "document_id",
            "unit_id",
            "block_id",
            "version_ref",
            "page_or_slide",
            "status",
            "citation_key",
        ],
    },
    "mapping": {
        "candidate_partition": "same_course_only",
        "title_match": {
            "exact_normalized_label_or_alias": 1.0,
            "otherwise": "max_set_sorensen_dice_over_frozen_label_tokens",
            "empty_token_set": 0.0,
            "aliases": "human_confirmed_pre_split_only",
        },
        "normalized_bm25": "raw_score/max_same_course_raw_score_else_zero",
        "chapter_proximity": "1/(1+distance)",
        "weights": {"title": 0.45, "bm25": 0.40, "chapter": 0.15},
        "tie_break": ["score_desc", "research_slide_id_asc"],
        "candidate_evidence_policy": "exclude_ineligible_then_abstain_if_none_remain",
        "hard_abstain": [
            "knowledge_point_has_no_active_evidence",
            "no_candidate_slide_with_active_evidence",
            "all_candidate_signals_are_zero",
        ],
        "soft_thresholds": "validation_only_not_frozen_before_human_gold",
    },
    "prohibited": [
        "production_wiring",
        "global_cross_course_index",
        "test_gold_parameter_tuning",
        "micro_fixture_quality_claims",
        "dense_retrieval",
        "rrf_fusion",
        "graph_expansion",
        "graphrag",
    ],
}


CONTRACT_BASELINE_SHA256 = {
    "backend/app/platform/document_intelligence/document_ir/models.py": "159860b0b2e1111cb702de9e08071dd7b89e480f41aaf62c56ed74f0a1f7fde4",
    "backend/app/platform/evidence/contracts.py": "98a7ccf9d2ae186b65a9576cf170580c4db4416c98dbc8583f82b4287ca4b57d",
    "backend/app/platform/evidence/citation.py": "a3c76de0682a119b7c08ad78bdb4933327a5d9d5327ade1d05b86ceed93ac175",
    "backend/app/platform/retrieval/schemas.py": "b509164c081fac29a3a9e030db7fc9a15682385dc73979fcf5c1635c53b605fb",
    "backend/app/platform/retrieval/providers/contracts.py": "1b81d93ba854e5f6e9c5650854f9205d67bba178d0676f2f38b825223da85b62",
    "backend/app/platform/retrieval/gateway.py": "ee911fd54aba25728a84dcf8b4c9473c567dae7191f769527b3e9d91bd22c4c5",
    "backend/app/domain/education_graph/models.py": "c862d61d277fc4bafb7e72ffd5bebae4adb54be0a606434b5952d5c62182cff7",
    "backend/app/domain/education_graph/enums.py": "85064a7d932dd4e649a211d36ac7636fb4473e332049245032988fb8f861c7e4",
    "docs/refactor/product1/contracts/registry.md": "617676c2ff6efacac394e0e14136b7eab1395942dfc86b63cbe9a0c443d4c6ad",
}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def check_contract_baseline(repository_root: Path | None = None) -> dict[str, Any]:
    """Fail closed when a frozen input changes after the preparation audit."""

    root = Path(repository_root) if repository_root is not None else _repository_root()
    reasons: list[str] = []
    actual: dict[str, str] = {}
    for relative_path, expected_hash in CONTRACT_BASELINE_SHA256.items():
        path = root / relative_path
        if not path.is_file():
            reasons.append(f"contract_missing:{relative_path}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        actual[relative_path] = digest
        if digest != expected_hash:
            reasons.append(f"contract_drift:{relative_path}")
    if reasons:
        raise ReleaseGateBlocked(",".join(reasons))
    return {"status": "verified", "files": actual}


def check_algorithm_preparation(
    fixture_dir: Path,
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Verify prerequisites that may be frozen before Human Gold is ready.

    This check authorizes no algorithm implementation and produces no quality
    claim. It only proves fixture integrity, contract stability, and a frozen
    deterministic implementation specification.
    """

    audit = validate_fixture(fixture_dir)
    contracts = check_contract_baseline(repository_root)
    spec_bytes = canonical_json_bytes(ALGORITHM_PREPARATION_SPEC)
    return {
        "gate": "B-P0",
        "status": "prepared_not_released",
        "implementation_authorized": False,
        "quality_comparison_authorized": False,
        "fixture_id": audit["fixture_id"],
        "fixture_level": audit["dataset_level"],
        "manifest_sha256": audit["manifest_sha256"],
        "contract_files_verified": len(contracts["files"]),
        "spec_version": ALGORITHM_PREPARATION_SPEC["spec_version"],
        "spec_sha256": sha256_bytes(spec_bytes),
        "next_gate": "B-G0_human_gold_and_explicit_B-R1_release",
    }


def check_b_r1_release(fixture_dir: Path) -> dict[str, Any]:
    check_algorithm_preparation(fixture_dir)
    audit = validate_fixture(fixture_dir)
    manifest = load_json(Path(fixture_dir) / "manifest.json")
    reasons: list[str] = []
    if manifest.get("dataset_level") != "human_gold":
        reasons.append("dataset_level_is_not_human_gold")
    if manifest.get("gold", {}).get("eligible_for_algorithm_comparison") is not True:
        reasons.append("gold_not_eligible_for_algorithm_comparison")
    annotation = manifest.get("annotation", {})
    if annotation.get("independent_human_annotator_count", 0) < 2:
        reasons.append("fewer_than_two_independent_human_annotators")
    if annotation.get("adjudicated") is not True:
        reasons.append("human_adjudication_incomplete")
    governance = manifest.get("governance", {})
    for owner in ("p1_00", "p1_10"):
        decision = governance.get(owner, {})
        if decision.get("status") != "approved":
            reasons.append(f"{owner}_not_approved")
        if not decision.get("reviewer_id") or not decision.get("decision_ref"):
            reasons.append(f"{owner}_approval_evidence_missing")
    if governance.get("b_r1_release") != "approved":
        reasons.append("b_r1_release_not_approved")
    if reasons:
        raise ReleaseGateBlocked(",".join(reasons))
    return {
        "gate": "B-G0",
        "next_stage": "B-R1",
        "status": "approved",
        "fixture_id": manifest["fixture_id"],
        "manifest_sha256": audit["manifest_sha256"],
        "p1_00": governance["p1_00"],
        "p1_10": governance["p1_10"],
        "b_r2_constraint": "reuse_the_single_b_r1_tokenizer_and_bm25_implementation",
        "production_contract_changes": "independent_ADR_required",
    }


def check_reviewed_silver_preparation(fixture_dir: Path) -> dict[str, Any]:
    """Validate the personal-learning Silver gate without relaxing B-R1's formal gate."""

    audit = validate_fixture(fixture_dir)
    manifest = load_json(Path(fixture_dir) / "manifest.json")
    reasons: list[str] = []
    if manifest.get("dataset_level") != "reviewed_silver":
        reasons.append("dataset_level_is_not_reviewed_silver")
    if manifest.get("gold", {}).get("status") != "reviewed_silver_llm_qrels":
        reasons.append("silver_qrels_status_missing")
    if manifest.get("gold", {}).get("eligible_for_algorithm_comparison") is not False:
        reasons.append("silver_must_not_claim_gold_eligibility")
    annotation = manifest.get("annotation", {})
    if annotation.get("human_semantic_review_completed") is not True:
        reasons.append("human_semantic_review_not_recorded")
    if annotation.get("llm_reconciliation_completed") is not True:
        reasons.append("llm_reconciliation_not_recorded")
    source = manifest.get("source_inventory", {})
    if source.get("paired_pptx_pdf_courses") != len(manifest.get("course_ids", [])):
        reasons.append("paired_source_inventory_incomplete")
    if reasons:
        raise ReleaseGateBlocked(",".join(reasons))
    return {
        "gate": "B-G0c-reviewed-silver",
        "status": "ready_for_offline_baseline_authorization",
        "fixture_id": manifest["fixture_id"],
        "manifest_sha256": audit["manifest_sha256"],
        "offline_baseline_implementation_eligible": True,
        "quality_comparison_eligibility": "reviewed_silver_only_not_human_gold",
        "formal_b_r1_release": "blocked_until_human_gold_and_independent_approvals",
        "production_integration": "not_authorized",
    }
