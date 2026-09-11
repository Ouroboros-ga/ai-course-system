"""CodingEduAgent baseline: deterministic diagnosis over verified run data.

This service is intentionally independent from the LLM.  A later constrained
LLM explainer may enrich the returned text, but it cannot change the outcome,
scope, score, or formal-evidence boundary established here.

职责切分（PR-06）：判定规则已移入 ``domain/oj/intelligence/``。本模块只负责
**查库 + ORM 适配 + 持久化**，不再持有判定逻辑与文案。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session, select

from app.domain.oj.intelligence import (
    DiagnosisInput,
    classify_run,
    confidence_for,
    debug_steps_for,
    hints_for,
    line_from_text,
    normalize_outcome,
)
from app.domain.oj.intelligence.rules import DIAGNOSIS_POLICY_VERSION
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
from app.models.experiment_model import ExperimentRun
from app.models.experiment_model import ExperimentRunArtifact


def _outcome_value(run: ExperimentRun) -> str:
    """兼容壳：保留原签名供既有调用方使用，逻辑委托域函数。"""
    return normalize_outcome(run.outcome)


def _artifact_texts(artifacts: list[ExperimentRunArtifact]) -> tuple[str, ...]:
    """只取 `stderr` / `compile` 两类 artifact 的正文——判定文本的唯一来源。

    这个筛选是**业务侧的决定**（哪类 artifact 算证据），因此留在 service；
    域层只接收筛好的文本。
    """
    return tuple(a.content or "" for a in artifacts if a.artifact_type in {"stderr", "compile"})


def _diagnosis_input(run: ExperimentRun, artifacts: list[ExperimentRunArtifact]) -> DiagnosisInput:
    """ORM → 域输入的适配。域层因此不必知道 SQLModel 的存在。"""
    return DiagnosisInput(
        outcome=normalize_outcome(run.outcome),
        error_code=run.error_code or "",
        error_message=run.error_message or "",
        compile_message=run.compile_message or "",
        runtime_message=run.runtime_message or "",
        artifacts=_artifact_texts(artifacts),
    )


def _classify(run: ExperimentRun, artifacts: list[ExperimentRunArtifact]) -> tuple[str, str, list[str]]:
    """兼容壳：保留原签名，委托域规则。"""
    return classify_run(_diagnosis_input(run, artifacts))


def _debug_steps(error_class: str) -> list[str]:
    """兼容壳：保留原签名，委托域规则。"""
    return debug_steps_for(error_class)


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
        data = _diagnosis_input(run, artifacts)
        error_class, summary, reasons = classify_run(data)
        line = line_from_text(
            data.compile_message,
            data.runtime_message,
            *data.artifacts,
        )
        outcome = data.outcome
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
            debug_steps=debug_steps_for(error_class),
            hints=hints_for(error_class),
            confidence=confidence_for(outcome),
            evidence_refs=[f"experiment_run:{run_id}"],
            reason_codes=reasons,
            policy_version=DIAGNOSIS_POLICY_VERSION,
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
