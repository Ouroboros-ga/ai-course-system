"""
Retrieval provider contract tests (P1-03) — BM25, vector, fusion (RRF), rerank.

Verifies:
- BM25Provider protocol compliance (FakeBM25Provider).
- VectorProvider protocol compliance (FakeVectorProvider).
- RRF fusion correctly combines sparse + dense results.
- RerankerProvider protocol compliance (FakeRerankerProvider).
- Evidence IDs are preserved through fusion and reranking.
- Missing scope returns empty (no fallback).
- Provider isolation: different scopes don't leak.
"""

import pytest

from app.platform.retrieval import RetrievalScope
from app.platform.retrieval.providers.contracts import (
    FakeBM25Provider,
    FakeRerankerProvider,
    FakeVectorProvider,
    FusionConfig,
    rrf_fuse,
)
from app.platform.retrieval.schemas import RetrievedChunk


DOCS_A = [
    "机器学习是人工智能的重要分支",
    "监督学习需要标注数据用于分类与回归",
    "准确率召回率与F1分数是常用评估指标",
]

DOCS_B = [
    "深度学习是机器学习的子领域",
    "神经网络是深度学习的核心结构",
    "反向传播算法用于训练神经网络",
]

QUERY_ML = "机器学习"
QUERY_DL = "深度学习"


@pytest.fixture
def bm25():
    return FakeBM25Provider()


@pytest.fixture
def vector():
    return FakeVectorProvider()


@pytest.fixture
def reranker():
    return FakeRerankerProvider()


# =====================================================================
# BM25 Provider
# =====================================================================


class TestBM25Provider:
    def test_index_and_retrieve(self, bm25):
        scope = RetrievalScope.course("A")
        bm25.index(scope, DOCS_A)
        assert bm25.has_scope(scope) is True
        results = bm25.retrieve(QUERY_ML, scope=scope, top_k=3)
        assert len(results) >= 1
        assert all(isinstance(c, RetrievedChunk) for c in results)
        assert all(c.retrieval_source == "bm25" for c in results)

    def test_missing_scope_returns_empty(self, bm25):
        scope = RetrievalScope.course("A")
        bm25.index(scope, DOCS_A)
        results = bm25.retrieve(QUERY_ML, scope=RetrievalScope.course("UNKNOWN"), top_k=3)
        assert results == []

    def test_empty_query_returns_empty(self, bm25):
        scope = RetrievalScope.course("A")
        bm25.index(scope, DOCS_A)
        assert bm25.retrieve("", scope=scope) == []
        assert bm25.retrieve("   ", scope=scope) == []

    def test_clear_scope(self, bm25):
        scope = RetrievalScope.course("A")
        bm25.index(scope, DOCS_A)
        assert bm25.clear_scope(scope) is True
        assert bm25.has_scope(scope) is False
        assert bm25.clear_scope(scope) is False

    def test_course_isolation(self, bm25):
        bm25.index(RetrievalScope.course("A"), DOCS_A)
        bm25.index(RetrievalScope.course("B"), DOCS_B)
        results = bm25.retrieve(QUERY_DL, scope=RetrievalScope.course("A"), top_k=3)
        # Course A doesn't have deep learning content
        assert len(results) == 0


# =====================================================================
# Vector Provider
# =====================================================================


class TestVectorProvider:
    def test_index_and_retrieve(self, vector):
        scope = RetrievalScope.course("A")
        vector.index(scope, DOCS_A)
        assert vector.has_scope(scope) is True
        results = vector.retrieve(QUERY_ML, scope=scope, top_k=3)
        assert len(results) >= 1
        assert all(c.retrieval_source == "vector" for c in results)

    def test_missing_scope_returns_empty(self, vector):
        vector.index(RetrievalScope.course("A"), DOCS_A)
        results = vector.retrieve(QUERY_ML, scope=RetrievalScope.course("UNKNOWN"), top_k=3)
        assert results == []

    def test_empty_query_returns_empty(self, vector):
        scope = RetrievalScope.course("A")
        vector.index(scope, DOCS_A)
        assert vector.retrieve("", scope=scope) == []
        assert vector.retrieve("   ", scope=scope) == []


# =====================================================================
# RRF Fusion
# =====================================================================


class TestRRFFusion:
    def test_fuse_empty(self):
        assert rrf_fuse({}) == []

    def test_fuse_single_source(self):
        scope = RetrievalScope.course("A")
        bm25 = FakeBM25Provider()
        bm25.index(scope, DOCS_A)
        bm25_results = bm25.retrieve(QUERY_ML, scope=scope, top_k=3)
        fused = rrf_fuse({"bm25": bm25_results}, top_k=3)
        assert len(fused) >= 1
        assert all(isinstance(c, RetrievedChunk) for c in fused)

    def test_fuse_two_sources(self):
        scope = RetrievalScope.course("A")
        bm25 = FakeBM25Provider()
        vector = FakeVectorProvider()
        bm25.index(scope, DOCS_A)
        vector.index(scope, DOCS_A)
        bm25_results = bm25.retrieve(QUERY_ML, scope=scope, top_k=3)
        vector_results = vector.retrieve(QUERY_ML, scope=scope, top_k=3)
        fused = rrf_fuse(
            {"bm25": bm25_results, "vector": vector_results},
            top_k=5,
        )
        assert len(fused) >= 1
        # RRF score should be positive
        assert fused[0].retrieval_score is not None

    def test_fuse_with_weights(self):
        scope = RetrievalScope.course("A")
        bm25 = FakeBM25Provider()
        vector = FakeVectorProvider()
        bm25.index(scope, DOCS_A)
        vector.index(scope, DOCS_A)
        bm25_results = bm25.retrieve(QUERY_ML, scope=scope, top_k=3)
        vector_results = vector.retrieve(QUERY_ML, scope=scope, top_k=3)
        config = FusionConfig(k=60, weights={"bm25": 0.3, "vector": 0.7})
        fused = rrf_fuse(
            {"bm25": bm25_results, "vector": vector_results},
            config=config,
            top_k=5,
        )
        assert len(fused) >= 1

    def test_fuse_preserves_evidence_fields(self):
        """Evidence IDs in RetrievedChunk must survive fusion."""
        scope = RetrievalScope.course("A")
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                content="ML is AI",
                scope=scope,
                artifact_id="art_001",
                document_id="doc_001",
                block_id="blk_001",
            )
        ]
        fused = rrf_fuse({"bm25": chunks}, top_k=5)
        assert fused[0].artifact_id == "art_001"
        assert fused[0].document_id == "doc_001"
        assert fused[0].block_id == "blk_001"


# =====================================================================
# Reranker
# =====================================================================


class TestRerankerProvider:
    def test_rerank_empty(self, reranker):
        assert reranker.rerank("query", []) == []

    def test_rerank_returns_reranked_chunks(self, reranker):
        scope = RetrievalScope.course("A")
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                content="ML is AI",
                scope=scope,
                retrieval_score=0.9,
            ),
            RetrievedChunk(
                chunk_id="c2",
                content="DL is ML subset",
                scope=scope,
                retrieval_score=0.7,
            ),
        ]
        result = reranker.rerank("ML", chunks, top_k=5)
        assert len(result) == 2
        # Fake reranker adjusts score by 1.05x
        assert result[0].retrieval_score == 0.9 * 1.05
        assert result[0].retrieval_source == "reranked"
        assert result[0].metadata.get("reranked") is True

    def test_rerank_preserves_evidence_ids(self, reranker):
        """Reranking must NOT discard evidence IDs."""
        scope = RetrievalScope.course("A")
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                content="text",
                scope=scope,
                artifact_id="art_001",
                document_id="doc_001",
                unit_id="unit_001",
                block_id="blk_001",
            )
        ]
        result = reranker.rerank("query", chunks, top_k=5)
        assert result[0].artifact_id == "art_001"
        assert result[0].document_id == "doc_001"
        assert result[0].unit_id == "unit_001"
        assert result[0].block_id == "blk_001"

    def test_rerank_top_k(self, reranker):
        scope = RetrievalScope.course("A")
        chunks = [
            RetrievedChunk(chunk_id=f"c{i}", content=f"text{i}", scope=scope)
            for i in range(5)
        ]
        result = reranker.rerank("query", chunks, top_k=3)
        assert len(result) == 3
