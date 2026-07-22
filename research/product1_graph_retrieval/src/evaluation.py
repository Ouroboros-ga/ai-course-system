"""Gold-separated evaluation for frozen retrieval and mapping run files."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from .fixture_io import load_json, load_jsonl, manifest_sha256, validate_fixture


RUN_SCHEMA_VERSION = "product1-graph-retrieval-offline-run/1.0"


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return fmean(values) if values else 0.0


def _load_run(run_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = load_jsonl(run_path)
    if not rows or rows[0].get("record_type") != "run_header":
        raise ValueError("run JSONL must start with a run_header")
    header = rows[0]
    if header.get("run_schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("unsupported run schema")
    attestation = header.get("gold_access_attestation", {})
    if attestation.get("qrels_accessed_during_run") is not False or attestation.get("query_labels_accessed_during_run") is not False:
        raise ValueError("run is ineligible because gold was accessed during ranking")
    return header, rows[1:]


def _eligibility(manifest: dict[str, Any], contract_test_only: bool) -> str:
    if manifest["gold"]["eligible_for_algorithm_comparison"]:
        return "human_gold_algorithm_comparison"
    if manifest.get("dataset_level") == "reviewed_silver":
        return "reviewed_silver_offline_research_only"
    if not contract_test_only:
        raise ValueError("synthetic micro oracle requires contract_test_only=True")
    return "contract_only_not_algorithm_comparison"


def _dcg(relevances: list[int]) -> float:
    return sum((2**rel - 1) / math.log2(rank + 1) for rank, rel in enumerate(relevances, 1))


def evaluate_retrieval(
    fixture_dir: Path,
    run_path: Path,
    *,
    contract_test_only: bool = False,
) -> dict[str, Any]:
    audit = validate_fixture(fixture_dir)
    manifest = load_json(Path(fixture_dir) / "manifest.json")
    header, results = _load_run(Path(run_path))
    if header.get("task") != "retrieval":
        raise ValueError("run task must be retrieval")
    if header.get("fixture_manifest_sha256") != manifest_sha256(Path(fixture_dir)):
        raise ValueError("run fixture manifest hash mismatch")
    eligibility = _eligibility(manifest, contract_test_only)

    queries = {row["research_query_id"]: row for row in load_jsonl(Path(fixture_dir) / "queries.jsonl")}
    labels = {row["research_query_id"]: row for row in load_jsonl(Path(fixture_dir) / "retrieval_query_labels.jsonl")}
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    for row in load_jsonl(Path(fixture_dir) / "retrieval_qrels.jsonl"):
        qrels[row["research_query_id"]][row["research_evidence_id"]] = row["relevance"]
    chunks = {row["research_chunk_id"]: row for row in load_jsonl(Path(fixture_dir) / "corpus.jsonl")}
    evidence = {row["research_evidence_id"]: row for row in load_jsonl(Path(fixture_dir) / "evidence.jsonl")}
    splits = load_json(Path(fixture_dir) / "splits.json")
    split = header.get("split")
    target_ids = set(splits[f"{split}_query_ids"])
    result_index = {row["research_query_id"]: row for row in results}
    if set(result_index) != target_ids:
        raise ValueError("run results must cover the selected split exactly")

    ks = (1, 3, 5, 10)
    per_query: list[dict[str, Any]] = []
    wrong_course_hits = 0
    all_hits = 0
    complete_hits = 0
    valid_citation_hits = 0
    contamination_queries = 0
    for query_id in sorted(target_ids):
        query, label, result = queries[query_id], labels[query_id], result_index[query_id]
        hits = result.get("hits", [])
        if result.get("status") == "abstain" and hits:
            raise ValueError(f"abstain result has hits: {query_id}")
        if result.get("status") not in {"ok", "abstain"}:
            raise ValueError(f"invalid result status: {query_id}")
        if [hit.get("rank") for hit in hits] != list(range(1, len(hits) + 1)):
            raise ValueError(f"hit ranks are not contiguous: {query_id}")

        query_contaminated = False
        retrieved_ids: list[str] = []
        seen_chunks: set[str] = set()
        seen_evidence: set[str] = set()
        for hit in hits:
            all_hits += 1
            if hit.get("course_id") != query["course_id"]:
                wrong_course_hits += 1
                query_contaminated = True
            chunk = chunks.get(hit.get("research_chunk_id"))
            refs = hit.get("research_evidence_ids", [])
            if hit.get("research_chunk_id") in seen_chunks or seen_evidence.intersection(refs):
                raise ValueError(f"duplicate chunk or evidence in ranking: {query_id}")
            seen_chunks.add(hit.get("research_chunk_id"))
            seen_evidence.update(refs)
            citations = hit.get("citations", [])
            citation_by_ref = {row.get("research_evidence_id"): row.get("citation_key") for row in citations}
            complete = bool(chunk and refs and set(refs) == set(chunk["research_evidence_ids"]))
            for ref in refs:
                ev = evidence.get(ref)
                complete = complete and bool(
                    ev
                    and ev["status"] == "active"
                    and ev["course_id"] == hit.get("course_id")
                    and ev["block_id"] == chunk["block_id"]
                )
                if ev:
                    retrieved_ids.append(ref)
            if complete:
                complete_hits += 1
            if complete and len(citation_by_ref) == len(refs) and all(
                citation_by_ref.get(ref) == evidence[ref]["citation_key"] for ref in refs
            ):
                valid_citation_hits += 1
        if query_contaminated:
            contamination_queries += 1

        gold = qrels.get(query_id, {})
        relevant = {ref for ref, grade in gold.items() if grade >= 1}
        direct = {ref for ref, grade in gold.items() if grade == 2}
        metrics: dict[str, float] = {}
        if label["answerability"] == "answerable":
            first_rank = next((rank for rank, ref in enumerate(retrieved_ids, 1) if ref in relevant), None)
            metrics["rr"] = 0.0 if first_rank is None else 1.0 / first_rank
            for k in ks:
                top = set(retrieved_ids[:k])
                metrics[f"recall@{k}"] = len(top & relevant) / len(relevant)
                metrics[f"direct_recall@{k}"] = len(top & direct) / len(direct)
                metrics[f"success@{k}"] = float(bool(top & relevant))
                actual_rels = [gold.get(ref, 0) for ref in retrieved_ids[:k]]
                ideal_rels = sorted(gold.values(), reverse=True)[:k]
                ideal = _dcg(ideal_rels)
                metrics[f"ndcg@{k}"] = 0.0 if ideal == 0 else _dcg(actual_rels) / ideal
        per_query.append(
            {
                "research_query_id": query_id,
                "query_stratum": query["query_stratum"],
                "answerability": label["answerability"],
                "status": result["status"],
                "metrics": metrics,
            }
        )

    answerable_rows = [row for row in per_query if row["answerability"] == "answerable"]
    unanswerable_rows = [row for row in per_query if row["answerability"] != "answerable"]
    aggregate = {key: _mean(row["metrics"][key] for row in answerable_rows) for key in answerable_rows[0]["metrics"]} if answerable_rows else {}
    aggregate["mrr"] = aggregate.pop("rr", 0.0)
    aggregate.update(
        {
            "correct_abstain_rate": _mean(row["status"] == "abstain" for row in unanswerable_rows),
            "false_answer_rate": _mean(row["status"] != "abstain" for row in unanswerable_rows),
            "false_abstain_rate": _mean(row["status"] == "abstain" for row in answerable_rows),
            "cross_course_contamination_rate": 0.0 if not all_hits else wrong_course_hits / all_hits,
            "queries_with_any_contamination": contamination_queries,
            "evidence_completeness_rate": 1.0 if not all_hits else complete_hits / all_hits,
            "citation_key_validity_rate": 1.0 if not all_hits else valid_citation_hits / all_hits,
        }
    )
    by_answerability = {
        answerability: {
            "queries": len(rows),
            "abstain_rate": _mean(row["status"] == "abstain" for row in rows),
            "answer_rate": _mean(row["status"] != "abstain" for row in rows),
        }
        for answerability in sorted({row["answerability"] for row in per_query})
        if (rows := [row for row in per_query if row["answerability"] == answerability])
    }

    by_stratum: dict[str, dict[str, float]] = {}
    for stratum in sorted({row["query_stratum"] for row in per_query}):
        rows = [row for row in answerable_rows if row["query_stratum"] == stratum]
        if rows:
            by_stratum[stratum] = {
                "queries": len(rows),
                "mrr": _mean(row["metrics"]["rr"] for row in rows),
                "recall@5": _mean(row["metrics"]["recall@5"] for row in rows),
            }
    return {
        "evaluation_schema_version": "product1-graph-retrieval-evaluation/1.0",
        "task": "retrieval",
        "eligibility": eligibility,
        "fixture_audit": audit,
        "run_header": header,
        "aggregate": aggregate,
        "by_query_stratum": by_stratum,
        "per_query": per_query,
        "by_answerability": by_answerability,
    }


def evaluate_mapping(
    fixture_dir: Path,
    run_path: Path,
    *,
    contract_test_only: bool = False,
) -> dict[str, Any]:
    audit = validate_fixture(fixture_dir)
    manifest = load_json(Path(fixture_dir) / "manifest.json")
    header, results = _load_run(Path(run_path))
    if header.get("task") != "mapping":
        raise ValueError("run task must be mapping")
    if header.get("fixture_manifest_sha256") != manifest_sha256(Path(fixture_dir)):
        raise ValueError("run fixture manifest hash mismatch")
    eligibility = _eligibility(manifest, contract_test_only)
    splits = load_json(Path(fixture_dir) / "splits.json")
    target_ids = set(splits[f"{header['split']}_knowledge_point_ids"])
    result_index = {row["research_knowledge_point_id"]: row for row in results}
    if set(result_index) != target_ids:
        raise ValueError("mapping results must cover selected split exactly")
    qrels: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in load_jsonl(Path(fixture_dir) / "mapping_qrels.jsonl"):
        qrels[row["research_knowledge_point_id"]][row["research_slide_id"]] = row
    slides = {row["research_slide_id"]: row for row in load_jsonl(Path(fixture_dir) / "slides.jsonl")}

    per_kp = []
    for kp_id in sorted(target_ids):
        result = result_index[kp_id]
        ranked = result.get("slides", [])
        if result.get("status") == "abstain" and ranked:
            raise ValueError(f"mapping abstain has slides: {kp_id}")
        if [row.get("rank") for row in ranked] != list(range(1, len(ranked) + 1)):
            raise ValueError(f"mapping ranks are not contiguous: {kp_id}")
        gold = qrels.get(kp_id, {})
        primary = {sid for sid, row in gold.items() if row["relevance"] == 2}
        useful = {sid for sid, row in gold.items() if row["relevance"] >= 1}
        ids = [row["research_slide_id"] for row in ranked]
        first_relevant = next((rank for rank, sid in enumerate(ids, 1) if sid in useful), None)
        # A ranked negative has no qrel evidence set to bind to.  It must not
        # lower the grounding score merely because it was inspected at Top-K.
        binding_checks = []
        for row in ranked:
            sid = row["research_slide_id"]
            expected = set(gold.get(sid, {}).get("research_evidence_ids", []))
            supplied = set(row.get("research_evidence_ids", []))
            if expected:
                binding_checks.append(bool(supplied and supplied <= set(slides[sid]["research_evidence_ids"]) and supplied & expected))
        per_kp.append(
            {
                "research_knowledge_point_id": kp_id,
                "top1_primary": float(bool(ids[:1] and ids[0] in primary)),
                "top3_primary": float(bool(set(ids[:3]) & primary)),
                "top3_useful_coverage": len(set(ids[:3]) & useful) / len(useful),
                "rr": 0.0 if first_relevant is None else 1.0 / first_relevant,
                "evidence_binding_accuracy": _mean(binding_checks),
            }
        )
    return {
        "evaluation_schema_version": "product1-graph-retrieval-evaluation/1.0",
        "task": "mapping",
        "eligibility": eligibility,
        "fixture_audit": audit,
        "run_header": header,
        "aggregate": {
            "top1_primary_accuracy": _mean(row["top1_primary"] for row in per_kp),
            "top3_primary_accuracy": _mean(row["top3_primary"] for row in per_kp),
            "top3_useful_coverage": _mean(row["top3_useful_coverage"] for row in per_kp),
            "mapping_mrr": _mean(row["rr"] for row in per_kp),
            "evidence_binding_accuracy": _mean(row["evidence_binding_accuracy"] for row in per_kp),
        },
        "per_knowledge_point": per_kp,
    }
