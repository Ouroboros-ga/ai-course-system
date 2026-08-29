"""CS 学科评测基准判定逻辑测试（XH-202620）。

覆盖 evaluate.py 的 _check 三种判定：contains、contains_grouped（符号渲染容差）、
judge0_manual（人工待验）；以及评测基准 JSON 的可加载性。全部本地，不调用外部服务。
"""
from __future__ import annotations

import json
from pathlib import Path

from finetune.evaluate import _check, _load_baseline

BASELINE = Path(__file__).resolve().parents[1] / "finetune" / "eval_baseline.json"


def test_contains_pass_and_fail():
    case = {"check": {"type": "contains", "markers": ["0.8", "0.666"]}}
    assert _check(case, "精确率 0.8，召回率 0.6667")["passed"] is True
    assert _check(case, "精确率 80%")["passed"] is False


def test_contains_grouped_tolerates_notation_variants():
    case = {"check": {"type": "contains_grouped", "markers": [["O(n²)", "O(n^2)"], ["O(n log n)", "O(nlogn)"]]}}
    assert _check(case, "最坏 O(n^2)；归并 O(n log n)")["passed"] is True
    assert _check(case, "最坏 O(n²)；归并 O(nlogn)")["passed"] is True
    assert _check(case, "最坏 O(n²)；归并 O(n^2)")["passed"] is False  # 第二组缺失


def test_contains_grouped_tolerates_latex_escapes():
    case = {"check": {"type": "contains_grouped", "markers": [["O(n²)", "O(n^2)"], ["O(n log n)", "O(nlogn)"]]}}
    assert _check(case, r"最坏 \( O(n^2) \)，归并 \( O(n \log n) \)")["passed"] is True


def test_judge0_manual_is_not_auto_judged():
    case = {"check": {"type": "judge0_manual"}}
    result = _check(case, "任意输出")
    assert result["passed"] is None
    assert "人工" in result["detail"]


def test_baseline_loads_and_all_cases_have_checks():
    baseline = _load_baseline(BASELINE)
    assert len(baseline["cases"]) == 10
    for case in baseline["cases"]:
        assert case["check"]["type"] in {"contains", "contains_grouped", "judge0_manual"}
        assert case["expected"]
        assert case["source"]["title"]


def test_baseline_c2_and_c8_checks_pass_on_correct_answers():
    baseline = _load_baseline(BASELINE)
    by_id = {c["id"]: c for c in baseline["cases"]}
    assert _check(by_id["C2"], "最坏情况 O(n^2)，归并排序 O(n log n)")["passed"] is True
    assert _check(by_id["C8"], "精确率 0.8，召回率 0.6667，F1 0.7273")["passed"] is True
