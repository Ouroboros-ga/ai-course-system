"""
Machine-readable quality-gate report generator for Product 1.

Usage:
    python -m backend.tests.product1.quality_gate_report [--gate G1] [--output path/to/report.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from backend.tests.product1.contracts.contract_helpers import (
    GateDecision,
    QualityGateReport,
)


def _run_pytest(paths: list[str], extra_args: list[str] | None = None) -> tuple[int, int, int]:
    """Run pytest and return (passed, failed, skipped)."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        *paths,
        *(extra_args or []),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    stdout = result.stdout
    stderr = result.stderr
    # Parse summary line like "3 passed, 1 failed, 2 skipped in 0.12s"
    passed = failed = skipped = 0
    for line in (stdout + stderr).splitlines():
        line = line.strip()
        if "passed" in line and "failed" in line:
            import re

            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+) skipped", line)
            if m:
                skipped = int(m.group(1))
            break
    return passed, failed, skipped


def build_g1_report(
    branch: str = "",
    worktree_path: str = "",
    baseline_sha: str = "",
    output_path: str | None = None,
) -> QualityGateReport:
    """Build a G1 (Contract) quality-gate report."""

    report = QualityGateReport(
        gate="G1",
        branch=branch,
        worktree_path=worktree_path,
        baseline_sha=baseline_sha,
    )

    # -- Contract-test checks ------------------------------------------------
    contract_paths = [
        "backend/tests/product1/contracts/",
    ]

    p, f, s = _run_pytest(contract_paths)
    status = GateDecision.PASS if f == 0 else GateDecision.FAIL
    report.add_check(
        name="P1 contract tests",
        status=status,
        passed=p,
        failed=f,
        skipped=s,
    )

    # -- Regression check ----------------------------------------------------
    core_paths = [
        "backend/tests/test_m4a_isolation.py",
        "backend/tests/test_m4a_route_contract.py",
        "backend/tests/test_m4b_fakes.py",
        "backend/tests/test_m4b_main_flows.py",
        "backend/tests/test_m7_demo_flow.py",
        "backend/tests/test_r1_adapters.py",
        "backend/tests/test_r1_adapter_migration.py",
        "backend/tests/test_r2_task_runtime.py",
        "backend/tests/test_r2b_video_task.py",
        "backend/tests/test_r2b_ppt_task.py",
        "backend/tests/test_r2c_tts_batch_task.py",
        "backend/tests/test_retrieval_gateway.py",
        "backend/tests/test_rag_course_scope.py",
    ]
    p, f, s = _run_pytest(core_paths)
    status = GateDecision.PASS if f == 0 else GateDecision.FAIL
    report.add_check(
        name="Core regression suite (M4A/M4B/M7/R1/R2/retrieval)",
        status=status,
        passed=p,
        failed=f,
        skipped=s,
    )

    report.finalize()
    if output_path:
        report.write(output_path)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Product 1 quality gate report")
    parser.add_argument("--gate", default="G1", help="Gate identifier (G1, G2, ...)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--branch", default="", help="Current branch name")
    parser.add_argument("--worktree", default="", help="Worktree path")
    parser.add_argument("--sha", default="", help="Baseline SHA")
    args = parser.parse_args()

    report = build_g1_report(
        branch=args.branch,
        worktree_path=args.worktree,
        baseline_sha=args.sha,
        output_path=args.output,
    )
    print(report.to_json())


if __name__ == "__main__":
    main()
