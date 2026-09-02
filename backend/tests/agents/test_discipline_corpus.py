"""RAG 检索白名单接入（2026-09-01）：学科语料层 FTS 检索的离线契约测试。

覆盖：
- 分词器（CJK 二元组 + ASCII 词）；
- fixture 索引上的段落检索（is_supplementary 契约、无 evidence_id、噪声词剥离）；
- fail-closed：未配置路径 / 文件缺失 / 非法索引文件均返回空列表；
- 向量召回与 FTS 的 RRF 融合（monkeypatch 向量路）、向量路降级；
- Port 两级合并（概念层 discipline_kb + 语料层 discipline_corpus）；
- respond 端点把段落字段（doc_id/chunk_no/source_license/retrieval_source）透出。
"""
from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from app.platform.knowledge import discipline_corpus
from app.platform.knowledge.discipline_corpus import tokenize_for_fts
from app.platform.agents.providers.retrieval.discipline_kb import DisciplineKnowledgePortImpl


_ENDPOINT = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "endpoints" / "teaching_agent.py"
_SPEC = importlib.util.spec_from_file_location("teaching_agent_endpoint_corpus_test", _ENDPOINT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _build_fixture_index(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE corpus_paragraph(
            rowid INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_no INTEGER NOT NULL,
            title_raw TEXT NOT NULL,
            body_raw TEXT NOT NULL,
            book TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            license TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE corpus_fts USING fts5(title, body, tokenize='unicode61', content='')"
    )
    rows = [
        (
            "fixture-virtual-memory", 0, "虚拟内存",
            "虚拟内存是计算机系统内存管理的一种技术。它使得应用程序认为它拥有连续的可用的内存，"
            "而实际上是被分隔的多个物理内存碎片，还有部分暂时存储在外部磁盘存储器上。",
            "教科书示例", "fixture", "CC BY-SA 4.0",
        ),
        (
            "fixture-tcp", 0, "传输控制协议",
            "TCP三次握手建立连接：客户端发送SYN，服务器回复SYN+ACK，客户端再发送ACK完成连接建立。",
            "", "fixture", "CC BY-SA 4.0",
        ),
    ]
    for rowid, (doc_id, chunk_no, title, body, book, source, license_) in enumerate(rows, 1):
        conn.execute(
            "INSERT INTO corpus_paragraph VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rowid, doc_id, chunk_no, title, body, book, source, license_),
        )
        conn.execute(
            "INSERT INTO corpus_fts(rowid, title, body) VALUES (?, ?, ?)",
            (rowid, tokenize_for_fts(title), tokenize_for_fts(body)),
        )
    conn.commit()
    conn.close()


class _FixtureIndexMixin:
    """为测试提供临时 fixture 索引并注入 settings 路径。"""

    def setUp(self):
        from app.core.config import settings

        self._tmp = tempfile.TemporaryDirectory()
        self.index_path = Path(self._tmp.name) / "fixture_corpus.sqlite3"
        _build_fixture_index(self.index_path)
        self._original_path = getattr(settings, "DISCIPLINE_CORPUS_INDEX_PATH", "")
        self._original_top_k = getattr(settings, "DISCIPLINE_CORPUS_TOP_K", 2)
        settings.DISCIPLINE_CORPUS_INDEX_PATH = str(self.index_path)
        settings.DISCIPLINE_CORPUS_TOP_K = 2

    def tearDown(self):
        from app.core.config import settings

        settings.DISCIPLINE_CORPUS_INDEX_PATH = self._original_path
        settings.DISCIPLINE_CORPUS_TOP_K = self._original_top_k
        discipline_corpus.close_corpus_connection()
        self._tmp.cleanup()


class TokenizeForFtsTest(unittest.TestCase):
    def test_cjk_bigram(self):
        self.assertEqual(tokenize_for_fts("进程调度"), "进程 程调 调度")

    def test_ascii_and_mixed(self):
        self.assertEqual(tokenize_for_fts("TCP handshake"), "tcp handshake")
        self.assertEqual(tokenize_for_fts("TCP三次握手"), "tcp 三次 次握 握手")

    def test_empty(self):
        self.assertEqual(tokenize_for_fts(""), "")


class SearchCorpusTest(_FixtureIndexMixin, unittest.TestCase):
    def test_hit_returns_supplementary_paragraph_without_evidence_id(self):
        results = discipline_corpus.search_corpus("TCP三次握手")
        self.assertTrue(results)
        first = results[0]
        self.assertEqual(first["doc_id"], "fixture-tcp")
        self.assertEqual(first["retrieval_source"], "discipline_corpus")
        self.assertTrue(first["is_supplementary"])
        self.assertNotIn("evidence_id", first)
        self.assertIn("三次握手", first["snippet"])

    def test_or_fallback_when_and_misses(self):
        # "虚拟内存页面置换" 的 AND 匹配无命中（fixture 段落无"页面置换"），
        # 回退 OR 后仍应命中虚拟内存段落。
        results = discipline_corpus.search_corpus("虚拟内存页面置换算法")
        self.assertTrue(results)
        self.assertEqual(results[0]["doc_id"], "fixture-virtual-memory")

    def test_noise_words_stripped(self):
        # 纯噪声词查询剥离后为空，直接返回空列表。
        self.assertEqual(discipline_corpus.search_corpus("请问怎么理解"), [])

    def test_index_available_flag(self):
        self.assertTrue(discipline_corpus.corpus_index_available())


class SearchCorpusFailClosedTest(unittest.TestCase):
    def _with_path(self, value: str):
        from app.core.config import settings

        original = getattr(settings, "DISCIPLINE_CORPUS_INDEX_PATH", "")
        settings.DISCIPLINE_CORPUS_INDEX_PATH = value
        try:
            return discipline_corpus.search_corpus("虚拟内存")
        finally:
            settings.DISCIPLINE_CORPUS_INDEX_PATH = original

    def test_unconfigured_path_returns_empty(self):
        self.assertEqual(self._with_path(""), [])

    def test_missing_file_returns_empty(self):
        self.assertEqual(self._with_path(str(Path(tempfile.gettempdir()) / "no-such-index.sqlite3")), [])

    def test_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.sqlite3"
            bad.write_text("this is not a sqlite database", encoding="utf-8")
            try:
                self.assertEqual(self._with_path(str(bad)), [])
            finally:
                discipline_corpus.close_corpus_connection()


class PortMergeTest(_FixtureIndexMixin, unittest.TestCase):
    def test_port_merges_concept_and_corpus_layers(self):
        refs = asyncio.run(DisciplineKnowledgePortImpl().search_discipline_knowledge(
            course_id="1", message="TCP三次握手是什么", concept_id=None, top_k=3,
        ))
        sources = {str(ref.get("retrieval_source")) for ref in refs}
        self.assertIn("discipline_corpus", sources)
        corpus_refs = [ref for ref in refs if ref.get("retrieval_source") == "discipline_corpus"]
        self.assertTrue(corpus_refs[0]["doc_id"])
        self.assertEqual(corpus_refs[0]["node_type"], "corpus_paragraph")
        for ref in refs:
            self.assertTrue(ref["is_supplementary"])
            self.assertNotIn("evidence_id", ref)

    def test_port_survives_corpus_layer_failure(self):
        from app.core.config import settings

        settings.DISCIPLINE_CORPUS_INDEX_PATH = str(self.index_path.parent / "missing.sqlite3")
        try:
            refs = asyncio.run(DisciplineKnowledgePortImpl().search_discipline_knowledge(
                course_id="1", message="什么是哈希表", concept_id=None, top_k=3,
            ))
        finally:
            settings.DISCIPLINE_CORPUS_INDEX_PATH = str(self.index_path)
        # 语料层降级为空，概念层结果不受影响。
        self.assertTrue(refs)
        self.assertTrue(all(ref.get("retrieval_source") == "discipline_kb" for ref in refs))


class RespondEndpointCorpusProjectionTest(unittest.TestCase):
    def test_response_exposes_corpus_paragraph_fields(self):
        import asyncio as _asyncio

        class StubRuntime:
            async def respond(self, **kwargs: Any):
                return {
                    "trace_id": "trace-1", "status": "ok", "intent": "concept_question",
                    "concept_candidates": [], "current_concept_id": None,
                    "teaching_action": "normal_answer", "final_answer": "讲解内容",
                    "citations": [],
                    "discipline_kb_results": [{
                        "node_id": "", "name": "传输控制协议", "course": "",
                        "node_type": "corpus_paragraph", "definition": "TCP三次握手……",
                        "key_points": [], "example": "",
                        "doc_id": "fixture-tcp", "chunk_no": 0,
                        "source_title": "教科书示例", "source_authors": "",
                        "source_chapter": "", "source_license": "CC BY-SA 4.0",
                        "retrieval_source": "discipline_corpus",
                        "is_supplementary": True,
                    }],
                    "selected_resource_ids": [], "warnings": [], "degraded_services": [],
                    "learning_adjustment": None, "inquiry_depth": None,
                }

        response = _asyncio.run(_MODULE._respond_for_subject(
            subject_user_id=1, course_id=1, session_id="s", message="TCP三次握手",
            resource_id=None, exercise_id=None, code_submission_id=None,
            question_observation=None, persist_learner_turn=False,
            runtime_source=StubRuntime(), session=None,
        ))
        refs = response["discipline_references"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["doc_id"], "fixture-tcp")
        self.assertEqual(refs[0]["retrieval_source"], "discipline_corpus")
        self.assertEqual(refs[0]["source_license"], "CC BY-SA 4.0")
        self.assertEqual(refs[0]["node_type"], "corpus_paragraph")
        self.assertTrue(refs[0]["is_supplementary"])


class RRFFuseTest(unittest.TestCase):
    def test_both_channel_hit_ranks_first(self):
        from app.platform.knowledge.discipline_corpus import _rrf_fuse

        # rowid 2 两路都命中应排第一；1/3 各只命中一路。
        fused = _rrf_fuse([2, 1], [3, 2])
        self.assertEqual(fused[0], 2)
        self.assertEqual(sorted(fused[1:]), [1, 3])

    def test_single_channel(self):
        from app.platform.knowledge.discipline_corpus import _rrf_fuse

        self.assertEqual(_rrf_fuse([5, 6], []), [5, 6])
        self.assertEqual(_rrf_fuse([], [7]), [7])


class VectorFusionTest(_FixtureIndexMixin, unittest.TestCase):
    """向量召回与 FTS 的 RRF 融合（monkeypatch 向量路，不依赖 pgvector）。"""

    def setUp(self):
        super().setUp()
        discipline_corpus._reset_vector_state()

    def tearDown(self):
        discipline_corpus._reset_vector_state()
        super().tearDown()

    def test_vector_and_fts_hits_are_fused(self):
        # FTS 命中 rowid 2（TCP）；向量路返回 rowid 1、2。
        # RRF 后 rowid 2（两路命中）第一，rowid 1（仅向量）第二。
        with mock.patch.object(
            discipline_corpus, "_vector_search", return_value=[(1, 0.92), (2, 0.81)]
        ):
            results = discipline_corpus.search_corpus("TCP三次握手")
        self.assertEqual([r["rowid"] for r in results], [2, 1])
        self.assertEqual(results[0]["doc_id"], "fixture-tcp")
        self.assertEqual(results[0]["matched_by"], ["fts", "vector"])
        # 仅向量命中的段落从 corpus_paragraph 回取原文。
        self.assertEqual(results[1]["doc_id"], "fixture-virtual-memory")
        self.assertEqual(results[1]["matched_by"], ["vector"])
        self.assertIn("虚拟内存", results[1]["snippet"])

    def test_vector_only_hit_when_fts_misses(self):
        # FTS 完全无命中时，向量命中仍应产出结果（纯向量补充路径）。
        with mock.patch.object(discipline_corpus, "_fts_search", return_value=[]), mock.patch.object(
            discipline_corpus, "_vector_search", return_value=[(2, 0.95)]
        ):
            results = discipline_corpus.search_corpus("建立连接的握手过程")
        self.assertTrue(results)
        self.assertEqual(results[0]["doc_id"], "fixture-tcp")
        self.assertEqual(results[0]["matched_by"], ["vector"])


class VectorFailClosedTest(_FixtureIndexMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        discipline_corpus._reset_vector_state()

    def tearDown(self):
        discipline_corpus._reset_vector_state()
        super().tearDown()

    def test_enabled_but_model_missing_falls_back_to_fts(self):
        from app.core.config import settings

        settings.DISCIPLINE_CORPUS_VECTOR_ENABLED = True
        settings.DISCIPLINE_CORPUS_VECTOR_MODEL_PATH = ""
        original_graphrag = getattr(settings, "GRAPHRAG_EMBEDDING_LOCAL_PATH", "")
        settings.GRAPHRAG_EMBEDDING_LOCAL_PATH = ""
        try:
            results = discipline_corpus.search_corpus("TCP三次握手")
            # 模型路径缺失 → 向量路禁用，纯 FTS 行为不变。
            self.assertTrue(results)
            self.assertEqual(results[0]["doc_id"], "fixture-tcp")
            self.assertEqual(results[0]["matched_by"], ["fts"])
        finally:
            settings.GRAPHRAG_EMBEDDING_LOCAL_PATH = original_graphrag

    def test_provider_failure_disables_vector_for_process(self):
        from app.core.config import settings

        original_enabled = getattr(settings, "DISCIPLINE_CORPUS_VECTOR_ENABLED", False)
        settings.DISCIPLINE_CORPUS_VECTOR_ENABLED = True

        class BrokenProvider:
            def embed(self, texts):
                raise RuntimeError("model exploded")

        try:
            with mock.patch.object(
                discipline_corpus, "_get_vector_provider", return_value=BrokenProvider()
            ):
                first = discipline_corpus.search_corpus("TCP三次握手")
            self.assertTrue(first)
            self.assertEqual(first[0]["matched_by"], ["fts"])
            # 进程内禁用：真实 _get_vector_provider 此后直接返回 None，
            # 向量路不再尝试（直到服务重启）。
            self.assertIsNone(discipline_corpus._get_vector_provider())
            self.assertEqual(discipline_corpus._vector_search("TCP三次握手", 8), [])
        finally:
            settings.DISCIPLINE_CORPUS_VECTOR_ENABLED = original_enabled


if __name__ == "__main__":
    unittest.main()
