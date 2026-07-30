"""Read-only CodingDiagnosis and bounded student-history adapters."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from app.models.cognitive_state_model import CognitiveState, LearningEvidenceRecord
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
from app.services.coding_eduagent_service import serialize_diagnosis


class SessionScopedCodingDiagnosisPort:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get_latest_diagnosis(
        self, *, student_id: str, course_id: str, run_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        try:
            sid, cid = int(student_id), int(course_id)
        except (TypeError, ValueError):
            return None
        with self._session_factory() as session:
            stmt = select(CodingDiagnosisRecord).where(
                CodingDiagnosisRecord.student_id == sid,
                CodingDiagnosisRecord.course_id == cid,
            )
            if run_id:
                stmt = stmt.where(CodingDiagnosisRecord.run_id == run_id)
            stmt = stmt.order_by(CodingDiagnosisRecord.created_at.desc()).limit(1)
            record = session.exec(stmt).first()
            return serialize_diagnosis(record) if record else None


class SessionScopedStudentHistoryPort:
    """Build a small history snapshot; never returns chat text or source code."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get_history(
        self, *, student_id: str, course_id: str, concept_id: str | None = None,
    ) -> Mapping[str, Any]:
        try:
            sid, cid = int(student_id), int(course_id)
        except (TypeError, ValueError):
            return {"status": "unknown", "reason": "invalid_scope"}
        with self._session_factory() as session:
            state_stmt = select(CognitiveState).where(
                CognitiveState.student_id == sid,
                CognitiveState.course_id == cid,
                CognitiveState.is_latest == True,  # noqa: E712
            )
            if concept_id not in (None, ""):
                try:
                    state_stmt = state_stmt.where(CognitiveState.node_id == int(concept_id))
                except (TypeError, ValueError):
                    pass
            states = list(session.exec(state_stmt).all())[:10]
            evidence_stmt = (
                select(LearningEvidenceRecord)
                .where(
                    LearningEvidenceRecord.student_id == sid,
                    LearningEvidenceRecord.course_id == cid,
                )
                .order_by(LearningEvidenceRecord.created_at.desc())
                .limit(5)
            )
            evidence = list(session.exec(evidence_stmt).all())
            diagnosis_stmt = (
                select(CodingDiagnosisRecord)
                .where(
                    CodingDiagnosisRecord.student_id == sid,
                    CodingDiagnosisRecord.course_id == cid,
                )
                .order_by(CodingDiagnosisRecord.created_at.desc())
                .limit(5)
            )
            diagnoses = list(session.exec(diagnosis_stmt).all())
            return {
                "status": "ready" if states or evidence or diagnoses else "unknown",
                "course_id": cid,
                "student_id": sid,
                "cognitive_states": [
                    {
                        "node_id": state.node_id,
                        "observed_performance_score": state.observed_performance_score,
                        "evidence_confidence": state.evidence_confidence,
                        "confusion_risk": state.confusion_risk,
                        "inquiry_depth": state.inquiry_depth,
                        "hint_dependency": state.hint_dependency,
                        "explanation_need": state.explanation_need,
                        "mastery_level": state.mastery_level,
                        "policy_version": state.policy_version,
                        "evidence_refs": list(state.evidence_refs or []),
                    }
                    for state in states
                ],
                "recent_assessments": [
                    {
                        "evidence_id": item.evidence_id,
                        "node_id": item.node_id,
                        "evidence_type": item.evidence_type,
                        "value": item.value,
                        "confidence": item.confidence,
                        "source": item.source,
                        "policy_version": item.policy_version,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                    for item in evidence
                ],
                "recent_coding_diagnoses": [serialize_diagnosis(item) for item in diagnoses],
            }


def make_session_scoped_coding_ports(session_factory: Callable[[], Session]):
    return SessionScopedCodingDiagnosisPort(session_factory), SessionScopedStudentHistoryPort(session_factory)
