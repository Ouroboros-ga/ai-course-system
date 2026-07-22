from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.canonical import write_json  # noqa: E402
from src.evaluation import evaluate_mapping, evaluate_retrieval  # noqa: E402
from src.fixture_io import load_json  # noqa: E402
from tools.human_gold_candidate import assert_evaluation_allowed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a frozen offline run after ranking is complete")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--task", choices=("retrieval", "mapping"), required=True)
    parser.add_argument(
        "--contract-test-only",
        action="store_true",
        help="required for synthetic micro fixtures; output cannot be used for algorithm comparison",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = load_json(args.fixture / "manifest.json")
    assert_evaluation_allowed(manifest, contract_test_only=args.contract_test_only)
    evaluator = evaluate_retrieval if args.task == "retrieval" else evaluate_mapping
    result = evaluator(args.fixture, args.run, contract_test_only=args.contract_test_only)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

