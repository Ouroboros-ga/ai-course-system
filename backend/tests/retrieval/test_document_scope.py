"""
Document scope tests (P1-03).

Verifies:
- RetrievalScope.document() creates a valid document scope.
- Document scope does not collide with course/knowledge_base scopes.
- Missing document scope returns empty (no fallback).
"""

from app.platform.retrieval import RetrievalScope


class TestDocumentScope:
    def test_create_document_scope(self):
        scope = RetrievalScope.document("doc_001")
        assert scope.scope_type == "document"
        assert scope.scope_id == "doc_001"
        assert scope.key == "document:doc_001"

    def test_document_scope_does_not_collide_with_course(self):
        doc = RetrievalScope.document("123")
        course = RetrievalScope.course("123")
        assert doc.key != course.key
        assert doc != course
        assert hash(doc) != hash(course)

    def test_document_scope_does_not_collide_with_knowledge_base(self):
        doc = RetrievalScope.document("123")
        kb = RetrievalScope.knowledge_base("123")
        assert doc.key != kb.key

    def test_document_scope_id_normalized_to_string(self):
        assert RetrievalScope.document(42).scope_id == "42"

    def test_document_scope_frozen(self):
        import pytest
        s = RetrievalScope.document("doc_001")
        with pytest.raises(Exception):
            s.scope_id = "other"  # type: ignore[misc]

    def test_missing_document_scope_returns_empty(self):
        """Missing document scope MUST return empty (no fallback to course)."""
        # This is a contract test: the retrieval gateway returns empty
        # for unknown scopes. The document scope follows the same rule.
        from app.platform.retrieval import retrieval_gateway
        result = retrieval_gateway.retrieve(
            "query", scope=RetrievalScope.document("UNKNOWN")
        )
        assert result == []
