from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.micro_fixture import generate_micro_fixture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the B-G0 Level-A micro-contract fixture")
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = generate_micro_fixture(args.output, overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
