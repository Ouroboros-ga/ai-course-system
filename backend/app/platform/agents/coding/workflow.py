"""Coding Agent workflow: sandbox result → diagnosis → student-friendly response.

The workflow has three nodes:
    1. ``load_sandbox_result`` — read execution result via ``SandboxPort``
    2. ``load_coding_diagnosis`` — read server-side diagnosis via
       ``CodingDiagnosisPort`` (teaching context only, never formal evidence)
    3. ``generate_diagnosis_response`` — produce a student-friendly response

Node 3 uses a rule-based fallback when the LLM is not configured or fails,
so the Coding Agent can always produce a basic diagnosis from the sandbox
result alone. This follows the fail-closed degradation principle.

Governance: the Coding Agent uses prompt-level governance. Sandbox reads and
diagnosis reads are LOW-risk (read-only). Only triggering a new sandbox run
would be HIGH-risk (not implemented in this skeleton).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from langgraph.graph import END, START, StateGraph

from ..contracts.sandbox import CodingDiagnosisPort, SandboxPort
from ..contracts.teaching import TeachingLLMPort

from .state import CodingState

logger = logging.getLogger(__name__)


@dataclass
class CodingTools:
    """Dependencies injected into the Coding Agent workflow.

    ``sandbox`` and ``coding_diagnosis`` are required (the Coding Agent is
    meaningless without sandbox results). ``llm`` is optional — when not
    injected, the workflow uses a rule-based fallback for response generation.
    """

    sandbox: SandboxPort
    coding_diagnosis: Optional[CodingDiagnosisPort] = None
    llm: Optional[TeachingLLMPort] = None


def _trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **detail}]


def _degrade(state: Mapping[str, Any], service: str, code: str) -> dict[str, Any]:
    return {
        "warnings": [*state.get("warnings", []), code],
        "degraded_services": [*state.get("degraded_services", []), service],
    }


def build_coding_workflow(tools: CodingTools):
    """Compile the Coding Agent LangGraph workflow."""

    async def load_sandbox_result(state: CodingState) -> dict[str, Any]:
        """Read the sandbox execution result for the student's submission."""
        submission_id = state.get("code_submission_id", "")
        if not submission_id:
            return {
                "sandbox_result": None,
                "errors": [*state.get("errors", []), "CODING_NO_SUBMISSION_ID"],
                "trace": _trace(state, "load_sandbox_result", skipped=True),
            }
        try:
            result = dict(await tools.sandbox.get_execution_result(
                student_id=state["student_id"],
                course_id=state["course_id"],
                code_submission_id=submission_id,
            ))
            # The sandbox result includes a diagnosis summary if available.
            return {
                "sandbox_result": result,
                "coding_diagnosis": result.get("diagnosis"),
                "trace": _trace(state, "load_sandbox_result", available=result.get("available", False)),
            }
        except Exception as error:  # noqa: BLE001 - degrade
            payload = _degrade(state, "sandbox", "SANDBOX_UNAVAILABLE")
            payload["sandbox_result"] = None
            payload["trace"] = _trace(state, "load_sandbox_result", error=type(error).__name__)
            return payload

    async def load_coding_diagnosis(state: CodingState) -> dict[str, Any]:
        """Load a server-owned, read-only coding diagnosis.

        This is teaching context only. It must never be converted into a
        ``LearningEvidence`` record or modify the cognition state.
        """
        if tools.coding_diagnosis is None:
            return {"trace": _trace(state, "load_coding_diagnosis", skipped=True)}
        submission_id = state.get("code_submission_id", "")
        if not submission_id:
            return {"trace": _trace(state, "load_coding_diagnosis", skipped=True)}
        try:
            diagnosis = await tools.coding_diagnosis.get_latest_diagnosis(
                student_id=state["student_id"],
                course_id=state["course_id"],
                run_id=submission_id,
            )
            return {
                "coding_diagnosis": dict(diagnosis) if diagnosis else state.get("coding_diagnosis"),
                "trace": _trace(state, "load_coding_diagnosis", available=diagnosis is not None),
            }
        except Exception as error:  # noqa: BLE001 - degrade
            payload = _degrade(state, "coding_diagnosis", "CODING_DIAGNOSIS_UNAVAILABLE")
            payload["trace"] = _trace(state, "load_coding_diagnosis", error=type(error).__name__)
            return payload

    async def generate_diagnosis_response(state: CodingState) -> dict[str, Any]:
        """Produce a student-friendly diagnosis response.

        LLM-based when configured; rule-based fallback otherwise. The
        fallback derives a basic diagnosis from the sandbox result's
        outcome, compile status, and test pass rate.
        """
        sandbox_result = state.get("sandbox_result")
        if sandbox_result is None or not sandbox_result.get("available"):
            answer = (
                "未能获取代码运行结果。请确认已提交代码并等待沙箱执行完成后再试。"
            )
            return {
                "final_answer": answer,
                "status": "no_sandbox_result",
                "trace": _trace(state, "generate_diagnosis_response", source="fallback_no_result"),
            }

        # Try LLM-based diagnosis when configured.
        if tools.llm is not None:
            try:
                diagnosis = state.get("coding_diagnosis") or {}
                safe_diagnosis = {
                    key: diagnosis.get(key)
                    for key in ("outcome", "error_class", "line", "summary", "debug_steps", "reason_codes")
                }
                safe_sandbox = {
                    "outcome": sandbox_result.get("outcome"),
                    "diagnosis": {
                        key: (sandbox_result.get("diagnosis") or {}).get(key)
                        for key in ("compile_ok", "passed_count", "total_count", "score", "error_code")
                    },
                    "resource_usage": sandbox_result.get("resource_usage") or {},
                }
                response = await tools.llm.generate_teaching_response(context={
                    "agent_type": "coding",
                    "sandbox_result": safe_sandbox,
                    "coding_diagnosis": safe_diagnosis,
                    "instruction": "只解释已脱敏诊断，不索取或复述源码、测试输入输出、隐藏测试或 Judge0 数据。",
                })
                answer = response.get("answer") or response.get("content") or ""
                if answer:
                    return {
                        "final_answer": answer,
                        "trace": _trace(state, "generate_diagnosis_response", source="llm"),
                    }
            except Exception as error:  # noqa: BLE001 - fall through to rule-based
                logger.warning("CodingAgent: LLM diagnosis failed: %s: %s", type(error).__name__, error)

        # Rule-based fallback: derive a basic diagnosis from the sandbox result.
        answer = _rule_based_diagnosis(sandbox_result, state.get("coding_diagnosis"))
        return {
            "final_answer": answer,
            "trace": _trace(state, "generate_diagnosis_response", source="rule_based"),
        }

    graph = StateGraph(CodingState)
    graph.add_node("load_sandbox_result", load_sandbox_result)
    graph.add_node("load_coding_diagnosis", load_coding_diagnosis)
    graph.add_node("generate_diagnosis_response", generate_diagnosis_response)
    graph.add_edge(START, "load_sandbox_result")
    graph.add_edge("load_sandbox_result", "load_coding_diagnosis")
    graph.add_edge("load_coding_diagnosis", "generate_diagnosis_response")
    graph.add_edge("generate_diagnosis_response", END)
    return graph.compile()


def _rule_based_diagnosis(
    sandbox_result: dict[str, Any],
    coding_diagnosis: dict[str, Any] | None,
) -> str:
    """Derive a basic student-friendly diagnosis from the sandbox result.

    This is intentionally simple — it summarizes the outcome, compile status,
    and test pass rate without exposing internal sandbox details.
    """
    outcome = sandbox_result.get("outcome") or sandbox_result.get("status") or "unknown"
    diagnosis = coding_diagnosis or sandbox_result.get("diagnosis") or {}

    parts: list[str] = []

    if outcome in ("passed", "success", "accepted"):
        parts.append("代码运行通过。")
    elif outcome in ("compile_error", "compilation_failed"):
        parts.append("代码编译失败，请检查语法错误。")
    elif outcome in ("runtime_error", "runtime_failed"):
        parts.append("代码在运行时出错，请检查数组越界、空指针等常见问题。")
    elif outcome in ("wrong_answer", "test_failed"):
        parts.append("代码运行完成但未通过全部测试用例。")
    elif outcome in ("timeout", "time_limit_exceeded"):
        parts.append("代码运行超时，请优化算法效率。")
    else:
        parts.append(f"代码运行状态：{outcome}。")

    compile_ok = diagnosis.get("compile_ok")
    if compile_ok is False:
        compile_msg = diagnosis.get("compile_message", "")
        if compile_msg:
            parts.append(f"编译错误信息：{compile_msg[:200]}")

    passed = diagnosis.get("passed_count")
    total = diagnosis.get("total_count")
    if passed is not None and total is not None and total > 0:
        parts.append(f"测试通过：{passed}/{total}。")
        if passed < total:
            error_code = diagnosis.get("error_code", "")
            if error_code:
                parts.append(f"错误类型：{error_code}。")

    score = diagnosis.get("score")
    if score is not None:
        parts.append(f"得分：{score}。")

    return " ".join(parts) if parts else "代码诊断完成，但未获得详细信息。"
