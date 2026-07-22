"""Offline Product 1 research tooling; no production adapter or GraphRAG."""

from .fixture_io import FixtureValidationError, validate_fixture
from .bm25 import CourseBM25Retriever
from .mapping import KnowledgePointSlideMapper
from .course_graph import build_snapshot
from .dense import CourseDenseRetriever

__all__ = ["CourseBM25Retriever", "CourseDenseRetriever", "FixtureValidationError", "KnowledgePointSlideMapper", "build_snapshot", "validate_fixture"]
