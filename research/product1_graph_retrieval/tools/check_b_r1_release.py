from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.release_gate import (  # noqa: E402
    ReleaseGateBlocked,
    check_algorithm_preparation,
    check_b_r1_release,
)
from src.fixture_io import load_json  # noqa: E402
from tools.human_gold_candidate import candidate_gate_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether P1-00/P1-10 have released B-R1")
    parser.add_argument("fixture", type=Path)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="verify frozen contracts and algorithm preparation without releasing B-R1",
    )
    args = parser.parse_args()
    if args.preflight_only:
        try:
            result = check_algorithm_preparation(args.fixture)
        except ReleaseGateBlocked as exc:
            print(json.dumps({"gate": "B-P0", "status": "blocked", "reasons": str(exc).split(",")}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    manifest = load_json(args.fixture / "manifest.json")
    if manifest.get("dataset_level") == "human_gold_candidate":
        result = candidate_gate_status(manifest)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 2
    try:
        result = check_b_r1_release(args.fixture)
    except ReleaseGateBlocked as exc:
        print(json.dumps({"gate": "B-G0", "status": "blocked", "reasons": str(exc).split(",")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

