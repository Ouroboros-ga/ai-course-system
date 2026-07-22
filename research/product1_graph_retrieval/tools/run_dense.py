"""Run local R1 Dense retrieval using only public inputs and a fixed local model."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PACKAGES = RESEARCH_ROOT / "runtime" / "python-packages"
sys.path[:0] = [str(RESEARCH_ROOT), str(RUNTIME_PACKAGES)]

from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file, write_jsonl  # noqa: E402
from src.dense import BgeSmallZhEmbedder, DENSE_VERSION, CourseDenseRetriever, cache_filename, cache_identity, model_file_manifest  # noqa: E402
from src.fixture_io import PUBLIC_INPUT_FILES, load_json, load_jsonl, manifest_sha256  # noqa: E402


def _load_public_inputs(fixture: Path):
    manifest = load_json(fixture / "manifest.json")
    if set(manifest.get("access_policy", {}).get("index_inputs", [])) != PUBLIC_INPUT_FILES:
        raise ValueError("fixture public input partition is not frozen")
    for name in ("corpus.jsonl", "evidence.jsonl", "queries.jsonl", "splits.json"):
        if manifest["files"].get(name) != f"sha256:{sha256_file(fixture / name)}":
            raise ValueError(f"public input hash mismatch: {name}")
    return manifest, load_jsonl(fixture / "corpus.jsonl"), load_jsonl(fixture / "evidence.jsonl"), load_jsonl(fixture / "queries.jsonl"), load_json(fixture / "splits.json")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def run_dense(fixture: Path, config_path: Path, *, split: str, output: Path, cache_dir: Path) -> dict:
    manifest, corpus, evidence, queries, splits = _load_public_inputs(fixture)
    config = load_json(config_path)
    target_key = f"{split}_query_ids"
    if target_key not in splits:
        raise ValueError(f"unknown split: {split}")
    model = config["model"]
    model_dir = Path(model["local_dir"])
    files = model_file_manifest(model_dir)
    if files["model.safetensors"] != f"sha256:{model['model_safetensors_sha256']}":
        raise ValueError("dense model weight hash mismatch")
    identity = cache_identity(fixture_manifest_sha256=manifest_sha256(fixture), model={"repo_id": model["repo_id"], "revision": model["revision"], "files": files}, max_length=model["max_length"], query_instruction=model["query_instruction"])
    cache_path = cache_dir / cache_filename(identity)
    started = time.perf_counter()
    embedder = BgeSmallZhEmbedder(model_dir, max_length=model["max_length"], query_instruction=model["query_instruction"])
    retriever = CourseDenseRetriever(corpus, evidence, embedder=embedder, cache_path=cache_path, cache_key=identity)
    index_seconds = time.perf_counter() - started
    query_by_id = {row["research_query_id"]: row for row in queries}
    targets = [query_by_id[query_id] for query_id in sorted(splits[target_key])]
    for query in targets:
        retriever.retrieve(query, top_k=config["candidate_k"], minimum_cosine=config["minimum_cosine"])
    rows, timings = [], []
    for query in targets:
        query_started = time.perf_counter()
        rows.append(retriever.retrieve(query, top_k=config["candidate_k"], minimum_cosine=config["minimum_cosine"]))
        timings.append(time.perf_counter() - query_started)
    header = {
        "record_type": "run_header", "run_schema_version": "product1-graph-retrieval-offline-run/1.0", "task": "retrieval", "run_id": config["run_name"],
        "implementation": {"dense_version": DENSE_VERSION, "exact_search": "course_local_exact_cosine"},
        "fixture_manifest_sha256": manifest_sha256(fixture), "configuration_sha256": sha256_bytes(canonical_json_bytes(config)), "split": split,
        "model": {"repo_id": model["repo_id"], "revision": model["revision"], "files": files, "pooling": model["pooling"], "normalization": model["normalization"], "max_length": model["max_length"]},
        "embedding_cache": {"path": str(cache_path), "sha256": f"sha256:{sha256_file(cache_path)}", "identity": identity},
        "gold_access_attestation": {"qrels_accessed_during_run": False, "query_labels_accessed_during_run": False},
        "runtime": {"index_build_seconds": round(index_seconds, 12), "query_count": len(rows), "query_latency_seconds_p50": round(_percentile(timings, .5), 12), "query_latency_seconds_p95": round(_percentile(timings, .95), 12), "course_index_count": len(retriever.chunks), "platform": platform.platform(), "python_version": platform.python_version()},
    }
    write_jsonl(output, [header, *rows])
    return {"run_path": str(output), "cache_path": str(cache_path), "query_count": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=RESEARCH_ROOT / "runtime" / "embedding-cache")
    args = parser.parse_args()
    print(json.dumps(run_dense(args.fixture, args.config, split=args.split, output=args.output, cache_dir=args.cache_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
