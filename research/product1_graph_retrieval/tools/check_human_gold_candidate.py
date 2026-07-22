from __future__ import annotations

import argparse
import json
from pathlib import Path

from human_gold_candidate import HumanGoldPreparationError, candidate_gate_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Check B-G0b candidate completeness without releasing B-R1")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = candidate_gate_status(manifest)
    except (HumanGoldPreparationError, json.JSONDecodeError) as exc:
        print(json.dumps({"candidate_status": "blocked", "reasons": str(exc).split(";")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["candidate_status"] == "approved_candidate" else 2


if __name__ == "__main__":
    raise SystemExit(main())
