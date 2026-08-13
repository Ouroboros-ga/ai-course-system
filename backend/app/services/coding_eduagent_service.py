"""CodingEduAgent baseline: deterministic diagnosis over verified run data.

This service is intentionally independent from the LLM.  A later constrained
LLM explainer may enrich the returned text, but it cannot change the outcome,
scope, score, or formal-evidence boundary established here.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Mapping

from sqlmodel import Session, select

from app.models.coding_diagnosis_model import (
    CODING_DIAGNOSIS_POLICY_VERSION,
    CodingDiagnosisRecord,
)
from app.models.experiment_model import ExperimentRun
from app.models.experiment_model import ExperimentRunArtifact


_LINE_RE = re.compile(r"(?:line|行)\s*[:=]?\s*(\d+)", re.IGNORECASE)


def _outcome_value(run: ExperimentRun) -> str:
    value = getattr(run.outcome, "value", run.outcome)
    return str(value or "unknown")


def _classify(run: ExperimentRun, artifacts: list[ExperimentRunArtifact]) -> tuple[str, str, list[str]]:
    outcome = _outcome_value(run)
    text = " ".join(
        [run.error_code or "", run.error_message or "", run.compile_message or "", run.runtime_message or ""]
        + [a.content or "" for a in artifacts if a.artifact_type in {"stderr", "compile"}]
    ).lower()
    if outcome == "compilation_error":
        if any(token in text for token in ("syntax", "indent", "parse", "语法", "缩进")):
            return "syntax", "编译阶段发现语法或缩进问题。", ["COMPILE_ERROR", "SYNTAX_LIKE"]
        return "compile", "代码未能通过编译或解释器检查。", ["COMPILE_ERROR"]
    if outcome == "runtime_error":
        if any(token in text for token in ("indexerror", "out of range", "越界")):
            return "runtime", "运行时访问了不存在的索引或元素。", ["RUNTIME_ERROR", "INDEX_LIKE"]
        if any(token in text for token in ("zerodivision", "division by zero", "除零")):
            return "runtime", "运行时发生除零错误。", ["RUNTIME_ERROR", "DIVISION_BY_ZERO"]
        return "runtime", "程序运行过程中抛出了错误。", ["RUNTIME_ERROR"]
    if outcome == "wrong_answer":
        return "logic", "程序可以运行，但输出与测试预期不一致。", ["WRONG_ANSWER", "CHECK_LOGIC"]
    if outcome == "time_limit_exceeded":
        return "complexity", "程序超过了本题的时间限制。", ["TIME_LIMIT", "CHECK_COMPLEXITY"]
    if outcome == "memory_limit_exceeded":
        return "complexity", "程序超过了本题的内存限制。", ["MEMORY_LIMIT", "CHECK_SPACE"]
    if outcome == "accepted":
        return "none", "本次运行通过了可见的评分检查。", ["ACCEPTED"]
    if outcome == "sandbox_unavailable":
        return "environment", "代码沙箱暂不可用，本次没有形成有效执行证据。", ["SANDBOX_UNAVAILABLE"]
    return "unknown", "当前运行结果不足以形成可靠的代码诊断。", ["INSUFFICIENT_EXECUTION_EVIDENCE"]


def _debug_steps(error_class: str) -> list[str]:
    return {
        "syntax": ["先查看编译器指出的行附近代码", "检查括号、缩进、关键字和语句结束符", "修复一个最小问题后重新运行"],
        "compile": ["确认语言版本和入口函数符合题目要求", "阅读第一条编译错误而不是后续连锁错误", "用最小代码片段重新提交"],
        "runtime": ["用最小输入复现错误", "检查边界条件和变量初始化", "逐步打印关键中间状态后重新运行"],
        "logic": ["找一个最小反例", "手工对照题目要求执行关键分支", "检查循环边界、状态更新和返回值"],
        "complexity": ["估算主要循环或递归的时间复杂度", "检查是否重复计算相同子问题", "再评估额外数据结构带来的空间开销"],
        "environment": ["稍后重试沙箱执行", "不要把未执行的结果当成通过或失败", "确认课程沙箱状态后再提交"],
        "none": ["可以查看隐藏边界条件并尝试解释每一步", "如需提升难度，请请求下一道课程练习"],
    }.get(error_class, ["等待一次有效执行结果后再诊断", "不要根据猜测修改多个地方", "保留最小复现样例"])


class CodingEduAgent:
    """Build and persist a bounded diagnosis from server-owned run records."""

    def diagnose_run(self, session: Session, *, course_id: int, student_id: int, run_id: str) -> CodingDiagnosisRecord:
        run = session.exec(
            select(ExperimentRun).where(
                ExperimentRun.run_id == run_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            )
        ).first()
        if run is None:
            raise ValueError("run_not_found_or_scope_mismatch")
        existing = session.exec(select(CodingDiagnosisRecord).where(CodingDiagnosisRecord.run_id == run_id)).first()
        if existing is not None:
            return existing
        artifacts = list(session.exec(select(ExperimentRunArtifact).where(ExperimentRunArtifact.run_id == run_id)).all())
        error_class, summary, reasons = _classify(run, artifacts)
        location = _LINE_RE.search(" ".join([run.compile_message or "", run.runtime_message or ""] + [a.content or "" for a in artifacts]))
        line = int(location.group(1)) if location else None
        outcome = _outcome_value(run)
        confidence = 0.95 if outcome in {"accepted", "compilation_error", "runtime_error", "wrong_answer", "time_limit_exceeded", "memory_limit_exceeded"} else 0.35
        diagnosis = CodingDiagnosisRecord(
            diagnosis_id="cd_" + uuid.uuid4().hex,
            run_id=run_id,
            course_id=course_id,
            student_id=student_id,
            status="ready" if outcome != "sandbox_unavailable" else "insufficient_evidence",
            outcome=outcome,
            error_class=error_class,
            line=line,
            summary=summary,
            debug_steps=_debug_steps(error_class),
            hints=[{"level": "concept", "text": step, "full_solution": False} for step in _debug_steps(error_class)[:2]],
            confidence=confidence,
            evidence_refs=[f"experiment_run:{run_id}"],
            reason_codes=reasons,
            policy_version=CODING_DIAGNOSIS_POLICY_VERSION,
            generated_by="coding-rules",
        )
        session.add(diagnosis)
        session.flush()
        return diagnosis


coding_eduagent = CodingEduAgent()


def build_rule_explanation(record: CodingDiagnosisRecord) -> dict[str, Any]:
    """Build product feedback from a bounded diagnosis record only.

    This deliberately accepts ``CodingDiagnosisRecord`` rather than an
    ``ExperimentRun`` or sandbox payload.  The public explanation endpoint
    must not re-open source code, artifacts, hidden cases, or Judge0 output
    after the deterministic diagnosis has been persisted.
    """
    return {
        "run_id": record.run_id,
        "outcome": record.outcome,
        "error_class": record.error_class,
        "summary": record.summary,
        "next_steps": list(record.debug_steps or []),
        "reason_codes": list(record.reason_codes or []),
        "source": "coding-rules",
    }


def serialize_diagnosis(record: CodingDiagnosisRecord) -> dict[str, Any]:
    return {
        "diagnosis_id": record.diagnosis_id,
        "run_id": record.run_id,
        "course_id": record.course_id,
        "student_id": record.student_id,
        "status": record.status,
        "outcome": record.outcome,
        "error_class": record.error_class,
        "line": record.line,
        "column": record.column,
        "summary": record.summary,
        "debug_steps": list(record.debug_steps or []),
        "hints": list(record.hints or []),
        "confidence": record.confidence,
        "evidence_refs": list(record.evidence_refs or []),
        "reason_codes": list(record.reason_codes or []),
        "policy_version": record.policy_version,
        "generated_by": record.generated_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
