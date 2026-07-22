from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from tools.human_gold_builder import (HumanGoldBuildError, build_human_gold_candidate,
    make_human_selection_template, validate_human_gold_candidate_bundle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate an unlabelled B-G0b candidate")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("source_manifest", type=Path)
    build.add_argument("selection", type=Path)
    build.add_argument("output", type=Path)
    template = sub.add_parser("template")
    template.add_argument("source_manifest", type=Path)
    template.add_argument("output", type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_human_gold_candidate(args.source_manifest, args.selection, args.output)
        elif args.command == "template":
            result = make_human_selection_template(args.source_manifest)
            from src.canonical import write_json
            write_json(args.output, result)
            result = {"status": "pending_human_selection_template_created", "output": str(args.output)}
        else:
            result = validate_human_gold_candidate_bundle(args.candidate)
    except (HumanGoldBuildError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reasons": str(exc).split(";")}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())