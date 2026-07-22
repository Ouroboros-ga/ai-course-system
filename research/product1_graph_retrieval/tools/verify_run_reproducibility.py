"""Verify deterministic ranking bytes while excluding intentionally variable timing fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import canonical_jsonl_bytes, sha256_bytes, write_json  # noqa: E402
from src.fixture_io import load_jsonl  # noqa: E402


def verify(left: Path, right: Path) -> dict[str, object]:
    left_rows, right_rows = load_jsonl(left), load_jsonl(right)
    if not left_rows or not right_rows:
        raise ValueError("both run files must be nonempty")
    left_header, right_header = left_rows[0], right_rows[0]
    for field in ("fixture_manifest_sha256", "configuration_sha256", "split", "task"):
        if left_header.get(field) != right_header.get(field):
            raise ValueError(f"run headers differ at {field}")
    left_hash = sha256_bytes(canonical_jsonl_bytes(left_rows[1:]))
    right_hash = sha256_bytes(canonical_jsonl_bytes(right_rows[1:]))
    if left_hash != right_hash:
        raise ValueError("ranked result records are not byte reproducible")
    return {
        "status": "byte_reproducible_rankings",
        "ranking_records_sha256": left_hash,
        "records_compared": len(left_rows) - 1,
        "runtime_fields_excluded": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.left, args.right)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
