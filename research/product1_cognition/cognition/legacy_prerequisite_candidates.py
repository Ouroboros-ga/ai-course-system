"""Read-only bridge from legacy knowledge relations to reviewable candidates.

The legacy ``KnowledgeRelation`` table has neither course scope nor pedagogical
evidence/review metadata.  Its ``prerequisite`` rows can help a curator locate
candidate edges, but they are not an accepted teaching graph and must never be
fed to path recommendation as if they were one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class LegacyPrerequisiteCandidate:
    """A provenance-preserving relation that still requires human acceptance."""

    candidate_id: str
    subject_node_id: str
    object_node_id: str
    predicate: str
    course_id: str
    source_snapshot_version: str
    legacy_relation_id: str
    requires_human_review: bool = True

    def as_graph_edge(self) -> dict[str, Any]:
        """Export the candidate without giving it an accepted graph status."""
        return {
            "candidate_id": self.candidate_id,
            "subject_node_id": self.subject_node_id,
            "object_node_id": self.object_node_id,
            "predicate": self.predicate,
            "course_id": self.course_id,
            "status": "candidate",
            "source_snapshot_version": self.source_snapshot_version,
            "evidence_refs": (f"legacy_knowledge_relation:{self.legacy_relation_id}",),
            "reason_codes": ("LEGACY_PREREQUISITE_CANDIDATE_REQUIRES_REVIEW",),
            "requires_human_review": True,
        }


@dataclass(frozen=True)
class LegacyCandidateBuildResult:
    status: str
    candidates: tuple[LegacyPrerequisiteCandidate, ...]
    error_codes: tuple[str, ...]


def build_legacy_prerequisite_candidates(
    *,
    course_key: str,
    source_snapshot_version: str,
    knowledge_points: list[Mapping[str, Any]],
    relations: list[Mapping[str, Any]],
) -> LegacyCandidateBuildResult:
    """Build deterministic *candidate* edges from a read-only enriched snapshot.

    Callers must add ``course_id`` while exporting the legacy rows.  This is an
    explicit security boundary: the historical table alone only identifies a
    knowledge base, not a course.  A malformed or cross-course batch is wholly
    rejected rather than silently dropping unsafe rows.
    """
    point_ids: dict[str, str] = {}
    errors: set[str] = set()
    for point in knowledge_points:
        legacy_id = point.get("id")
        node_id = point.get("point_id")
        if legacy_id is None or not node_id:
            errors.add("LEGACY_KNOWLEDGE_POINT_IDENTITY_MISSING")
            continue
        if point.get("course_id") != course_key:
            errors.add("LEGACY_KNOWLEDGE_POINT_COURSE_SCOPE_MISMATCH")
            continue
        point_ids[str(legacy_id)] = str(node_id)

    candidates: list[LegacyPrerequisiteCandidate] = []
    for relation in relations:
        if str(relation.get("relation_type") or "") != "prerequisite":
            continue
        relation_id = relation.get("id")
        source_id = relation.get("source_id")
        target_id = relation.get("target_id")
        if relation.get("course_id") != course_key:
            errors.add("LEGACY_PREREQUISITE_COURSE_SCOPE_MISMATCH")
            continue
        if relation_id is None or source_id is None or target_id is None:
            errors.add("LEGACY_PREREQUISITE_IDENTITY_MISSING")
            continue
        source_node = point_ids.get(str(source_id))
        target_node = point_ids.get(str(target_id))
        if not source_node or not target_node:
            errors.add("LEGACY_PREREQUISITE_DANGLING_OR_UNSCOPED")
            continue
        candidates.append(
            LegacyPrerequisiteCandidate(
                candidate_id=f"legacy-prerequisite:{relation_id}",
                subject_node_id=source_node,
                object_node_id=target_node,
                predicate="PREREQUISITE_OF",
                course_id=course_key,
                source_snapshot_version=source_snapshot_version,
                legacy_relation_id=str(relation_id),
            )
        )

    if errors:
        return LegacyCandidateBuildResult("rejected", (), tuple(sorted(errors)))
    return LegacyCandidateBuildResult(
        "candidate",
        tuple(sorted(candidates, key=lambda item: (item.subject_node_id, item.object_node_id, item.candidate_id))),
        (),
    )
