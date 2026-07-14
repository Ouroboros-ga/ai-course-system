"""
Offline benchmark runner placeholder for Product 1.

Gold fixtures live in tests/benchmarks/product1/gold/<category>/.
Each category has a manifest describing its samples, provenance,
and expected metrics.

Usage:
    python tests/benchmarks/product1/runner.py --category parser
    python tests/benchmarks/product1/runner.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_ROOT = Path(__file__).resolve().parent
GOLD_ROOT = BENCHMARK_ROOT / "gold"


@dataclass
class FixtureProvenance:
    """Provenance tracking for every gold fixture."""

    source: str  # e.g. "public-domain-dataset", "self-authored", "license-granted"
    license: str = ""
    owner: str = ""
    usage_restriction: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str = ""


@dataclass
class BenchmarkResult:
    category: str
    total_samples: int = 0
    passed: int = 0
    failed: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Known fixture categories
# ---------------------------------------------------------------------------

FIXTURE_CATEGORIES = {
    "parser": "Parsing quality (block/page/bbox/order/table/formula)",
    "coordinate": "Coordinate geometry precision (normalized bbox/polygon)",
    "citation": "Citation accuracy (text/page/block support)",
    "retrieval": "Retrieval quality (Recall@k, MRR, nDCG)",
    "memory_privacy": "Memory isolation and privacy controls",
    "memory_deletion": "Memory deletion completeness (tombstone/cache)",
    "learning_event": "Learning event integrity and replay",
    "rule_baseline": "Rule-based baseline mastery accuracy",
    "safety_policy": "Safety policy enforcement (platform/course rules)",
    "migration": "Database migration forward compatibility",
    "rollback": "Migration rollback integrity",
}

FIXTURE_PROVENANCE: dict[str, FixtureProvenance] = {
    "parser": FixtureProvenance(
        source="TBD", description="Placeholder -- populate with self-authored or licensed samples"
    ),
    "coordinate": FixtureProvenance(
        source="TBD", description="Placeholder -- normalized bbox/polygon gold data"
    ),
    "citation": FixtureProvenance(
        source="TBD", description="Placeholder -- citation support gold data"
    ),
    "retrieval": FixtureProvenance(
        source="TBD", description="Placeholder -- retrieval relevance gold data"
    ),
    "memory_privacy": FixtureProvenance(
        source="TBD", description="Placeholder -- memory isolation gold scenarios"
    ),
    "memory_deletion": FixtureProvenance(
        source="TBD", description="Placeholder -- deletion completeness gold scenarios"
    ),
    "learning_event": FixtureProvenance(
        source="TBD", description="Placeholder -- learning event integrity gold data"
    ),
    "rule_baseline": FixtureProvenance(
        source="TBD", description="Placeholder -- rule-based baseline gold mastery"
    ),
    "safety_policy": FixtureProvenance(
        source="TBD", description="Placeholder -- safety policy enforcement gold scenarios"
    ),
    "migration": FixtureProvenance(
        source="TBD", description="Placeholder -- migration forward gold tests"
    ),
    "rollback": FixtureProvenance(
        source="TBD", description="Placeholder -- rollback integrity gold tests"
    ),
}


def run_benchmark(category: str) -> BenchmarkResult:
    """Run a benchmark for *category*.  Placeholder -- no actual measurements yet."""
    result = BenchmarkResult(category=category)
    gold_dir = GOLD_ROOT / category
    if not gold_dir.exists():
        result.errors.append(f"Gold directory not found: {gold_dir}")
        return result

    samples = list(gold_dir.iterdir())
    result.total_samples = len(samples)
    result.passed = 0
    result.failed = result.total_samples
    result.metrics = {"placeholder_metric": 0.0}
    result.errors.append("Benchmark runner not yet implemented -- placeholder only")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Product 1 offline benchmark runner")
    parser.add_argument(
        "--category", "-c",
        choices=list(FIXTURE_CATEGORIES.keys()) + ["all"],
        default="all",
        help="Benchmark category to run",
    )
    parser.add_argument("--output", "-o", default=None, help="Output JSON path")
    parser.add_argument("--list", action="store_true", help="List available categories")
    args = parser.parse_args()

    if args.list:
        print("Available benchmark categories:")
        for key, desc in FIXTURE_CATEGORIES.items():
            prov = FIXTURE_PROVENANCE.get(key)
            src = prov.source if prov else "unknown"
            print(f"  {key:25s} {desc:50s} (source: {src})")
        return

    categories = list(FIXTURE_CATEGORIES.keys()) if args.category == "all" else [args.category]
    results: list[BenchmarkResult] = []

    for cat in categories:
        print(f"Running benchmark: {cat} ...")
        result = run_benchmark(cat)
        results.append(result)
        print(f"  {result.passed}/{result.total_samples} passed, {len(result.errors)} errors")

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [r.to_dict() for r in results],
    }
    output_json = json.dumps(output, ensure_ascii=False, indent=2)
    print("\n--- Full Results ---")
    print(output_json)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
        print(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
