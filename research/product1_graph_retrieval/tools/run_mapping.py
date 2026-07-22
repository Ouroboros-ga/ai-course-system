"""Run B-R2 mapping without opening mapping qrels or retrieval labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import canonical_json_bytes, sha256_bytes, sha256_file, write_jsonl  # noqa: E402
from src.fixture_io import PUBLIC_INPUT_FILES, load_json, load_jsonl, manifest_sha256  # noqa: E402
from src.mapping import MAPPING_VERSION, KnowledgePointSlideMapper  # noqa: E402
from src.tokenizer import TOKENIZER_VERSION  # noqa: E402


def _load_public_mapping_inputs(fixture: Path) -> tuple[dict, list[dict], list[dict], list[dict], dict]:
    manifest = load_json(fixture / "manifest.json")
    if set(manifest.get("access_policy", {}).get("index_inputs", [])) != PUBLIC_INPUT_FILES:
        raise ValueError("fixture public input partition is not the frozen contract")
    for name in ("evidence.jsonl", "knowledge_points.jsonl", "slides.jsonl", "splits.json"):
        if manifest.get("files", {}).get(name) != f"sha256:{sha256_file(fixture / name)}":
            raise ValueError(f"public input hash mismatch: {name}")
    return (
        manifest,
        load_jsonl(fixture / "evidence.jsonl"),
        load_jsonl(fixture / "knowledge_points.jsonl"),
        load_jsonl(fixture / "slides.jsonl"),
        load_json(fixture / "splits.json"),
    )


def run_mapping(fixture: Path, config_path: Path, *, split: str, output: Path) -> dict:
    manifest, evidence, knowledge_points, slides, splits = _load_public_mapping_inputs(fixture)
    config = load_json(config_path)
    if config.get("tokenizer", {}).get("version") != TOKENIZER_VERSION:
        raise ValueError("mapping must reuse the frozen R0 tokenizer")
    if config.get("bm25", {}).get("idf") != "lucene-positive":
        raise ValueError("mapping must reuse frozen R0 BM25 IDF")
    target_key = f"{split}_knowledge_point_ids"
    if target_key not in splits:
        raise ValueError(f"unknown split: {split}")
    kp_by_id = {row["research_knowledge_point_id"]: row for row in knowledge_points}
    targets = [kp_by_id[kp_id] for kp_id in sorted(splits[target_key])]
    features, bm25 = config["features"], config["bm25"]
    mapper = KnowledgePointSlideMapper(
        slides,
        evidence,
        k1=bm25["k1"],
        b=bm25["b"],
        title_weight=features["title_match"],
        bm25_weight=features["normalized_bm25"],
        chapter_weight=features["chapter_proximity"],
    )
    rows = [mapper.map(knowledge_point, top_k=int(config["candidate_k"])) for knowledge_point in targets]
    header = {
        "record_type": "run_header",
        "run_schema_version": "product1-graph-retrieval-offline-run/1.0",
        "task": "mapping",
        "run_id": config["run_name"],
        "implementation": {"mapping_version": MAPPING_VERSION, "tokenizer_version": TOKENIZER_VERSION},
        "fixture_manifest_sha256": manifest_sha256(fixture),
        "configuration_sha256": sha256_bytes(canonical_json_bytes(config)),
        "split": split,
        "gold_access_attestation": {"qrels_accessed_during_run": False, "query_labels_accessed_during_run": False},
        "runtime": {"knowledge_point_count": len(rows), "course_index_count": len(mapper.indexes)},
    }
    write_jsonl(output, [header, *rows])
    return {"run_path": str(output), "query_count": len(rows), "configuration_sha256": header["configuration_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_mapping(args.fixture, args.config, split=args.split, output=args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
