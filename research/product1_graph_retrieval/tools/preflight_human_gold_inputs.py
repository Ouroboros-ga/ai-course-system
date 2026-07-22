from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from human_gold_candidate import HumanGoldPreparationError, preflight_authorized_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate authorized real-course inputs for B-G0b")
    parser.add_argument("source_manifest", type=Path)
    args = parser.parse_args()
    try:
        result = preflight_authorized_sources(args.source_manifest)
    except HumanGoldPreparationError as exc:
        print(json.dumps({"status": "blocked", "reasons": str(exc).split(";")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
