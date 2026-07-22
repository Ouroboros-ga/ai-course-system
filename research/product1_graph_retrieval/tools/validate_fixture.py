from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.fixture_io import FixtureValidationError, validate_fixture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a B-G0 research fixture")
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    try:
        result = validate_fixture(args.fixture)
    except FixtureValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
