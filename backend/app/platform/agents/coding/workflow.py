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
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from langgraph.graph import END, START, StateGraph

from ..contracts.sandbox import CodeSubmissionPort, CodingDiagnosisPort, SandboxPort
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
    code_submission: Optional[CodeSubmissionPort] = None
    llm: Optional[TeachingLLMPort] = None


def _trace(state: Mapping[str, Any], node: str, **detail: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **detail}]


def _degrade(state: Mapping[str, Any], service: str, code: str) -> dict[str, Any]:
    return {
        "warnings": [*state.get("warnings", []), code],
        "degraded_services": [*state.get("degraded_services", []), service],
    }


_DIAGNOSIS_CONTEXT_FIELDS = (
    "outcome",
    "error_class",
    "line",
    "column",
    "passed_count",
    "total_count",
    "resource_usage",
    "summary",
    "debug_steps",
    "reason_codes",
)


def _sanitize_sandbox_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only non-sensitive execution availability facts in agent state."""
    sanitized: dict[str, Any] = {"available": bool(result.get("available", False))}
    outcome = result.get("outcome") or result.get("status")
    if outcome:
        sanitized["outcome"] = str(outcome)
    resource_usage = result.get("resource_usage")
    if isinstance(resource_usage, Mapping):
        sanitized["resource_usage"] = {
            field: resource_usage.get(field)
            for field in ("cpu_time_ms", "wall_time_ms", "memory_kb")
            if resource_usage.get(field) is not None
        }
    return sanitized


def _llm_diagnosis_context(
    coding_diagnosis: Mapping[str, Any] | None,
    sandbox_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the only execution facts a CodingAgent LLM may receive.

    A persisted ``CodingDiagnosisRecord`` is preferred.  The fallback is
    limited to its own diagnosis summary and resource counters; it never
    forwards source code, artifacts, test details, Judge0 payloads, or the
    learner's free-form message.
    """
    source = coding_diagnosis if isinstance(coding_diagnosis, Mapping) else {}

    context: dict[str, Any] = {}
    for field in _DIAGNOSIS_CONTEXT_FIELDS:
        value = source.get(field)
        if value is not None:
            context[field] = value

    if "outcome" not in context and isinstance(sandbox_result, Mapping):
        outcome = sandbox_result.get("outcome") or sandbox_result.get("status")
        if outcome:
            context["outcome"] = outcome
    if "resource_usage" not in context and isinstance(sandbox_result, Mapping):
        resource_usage = sandbox_result.get("resource_usage")
        if isinstance(resource_usage, Mapping):
            context["resource_usage"] = {
                field: resource_usage.get(field)
                for field in ("cpu_time_ms", "wall_time_ms", "memory_kb")
                if resource_usage.get(field) is not None
            }
    return context


def _normalise_source_fragment(value: str) -> str:
    """Normalise whitespace only for source-echo detection, never storage."""
    return re.sub(r"\s+", "", value)


def _answer_echoes_submission_source(*, answer: str, source_code: str) -> bool:
    """Reject a model response that repeats the private submission.

    CodingAgent may inspect the authorized source to locate an issue, but the
    response becomes product-facing data and can be retained by the
    conversation domain.  Detect the whole source plus meaningful source
    lines after whitespace normalisation; return a source-free rule diagnosis
    instead of attempting to redact an LLM answer in place.
    """
    compact_answer = _normalise_source_fragment(answer)
    compact_source = _normalise_source_fragment(source_code)
    if compact_source and compact_source in compact_answer:
        return True
    return any(
        len(compact_line) >= 3 and compact_line in compact_answer
        for line in source_code.splitlines()
        if (compact_line := _normalise_source_fragment(line))
    )


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
            raw_result = dict(await tools.sandbox.get_execution_result(
                student_id=state["student_id"],
                course_id=state["course_id"],
                code_submission_id=submission_id,
            ))
            result = _sanitize_sandbox_result(raw_result)
            return {
                "sandbox_result": result,
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
                submission_context: dict[str, Any] | None = None
                source_code = ""
                if tools.code_submission is not None:
                    submission = await tools.code_submission.get_submission_for_diagnosis(
                        student_id=state["student_id"],
                        course_id=state["course_id"],
                        run_id=state.get("code_submission_id", ""),
                    )
                    if isinstance(submission, Mapping) and isinstance(submission.get("source_code"), str):
                        source_code = submission["source_code"]
                        submission_context = {
                            "language": str(submission.get("language") or ""),
                            "source_code": source_code,
                        }
                llm_context: dict[str, Any] = {
                    "agent_type": "coding",
                    "diagnosis": _llm_diagnosis_context(
                        state.get("coding_diagnosis"),
                        sandbox_result,
                    ),
                }
                if submission_context is not None:
                    llm_context["submission"] = submission_context
                response = await tools.llm.generate_teaching_response(context={
                    **llm_context,
                })
                answer = response.get("answer") or response.get("content") or ""
                if answer:
                    if source_code and _answer_echoes_submission_source(
                        answer=str(answer), source_code=source_code,
                    ):
                        return {
                            "final_answer": _rule_based_diagnosis(
                                sandbox_result, state.get("coding_diagnosis"),
                            ),
                            "warnings": [*state.get("warnings", []), "SOURCE_ECHO_BLOCKED"],
                            "trace": _trace(
                                state,
                                "generate_diagnosis_response",
                                source="rule_based_source_echo_blocked",
                            ),
                        }
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
    diagnosis = coding_diagnosis if isinstance(coding_diagnosis, Mapping) else {}

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
