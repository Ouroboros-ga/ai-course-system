"""Read-only CodingDiagnosis and bounded student-history adapters."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from sqlmodel import Session, select

from app.models.cognitive_state_model import CognitiveState, LearningEvidenceRecord
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
from app.models.experiment_model import ExperimentAttempt, ExperimentDefinition, ExperimentRun
from app.models.graph_production_model import CourseKnowledgeNode
from app.services.coding_eduagent_service import serialize_diagnosis


_SOURCE_READABLE_OUTCOMES = {
    "accepted",
    "wrong_answer",
    "time_limit_exceeded",
    "memory_limit_exceeded",
    "runtime_error",
    "compilation_error",
}


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
            return _serialize_with_learning_signal(session, record) if record else None


def _mapped_knowledge_node_ids(
    session: Session,
    *,
    record: CodingDiagnosisRecord,
) -> list[int]:
    """Resolve only explicit, course-owned experiment knowledge-node mappings."""
    run = session.exec(select(ExperimentRun).where(
        ExperimentRun.run_id == record.run_id,
        ExperimentRun.course_id == record.course_id,
        ExperimentRun.student_id == record.student_id,
    )).first()
    if run is None:
        return []
    # A diagnosis can outlive a purged experiment run.  Treat an incomplete
    # mapping as absent rather than letting a historical diagnosis lookup fail.
    run_attempt_id = getattr(run, "attempt_id", None)
    if not isinstance(run_attempt_id, str) or not run_attempt_id:
        return []
    attempt = session.exec(select(ExperimentAttempt).where(
        ExperimentAttempt.attempt_id == run_attempt_id,
        ExperimentAttempt.course_id == record.course_id,
        ExperimentAttempt.student_id == record.student_id,
    )).first()
    if attempt is None:
        return []
    attempt_experiment_id = getattr(attempt, "experiment_id", None)
    if not isinstance(attempt_experiment_id, str) or not attempt_experiment_id:
        return []
    definition = session.exec(select(ExperimentDefinition).where(
        ExperimentDefinition.experiment_id == attempt_experiment_id,
        ExperimentDefinition.course_id == record.course_id,
    )).first()
    if definition is None:
        return []
    candidate_ids = [
        node_id for node_id in (definition.knowledge_node_ids or [])
        if isinstance(node_id, int) and not isinstance(node_id, bool)
    ]
    if not candidate_ids:
        return []
    existing_ids = set(session.exec(select(CourseKnowledgeNode.id).where(
        CourseKnowledgeNode.course_id == record.course_id,
        CourseKnowledgeNode.id.in_(candidate_ids),
    )).all())
    return [node_id for node_id in candidate_ids if node_id in existing_ids]


def _serialize_with_learning_signal(
    session: Session,
    record: CodingDiagnosisRecord,
) -> dict[str, Any]:
    """Attach bounded teaching context without modifying the diagnosis record.

    The signal is a cross-agent contract: it contains the error pattern,
    explicitly mapped concepts, and next actions but deliberately excludes
    source, execution artifacts, hidden cases, and free-form student input.
    """
    payload = serialize_diagnosis(record)
    recent_same_error = list(session.exec(select(CodingDiagnosisRecord).where(
        CodingDiagnosisRecord.course_id == record.course_id,
        CodingDiagnosisRecord.student_id == record.student_id,
        CodingDiagnosisRecord.error_class == record.error_class,
    ).order_by(CodingDiagnosisRecord.created_at.desc()).limit(5)).all())
    count = len(recent_same_error)
    payload["learning_signal"] = {
        "schema_version": "coding-learning-signal/1",
        "run_id": record.run_id,
        "outcome": record.outcome,
        "error_class": record.error_class,
        "knowledge_node_ids": _mapped_knowledge_node_ids(session, record=record),
        "repeated_error": {
            "error_class": record.error_class,
            "recent_count": count,
            "is_repeated": count >= 2,
        },
        "recommended_actions": list(record.debug_steps or [])[:3],
        "evidence_refs": list(record.evidence_refs or []),
    }
    return payload


class SessionScopedCodeSubmissionPort:
    """Read one student's submitted source exclusively for CodingAgent.

    This provider is intentionally separate from diagnosis/history adapters so
    the latter cannot accidentally gain access to source code.  The returned
    mapping is purpose-limited to the local CodingAgent LLM call.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def get_submission_for_diagnosis(
        self, *, student_id: str, course_id: str, run_id: str,
    ) -> Mapping[str, Any] | None:
        try:
            sid, cid = int(student_id), int(course_id)
        except (TypeError, ValueError):
            return None
        if not run_id:
            return None
        with self._session_factory() as session:
            run = session.exec(select(ExperimentRun).where(
                ExperimentRun.run_id == run_id,
                ExperimentRun.student_id == sid,
                ExperimentRun.course_id == cid,
            )).first()
            if run is None:
                return None
            outcome = str(getattr(run.outcome, "value", run.outcome))
            if outcome not in _SOURCE_READABLE_OUTCOMES:
                return None
            return {
                "run_id": run.run_id,
                "language": run.language,
                "source_code": run.source_code,
            }


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
                "recent_coding_diagnoses": [
                    _serialize_with_learning_signal(session, item)
                    for item in diagnoses
                ],
            }


def make_session_scoped_coding_ports(session_factory: Callable[[], Session]):
    return SessionScopedCodingDiagnosisPort(session_factory), SessionScopedStudentHistoryPort(session_factory)


def make_session_scoped_code_submission_port(
    session_factory: Callable[[], Session],
) -> SessionScopedCodeSubmissionPort:
    return SessionScopedCodeSubmissionPort(session_factory)
