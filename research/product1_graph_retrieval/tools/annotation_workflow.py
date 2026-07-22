from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.annotation import (  # noqa: E402
    compare_independent_annotations,
    finalize_with_adjudication,
    prepare_annotation_packet,
)
from src.canonical import write_json  # noqa: E402
from src.fixture_io import load_json  # noqa: E402
from tools.human_gold_candidate import (  # noqa: E402
    augment_candidate_comparison,
    enrich_adjudication_packet,
    enrich_blind_packet,
    finalize_candidate_with_adjudication,
    validate_adjudication_metadata,
    validate_annotation_pair_metadata,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and compare independent human annotation bundles")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("fixture", type=Path)
    prepare.add_argument("--task", choices=("retrieval", "mapping"), required=True)
    prepare.add_argument("--role", choices=("A", "B"))
    prepare.add_argument("--member-id", required=True)
    prepare.add_argument("--output", type=Path, required=True)

    compare = sub.add_parser("compare")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    compare.add_argument("--output", type=Path, required=True)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("left", type=Path)
    finalize.add_argument("right", type=Path)
    finalize.add_argument("adjudication", type=Path)
    finalize.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        manifest = load_json(args.fixture / "manifest.json")
        result = prepare_annotation_packet(args.fixture, task=args.task, member_id=args.member_id)
        if manifest.get("dataset_level") == "human_gold_candidate":
            if args.role is None:
                raise ValueError("--role A or B is required for a human_gold_candidate")
            result = enrich_blind_packet(
                result, manifest=manifest, role=args.role, member_id=args.member_id
            )
    elif args.command == "compare":
        left, right = load_json(args.left), load_json(args.right)
        is_candidate = "human_gold_candidate_v0_1" in {
            left.get("candidate_id"), right.get("candidate_id")
        }
        if is_candidate:
            validate_annotation_pair_metadata(left, right)
        result = compare_independent_annotations(left, right)
        if is_candidate:
            result = augment_candidate_comparison(result, left=left, right=right)
            result = enrich_adjudication_packet(result, left=left, right=right)
    else:
        left, right = load_json(args.left), load_json(args.right)
        adjudication = load_json(args.adjudication)
        is_candidate = "human_gold_candidate_v0_1" in {
            left.get("candidate_id"), right.get("candidate_id"), adjudication.get("candidate_id")
        }
        if is_candidate:
            validate_adjudication_metadata(adjudication, left=left, right=right)
            result = finalize_candidate_with_adjudication(left, right, adjudication)
        else:
            result = finalize_with_adjudication(left, right, adjudication)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output), "command": args.command}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



