#!/usr/bin/env python3
"""CS 学科垂类模型评测脚本（挑战杯 XH-202620）。

对任意 OpenAI 兼容的 chat 端点（本地 vLLM / 星火 spark-api-open / 豆包等）
批量运行评测基准（eval_baseline.json），按用例 check 规则判定并输出结果 JSON，
用于对比"基座模型 vs LoRA 微调后模型"。

    python backend/finetune/evaluate.py \
        --base-url https://spark-api-open.xf-yun.com/v1 \
        --api-key $XFYUN_SPARK_API_KEY --model 4.0Ultra \
        --output results_base.json

失败关闭：未配置端点/Key 时明确报错退出（不伪造结果）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

DEFAULT_BASELINE = Path(__file__).resolve().parent / "eval_baseline.json"


def _load_baseline(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _chat_once(base_url: str, api_key: str, model: str, question: str, timeout: float) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "temperature": 0.2,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    return body["choices"][0]["message"]["content"]


def _check(case: dict, output: str) -> dict:
    rule = case.get("check", {})
    kind = rule.get("type", "contains")
    markers = rule.get("markers", [])
    if kind == "judge0_manual":
        passed = None  # 需沙箱人工/服务端验证，不自动判定
        detail = "需 Judge0 沙箱执行验证（人工/服务端），未自动判定"
    else:
        normalized = output
        passed = all(marker in normalized for marker in markers)
        detail = "全部 markers 命中" if passed else f"缺失 markers: {[m for m in markers if m not in normalized]}"
    return {"type": kind, "passed": passed, "detail": detail}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 CS 学科评测基准")
    parser.add_argument("--base-url", required=True, help="OpenAI 兼容端点，如 https://spark-api-open.xf-yun.com/v1")
    parser.add_argument("--api-key", required=True, help="端点 API Key（只作本次调用使用，不写入任何文件）")
    parser.add_argument("--model", required=True, help="模型名，如 4.0Ultra / qwen-turbo")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output", type=Path, default=Path("results.json"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-cases", type=int, default=0, help="0=全部用例")
    args = parser.parse_args()

    baseline = _load_baseline(args.baseline)
    cases = baseline.get("cases", [])
    if args.max_cases > 0:
        cases = cases[: args.max_cases]

    if not cases:
        print("[ERROR] 评测基准无用例", file=sys.stderr)
        return 1

    results = []
    for case in cases:
        print(f"[RUN] {case['id']} {case['category']}: {case['question'][:40]}...")
        try:
            output = _chat_once(args.base_url, args.api_key, args.model, case["question"], args.timeout)
        except Exception as exc:  # noqa: BLE001 —— 网络/端点错误按用例记录失败，不崩溃
            results.append({"id": case["id"], "error": str(exc), "passed": False})
            continue
        check = _check(case, output)
        results.append({"id": case["id"], "category": case["category"], "output": output, **check})

    auto_cases = [r for r in results if r.get("passed") is not None]
    passed = sum(1 for r in auto_cases if r["passed"])
    report = {
        "schema_version": baseline.get("schema_version"),
        "model": args.model,
        "base_url": args.base_url,
        "total": len(results),
        "auto_passed": passed,
        "auto_total": len(auto_cases),
        "manual_pending": len(results) - len(auto_cases),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 自动判定 {passed}/{len(auto_cases)} 通过；人工待验 {report['manual_pending']}；结果写入 {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
