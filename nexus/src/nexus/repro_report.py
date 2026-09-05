"""M4-B3：复现报告的确定性构建与判定（LLM 不参与 PASS/FAIL）。

数据来源：Repro Worker 作业记录（status/steps_result/log_tail）。
指标提取：从训练日志尾部按正则抽取（当前支持 nanoGPT 的
``step N: train loss X, val loss Y`` 行）；期望指标来自已核验预设
（expected_metrics，来源与容差随预设声明，如实写入报告）。
判定：|observed - target| <= tolerance → PASS，否则 FAIL；
无期望指标/无法提取 → INCOMPLETE。全程纯函数，可单测。
"""
from __future__ import annotations

import re
from typing import Any

_VAL_LOSS_RE = re.compile(r"val loss ([0-9]+\.?[0-9]*)")
_TRAIN_LOSS_RE = re.compile(r"train loss ([0-9]+\.?[0-9]*)")


def extract_metrics(steps_result: list[dict[str, Any]]) -> dict[str, float | None]:
    """从各步日志尾部提取指标（取最后一次出现——训练末段数值）。"""
    val_loss: float | None = None
    train_loss: float | None = None
    for step in steps_result or []:
        tail = str(step.get("log_tail") or "")
        for match in _VAL_LOSS_RE.finditer(tail):
            val_loss = float(match.group(1))
        for match in _TRAIN_LOSS_RE.finditer(tail):
            train_loss = float(match.group(1))
    return {"val_loss": val_loss, "train_loss_final": train_loss}


def compare_metrics(
    observed: dict[str, float | None],
    expected: dict[str, dict[str, float]] | None,
) -> list[dict[str, Any]]:
    """逐指标确定性比较：|observed - target| <= tolerance → PASS。"""
    comparison: list[dict[str, Any]] = []
    for name, spec in (expected or {}).items():
        target = float(spec.get("target", 0.0))
        tolerance = float(spec.get("tolerance", 0.0))
        value = observed.get(name)
        if value is None:
            comparison.append({
                "metric": name, "target": target, "tolerance": tolerance,
                "observed": None, "pass": False, "note": "未在日志中提取到该指标",
            })
            continue
        comparison.append({
            "metric": name,
            "target": target,
            "tolerance": tolerance,
            "observed": value,
            "pass": abs(value - target) <= tolerance,
            "note": "",
        })
    return comparison


def decide_verdict(comparison: list[dict[str, Any]]) -> str:
    """PASS 当且仅当存在至少一条比较且全部通过；否则 FAIL/INCOMPLETE。"""
    if not comparison:
        return "INCOMPLETE"
    return "PASS" if all(item["pass"] for item in comparison) else "FAIL"


def build_report(
    *,
    job: dict[str, Any],
    preset: dict[str, Any] | None,
) -> dict[str, Any]:
    """构建确定性报告（observed/expected/verdict/steps/env/license）。"""
    steps = job.get("steps_result") or []
    metrics = extract_metrics(steps)
    expected = (preset or {}).get("expected_metrics")
    comparison = compare_metrics(metrics, expected)
    verdict = decide_verdict(comparison)
    license_checks = job.get("license_checks") or {}
    return {
        "verdict": verdict,
        "preset_id": job.get("preset_id", ""),
        "repo_url": job.get("repo_url", ""),
        "repo_license": job.get("requested_license", ""),
        "license_checks": {
            "github_spdx": license_checks.get("github_spdx"),
            "local_spdx": license_checks.get("local_spdx"),
            "effective": license_checks.get("effective"),
        },
        "seed_used": bool(job.get("seed_used")),
        "metrics_observed": metrics,
        "metrics_expected": expected or {},
        "comparison": comparison,
        "metric_source": (preset or {}).get("expected_metrics_source", ""),
        "steps": [
            {
                "index": index + 1,
                "command": str(step.get("command") or "")[:160],
                "exit_code": step.get("exit_code"),
                "timed_out": bool(step.get("timed_out")),
                "duration_s": step.get("duration_s"),
            }
            for index, step in enumerate(steps)
        ],
        "log_tail": str((steps or [{}])[-1].get("log_tail") or "")[-1500:],
        "job_status": job.get("status", ""),
        "job_code": job.get("code"),
        "job_detail": job.get("detail"),
    }


def render_report_markdown(report: dict[str, Any]) -> str:
    """报告 Markdown 渲染（人读版，含判定依据与边界说明）。"""
    verdict = report["verdict"]
    lines: list[str] = [
        f"# 复现报告 · {report['preset_id']}",
        "",
        f"**结论：{verdict}**（由确定性指标比较生成，非 LLM 判定）",
        "",
        f"- 仓库：{report['repo_url']}",
        f"- License：{report['repo_license']}"
        f"（GitHub={report['license_checks'].get('github_spdx')} / "
        f"本地={report['license_checks'].get('local_spdx')}）",
        f"- 种子快照：{'命中（离线确定性）' if report['seed_used'] else '未命中（运行时拉取）'}",
        "",
        "## 指标对比",
        "",
    ]
    if report["metric_source"]:
        lines.append(f"> 期望指标来源：{report['metric_source']}")
        lines.append("")
    if report["comparison"]:
        lines.append("| 指标 | 期望 | 容差 | 实测 | 判定 |")
        lines.append("|---|---|---|---|---|")
        for item in report["comparison"]:
            observed = "未提取到" if item["observed"] is None else f"{item['observed']:.4f}"
            lines.append(
                f"| {item['metric']} | {item['target']} | ±{item['tolerance']} | "
                f"{observed} | {'PASS' if item['pass'] else 'FAIL'} |"
            )
    else:
        lines.append("（该预设未声明期望指标，无法做确定性比较）")
    lines += [
        "",
        "## 执行步骤",
        "",
    ]
    for step in report["steps"]:
        status = "TIMEOUT" if step["timed_out"] else f"exit={step['exit_code']}"
        lines.append(
            f"{step['index']}. `{step['command']}` — {status}，{step['duration_s']}s"
        )
    lines += [
        "",
        "## 日志尾部（最后一步摘要）",
        "",
        "```text",
        report["log_tail"].strip() or "（无日志）",
        "```",
        "",
    ]
    if report["job_status"] != "succeeded":
        lines += [
            f"> 作业终态：{report['job_status']}"
            f"{'（' + str(report['job_code']) + '）' if report.get('job_code') else ''}"
            f"{str(report.get('job_detail') or '')[:200]}",
            "",
        ]
    return "\n".join(lines)


def render_report_json(report: dict[str, Any]) -> str:
    import json

    return json.dumps(report, ensure_ascii=False, indent=2)
