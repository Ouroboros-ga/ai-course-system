from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.dense import CourseDenseRetriever, cache_filename, cache_identity


TEMP_ROOT = RESEARCH_ROOT / "tests" / "_tmp"


class FakeEmbedder:
    def encode_documents(self, texts):
        return [[1.0, 0.0] if "电机" in text else [0.0, 1.0] for text in texts]

    def encode_queries(self, texts):
        return [[1.0, 0.0] if "电机" in text else [0.0, 1.0] for text in texts]


@contextmanager
def test_directory():
    path = TEMP_ROOT / f"dense_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


class DenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP_ROOT.mkdir(exist_ok=True)

    def test_course_dense_retrieval_is_closed_cited_and_cached(self):
        corpus = [
            {"research_chunk_id": "rch_a", "course_id": "C1", "text": "电机原理", "research_evidence_ids": ["rev_a"], "page_or_slide": 1, "block_id": "b1"},
            {"research_chunk_id": "rch_b", "course_id": "C2", "text": "电机原理", "research_evidence_ids": ["rev_b"], "page_or_slide": 1, "block_id": "b2"},
        ]
        evidence = [
            {"research_evidence_id": "rev_a", "course_id": "C1", "status": "active", "citation_key": "cite_a", "artifact_id": "a", "block_id": "b1", "page_or_slide": 1},
            {"research_evidence_id": "rev_b", "course_id": "C2", "status": "active", "citation_key": "cite_b", "artifact_id": "a", "block_id": "b2", "page_or_slide": 1},
        ]
        identity = cache_identity(fixture_manifest_sha256="fixture", model={"revision": "fixed"}, max_length=8, query_instruction="")
        with test_directory() as temp:
            cache = temp / cache_filename(identity)
            retriever = CourseDenseRetriever(corpus, evidence, embedder=FakeEmbedder(), cache_path=cache, cache_key=identity)
            result = retriever.retrieve({"research_query_id": "rq_1", "course_id": "C1", "text": "电机"}, top_k=5, minimum_cosine=0)
            self.assertEqual(result["hits"][0]["course_id"], "C1")
            self.assertEqual(result["hits"][0]["citations"][0]["citation_key"], "cite_a")
            self.assertTrue(cache.is_file())
            reloaded = CourseDenseRetriever(corpus, evidence, embedder=FakeEmbedder(), cache_path=cache, cache_key=identity)
            self.assertEqual(reloaded.retrieve({"research_query_id": "rq_1", "course_id": "C1", "text": "电机"}, top_k=1, minimum_cosine=0)["hits"][0]["research_chunk_id"], "rch_a")


if __name__ == "__main__":
    unittest.main()
