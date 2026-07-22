from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.release_gate import ReleaseGateBlocked, check_reviewed_silver_preparation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Reviewed Silver readiness for offline B-R1 baseline work")
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    try:
        result = check_reviewed_silver_preparation(args.fixture)
    except ReleaseGateBlocked as exc:
        print(json.dumps({"gate": "B-G0c-reviewed-silver", "status": "blocked", "reasons": str(exc).split(",")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
