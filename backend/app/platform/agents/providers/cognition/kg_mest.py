"""Read-only TeachingAgent port for a precomputed KG-MEST Shadow report.

This is the production-side boundary for the research algorithm. It consumes
an already-approved local report supplied by an application composition root;
it does not import research modules, open a database, execute a bundle, or
write student state. The port is bound to one student and course.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_CONFIDENCE = {"unknown": 0.0, "low": 0.25, "medium": 0.65, "high": 0.90}


@dataclass(frozen=True)
class KGMetShadowReportStudentModelingPort:
    """Expose a bounded report through the existing ``StudentModelingPort``."""

    expected_student_id: str
    expected_course_id: str
    report: Mapping[str, Any]

    @classmethod
    def from_report(
        cls, *, expected_student_id: str, expected_course_id: str, report: Mapping[str, Any],
    ) -> "KGMetShadowReportStudentModelingPort":
        if report.get("status") != "ok":
            raise ValueError("KG-MEST Shadow report is not an accepted read-only result")
        if str(report.get("course_key", "")) != expected_course_id:
            raise ValueError("KG-MEST Shadow report course does not match the injected runtime scope")
        if not isinstance(report.get("states"), Mapping) or not isinstance(report.get("recommendations"), Mapping):
            raise ValueError("KG-MEST Shadow report has no consumable states or recommendations")
        return cls(str(expected_student_id), str(expected_course_id), report)

    async def get_concept_state(self, *, student_id: str, course_id: str, concept_id: str) -> Mapping[str, Any]:
        if not self._in_scope(student_id, course_id):
            return _unknown_state("KG_MEST_SHADOW_SCOPE_MISMATCH")
        raw = self.report["states"].get(concept_id)
        if not isinstance(raw, Mapping):
            return _unknown_state("KG_MEST_SHADOW_CONCEPT_UNAVAILABLE")
        values = raw.get("values") if isinstance(raw.get("values"), Mapping) else {}
        confidence = raw.get("confidence", "unknown")
        return {
            "mastery_score": raw.get("observed_performance_score"),
            "confidence": _CONFIDENCE.get(str(confidence), 0.0),
            "repeated_error_risk": values.get("recurring_error_risk"),
            "hint_dependency": values.get("hint_dependency"),
            "transfer_score": values.get("transfer"),
            "state_status": raw.get("status", "unknown"),
            "evidence_refs": tuple(raw.get("evidence_refs", ())),
            "reason_codes": tuple(raw.get("reason_codes", ())),
            "policy_versions": dict(raw.get("policy_versions", {})),
            "data_version": raw.get("data_version"),
        }

    async def get_weak_concepts(self, *, student_id: str, course_id: str) -> list[Mapping[str, Any]]:
        if not self._in_scope(student_id, course_id):
            return []
        weak: dict[str, Mapping[str, Any]] = {}
        for items in self.report["recommendations"].values():
            if not isinstance(items, (list, tuple)):
                continue
            for item in items:
                if not isinstance(item, Mapping) or item.get("action_type") != "review_confirmed_weak_prerequisite":
                    continue
                concept_id = str(item.get("concept_id", ""))
                if concept_id:
                    weak.setdefault(concept_id, {
                        "concept_id": concept_id,
                        "evidence_refs": tuple(item.get("evidence_refs", ())),
                        "reason_codes": tuple(item.get("reason_codes", ())),
                        "policy_version": item.get("policy_version"),
                    })
        return [weak[concept_id] for concept_id in sorted(weak)]

    def _in_scope(self, student_id: str, course_id: str) -> bool:
        return str(student_id) == self.expected_student_id and str(course_id) == self.expected_course_id


def _unknown_state(reason_code: str) -> Mapping[str, Any]:
    return {
        "mastery_score": None, "confidence": 0.0, "repeated_error_risk": None,
        "hint_dependency": None, "transfer_score": None, "state_status": "unavailable",
        "evidence_refs": (), "reason_codes": (reason_code,), "policy_versions": {}, "data_version": None,
    }
