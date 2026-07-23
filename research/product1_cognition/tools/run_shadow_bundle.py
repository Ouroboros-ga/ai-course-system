"""Run a pre-approved KG-MEST research Shadow bundle from local JSON files.

Example (stdout only; no database or application API is contacted):
  $env:PYTHONPATH='research/product1_cognition'
  backend/.venv/Scripts/python.exe research/product1_cognition/tools/run_shadow_bundle.py --bundle-dir path/to/bundle
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cognition.shadow_bundle import run_shadow_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a governed KG-MEST read-only Shadow bundle.")
    parser.add_argument("--bundle-dir", required=True, type=Path)
    args = parser.parse_args()
    bundle_dir: Path = args.bundle_dir
    try:
        result = run_shadow_bundle(
            manifest=_read(bundle_dir / "manifest.json"),
            graph_nodes=_read(bundle_dir / "graph_nodes.json"),
            graph_relations=_read(bundle_dir / "graph_relations.json"),
            review_decisions=_read(bundle_dir / "review_decisions.json"),
            learning_events=_read(bundle_dir / "learning_events.json"),
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        print(json.dumps({"status": "rejected", "error_codes": ["SHADOW_BUNDLE_READ_FAILED"], "detail": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result.report, ensure_ascii=False, sort_keys=True, default=list))
    return 0 if result.status == "ok" else 1


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
