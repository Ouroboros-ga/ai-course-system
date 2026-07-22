"""Run the R0 course-isolated BM25 baseline without opening labels or qrels."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.bm25 import BM25_VERSION, CourseBM25Retriever  # noqa: E402
from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file, write_jsonl  # noqa: E402
from src.fixture_io import PUBLIC_INPUT_FILES, load_json, load_jsonl, manifest_sha256  # noqa: E402
from src.tokenizer import TOKENIZER_VERSION, token_count  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _load_public_fixture(fixture: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Check only declared public inputs. Gold-only files are never opened here."""

    manifest = load_json(fixture / "manifest.json")
    declared = set(manifest.get("access_policy", {}).get("index_inputs", []))
    if declared != PUBLIC_INPUT_FILES:
        raise ValueError("fixture public input partition is not the frozen contract")
    for name in ("corpus.jsonl", "evidence.jsonl", "queries.jsonl", "splits.json"):
        expected = manifest.get("files", {}).get(name)
        if expected != f"sha256:{sha256_file(fixture / name)}":
            raise ValueError(f"public input hash mismatch: {name}")
    return (
        manifest,
        load_jsonl(fixture / "corpus.jsonl"),
        load_jsonl(fixture / "evidence.jsonl"),
        load_jsonl(fixture / "queries.jsonl"),
        load_json(fixture / "splits.json"),
    )


def run_bm25(fixture: Path, config_path: Path, *, split: str, output: Path) -> dict[str, Any]:
    manifest, corpus, evidence, queries, splits = _load_public_fixture(fixture)
    config = load_json(config_path)
    if config.get("tokenizer", {}).get("version") != TOKENIZER_VERSION:
        raise ValueError("config tokenizer version does not match R0 implementation")
    bm25 = config.get("bm25", {})
    if bm25.get("idf") != "lucene-positive":
        raise ValueError("R0 supports only frozen lucene-positive IDF")
    target_key = f"{split}_query_ids"
    if target_key not in splits:
        raise ValueError(f"unknown split: {split}")
    query_by_id = {row["research_query_id"]: row for row in queries}
    target_queries = [query_by_id[query_id] for query_id in sorted(splits[target_key])]
    started = time.perf_counter()
    retriever = CourseBM25Retriever(corpus, evidence, k1=bm25["k1"], b=bm25["b"])
    index_build_seconds = time.perf_counter() - started
    # A warm-up is intentionally excluded from the recorded query timings.
    for query in target_queries:
        retriever.retrieve(query, top_k=int(config["candidate_k"]))
    rows: list[dict[str, Any]] = []
    timings: list[float] = []
    for query in target_queries:
        query_started = time.perf_counter()
        rows.append(retriever.retrieve(query, top_k=int(config["candidate_k"])))
        timings.append(time.perf_counter() - query_started)
    config_hash = sha256_bytes(canonical_json_bytes(config))
    header = {
        "record_type": "run_header",
        "run_schema_version": "product1-graph-retrieval-offline-run/1.0",
        "task": "retrieval",
        "run_id": config["run_name"],
        "implementation": {"bm25_version": BM25_VERSION, "tokenizer_version": TOKENIZER_VERSION},
        "fixture_manifest_sha256": manifest_sha256(fixture),
        "configuration_sha256": config_hash,
        "split": split,
        "gold_access_attestation": {
            "qrels_accessed_during_run": False,
            "query_labels_accessed_during_run": False,
        },
        "runtime": {
            "index_build_seconds": round(index_build_seconds, 12),
            "query_count": len(rows),
            "query_latency_seconds_p50": round(_percentile(timings, 0.50), 12),
            "query_latency_seconds_p95": round(_percentile(timings, 0.95), 12),
            "corpus_document_count": len(corpus),
            "corpus_token_count": token_count(row["text"] for row in corpus),
            "course_index_count": len(retriever.indexes),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
    }
    write_jsonl(output, [header, *rows])
    return {"run_path": str(output), "configuration_sha256": config_hash, "query_count": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_bm25(args.fixture, args.config, split=args.split, output=args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
