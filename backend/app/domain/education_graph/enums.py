"""Controlled ontology: schema-constrained entity and relation types.

Every new type must be added here (enum) before it can appear in any
candidate, node, or edge.  This is the single source of truth for the
education graph ontology version ``edu-graph/1.0``.
"""
from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# Ontology version
# ---------------------------------------------------------------------------

ONTOLOGY_VERSION = "edu-graph/1.0"


# ---------------------------------------------------------------------------
# EducationalUnit types (deterministic hierarchy)
# ---------------------------------------------------------------------------


class EducationalUnitType(str, Enum):
    """Types of educational structural units.

    These are the deterministic backbone of the graph: they come from the
    DocumentIR / curriculum definition, not from LLM extraction.
    """

    COURSE = "course"
    CHAPTER = "chapter"
    SECTION = "section"
    PAGE = "page"
    SOURCE_BLOCK = "source_block"


# ---------------------------------------------------------------------------
# Node types (schema-constrained)
# ---------------------------------------------------------------------------


class NodeType(str, Enum):
    """All permitted node types in the education graph.

    Based on R2D0 ontology SS2 with adjustments for evidence-backed design.
    """

    # Structural (deterministic)
    COURSE = "course"
    CHAPTER = "chapter"
    SECTION = "section"
    PAGE = "page"
    SOURCE_BLOCK = "source_block"

    # Semantic (candidate-extracted, must have evidence to be accepted)
    KNOWLEDGE_POINT = "knowledge_point"
    CONCEPT = "concept"
    DEFINITION = "definition"
    FORMULA = "formula"
    THEOREM = "theorem"
    METHOD = "method"
    SKILL = "skill"
    EXAMPLE = "example"
    EXERCISE = "exercise"
    MISCONCEPTION = "misconception"
    LEARNING_OBJECTIVE = "learning_objective"


# ---------------------------------------------------------------------------
# Relation types (type-matrix constrained)
# ---------------------------------------------------------------------------


class RelationType(str, Enum):
    """All permitted edge types.

    ``CONTAINS`` / ``PART_OF`` are structural (deterministic from hierarchy).
    All others are semantic (candidate-extracted, need evidence).

    Reference: R2D0 ontology SS3 type matrix.
    """

    # Structural
    CONTAINS = "contains"
    PART_OF = "part_of"

    # Semantic
    DEFINES = "defines"
    EXPLAINS = "explains"
    PREREQUISITE_OF = "prerequisite_of"
    DERIVES_FROM = "derives_from"
    USES = "uses"
    USES_FORMULA = "uses_formula"
    HAS_EXAMPLE = "has_example"
    TESTS = "tests"
    CONTRASTS_WITH = "contrasts_with"
    CAUSES = "causes"
    RELATED_TO = "related_to"
    SUPPORTED_BY = "supported_by"
    APPEARS_ON = "appears_on"


# ---------------------------------------------------------------------------
# Review status (state machine)
# ---------------------------------------------------------------------------


class ReviewStatus(str, Enum):
    """Lifecycle status for graph nodes, edges, and snapshots.

    State machine:
        proposed -> accepted          (auto or teacher-approved)
        proposed -> needs_review      (conflict, low confidence, cycle)
        proposed -> rejected          (hard constraint violation)
        needs_review -> accepted      (teacher approves)
        needs_review -> rejected      (teacher rejects)
        accepted -> superseded        (new snapshot replaces, audit retained)
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    SUPERSEDED = "superseded"
