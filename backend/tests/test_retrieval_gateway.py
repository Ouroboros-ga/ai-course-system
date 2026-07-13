"""
统一检索 Gateway / Scope 契约测试（R2D0-P1A）。

验证：
- RetrievalScope：course 与 knowledge_base 同 ID 不冲突、可哈希、统一转 str。
- RetrievedChunk：统一结构、chunk_id 跨进程稳定、无页码/章节 ID 时为 None。
- RetrievalGateway：空查询、top_k 边界、缺失 scope、检索异常兜底、多次稳定。
- Tree Provider：跨课程/跨知识库隔离、缺失返回空不回退、原子替换。
- QAService：显式课程 scope 透传、缺失回退 course_context、ragSources 兼容。
- 旧接口兼容：rag_pipeline.retrieve(course_id=...)、process_document(scope=...)、
  无 scope 调用保持兼容并产生可控 deprecation warning。

不依赖真实 LLM / 网络 / Embedding / FAISS。使用最小测试文本与 FakeLLMClient。
"""

import asyncio
import warnings

import pytest

from app.common.RAG import rag_pipeline
from app.common.RAG.rag_utils import RAGPipeline
from app.platform.retrieval import (
    RetrievedChunk,
    RetrievalGateway,
    RetrievalScope,
    retrieval_gateway,
    stable_chunk_id,
)
from app.services.qa_service import qa_service


COURSE_A_MD = """# 机器学习

机器学习是人工智能的一个重要分支。监督学习需要标注数据，常用于分类与回归任务。

# 模型评估

准确率、召回率与 F1 分数是常用的评估指标。
"""

COURSE_B_MD = """# 深度学习

深度学习是机器学习的子领域，神经网络是其核心结构，反向传播算法用于训练。

# 卷积神经网络

卷积神经网络擅长处理图像数据，通过卷积核提取局部特征。
"""

KB_MD = """# 高等数学

导数描述函数的变化率，定积分计算曲线下面积。

# 线性代数

矩阵乘法与行列式是线性代数的基础工具。
"""

A_TERM = "机器学习"
A_DISTINCTIVE = "监督学习需要标注数据"
B_DISTINCTIVE = "神经网络是其核心结构"
KB_DISTINCTIVE = "定积分计算曲线下面积"


@pytest.fixture(autouse=True)
def _reset_scopes():
    """每个测试前后清空所有作用域检索器，避免跨测试污染。"""
    rag_pipeline.clear_all_scopes()
    yield
    rag_pipeline.clear_all_scopes()


def _index_course(course_id, markdown, name):
    rag_pipeline.process_document(
        markdown_text=markdown, doc_name=name, scope=RetrievalScope.course(course_id)
    )


def _index_kb(kb_id, markdown, name):
    rag_pipeline.process_document(
        markdown_text=markdown, doc_name=name, scope=RetrievalScope.knowledge_base(kb_id)
    )


# =====================================================================
# RetrievalScope
# =====================================================================


class TestRetrievalScope:
    def test_course_and_kb_same_id_do_not_collide(self):
        c = RetrievalScope.course(1)
        k = RetrievalScope.knowledge_base(1)
        assert c.key == "course:1"
        assert k.key == "knowledge_base:1"
        assert c != k
        assert hash(c) != hash(k)

    def test_scope_id_normalized_to_string(self):
        assert RetrievalScope.course(12).scope_id == "12"
        assert RetrievalScope.knowledge_base("5").scope_id == "5"

    def test_scope_hashable_and_usable_as_dict_key(self):
        s = RetrievalScope.course(7)
        d = {s: "v"}
        assert d[RetrievalScope.course(7)] == "v"

    def test_scope_frozen(self):
        s = RetrievalScope.course(1)
        with pytest.raises(Exception):
            s.scope_id = "2"  # type: ignore[misc]


# =====================================================================
# RetrievedChunk
# =====================================================================


class TestRetrievedChunk:
    def test_chunk_id_stable_across_processes(self):
        # SHA-256 输入确定性，跨进程稳定（不依赖 Python hash()）
        cid1 = stable_chunk_id(RetrievalScope.course(1), "a/b", "content")
        cid2 = stable_chunk_id(RetrievalScope.course(1), "a/b", "content")
        assert cid1 == cid2
        # 不同 scope / 路径 / 内容产生不同 id
        assert cid1 != stable_chunk_id(RetrievalScope.knowledge_base(1), "a/b", "content")
        assert cid1 != stable_chunk_id(RetrievalScope.course(1), "a/c", "content")
        assert cid1 != stable_chunk_id(RetrievalScope.course(1), "a/b", "other")

    def test_chunk_id_invariant_to_whitespace_and_newline_forms(self):
        """换行符差异 / 多余空白 / 路径分隔符差异 / Unicode 不同表示
        不应导致相同内容生成不同 chunk_id。"""
        base = stable_chunk_id(RetrievalScope.course(1), "a/b", "hello world")
        assert stable_chunk_id(RetrievalScope.course(1), "a/b", "hello  world") == base
        assert stable_chunk_id(RetrievalScope.course(1), "a\\b", "hello world") == base
        assert stable_chunk_id(
            RetrievalScope.course(1), "a/b", "hello world\r\n"
        ) == base
        assert stable_chunk_id(
            RetrievalScope.course(1), " a/b ", "  hello world  "
        ) == base

    def test_gateway_returns_retrieved_chunk_type(self):
        _index_course("A", COURSE_A_MD, "课程A")
        chunks = retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("A"), top_k=3
        )
        assert len(chunks) >= 1
        assert all(isinstance(c, RetrievedChunk) for c in chunks)

    def test_chunk_fields_mapping(self):
        _index_course("A", COURSE_A_MD, "课程A")
        chunks = retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("A"), top_k=3
        )
        c = chunks[0]
        assert c.scope.key == "course:A"
        assert c.retrieval_source == "tree_keyword"
        assert isinstance(c.match_type, str)
        assert isinstance(c.path, list) and len(c.path) >= 1
        assert c.retrieval_score is not None
        # 当前树式检索不具备页码/章节 ID，必须为 None（不伪造）
        assert c.page_number is None
        assert c.chapter_id is None
        assert c.source_id is None
        # chapter_title 取自路径首段（标题），非数据库章节 ID
        assert c.chapter_title == c.path[0]
        # chunk_id 为 16 位十六进制稳定标识
        assert len(c.chunk_id) == 16
        int(c.chunk_id, 16)  # 可解析为十六进制

    def test_chunk_id_reproducible_on_rebuild(self):
        _index_course("A", COURSE_A_MD, "课程A")
        chunks1 = retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("A"), top_k=3
        )
        # 重建（覆盖）后 chunk_id 应保持稳定
        _index_course("A", COURSE_A_MD, "课程A")
        chunks2 = retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("A"), top_k=3
        )
        assert {c.chunk_id for c in chunks1} == {c.chunk_id for c in chunks2}


# =====================================================================
# RetrievalGateway
# =====================================================================


class TestRetrievalGateway:
    def test_empty_query_returns_empty(self):
        _index_course("A", COURSE_A_MD, "课程A")
        assert retrieval_gateway.retrieve("", scope=RetrievalScope.course("A")) == []
        assert retrieval_gateway.retrieve("   ", scope=RetrievalScope.course("A")) == []

    def test_top_k_invalid_falls_back_to_default(self):
        _index_course("A", COURSE_A_MD, "课程A")
        # top_k=0 / 负数 -> 默认；不抛异常
        for k in (0, -1):
            res = retrieval_gateway.retrieve(A_TERM, scope=RetrievalScope.course("A"), top_k=k)
            assert isinstance(res, list)

    def test_top_k_larger_than_data(self):
        _index_course("A", COURSE_A_MD, "课程A")
        res = retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("A"), top_k=1000
        )
        assert isinstance(res, list) and len(res) <= 1000

    def test_missing_scope_returns_empty_no_fallback(self):
        _index_course("A", COURSE_A_MD, "课程A")
        # 未知 scope 不回退到已建立的 course:A
        assert retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("UNKNOWN")
        ) == []
        assert retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.knowledge_base("A")
        ) == []

    def test_retrieval_exception_is_caught(self):
        # 注入一个会抛异常的伪检索器到 registry，验证 Gateway 兜底
        class _BoomRetriever:
            def retrieve(self, *a, **kw):
                raise RuntimeError("fake retrieval boom")

        scope = RetrievalScope.course("BOOM")
        retrieval_gateway._registry.register(scope, _BoomRetriever())
        try:
            res = retrieval_gateway.retrieve(A_TERM, scope=scope, top_k=3)
            assert res == []
        finally:
            retrieval_gateway.clear_scope(scope)

    def test_repeated_calls_stable(self):
        _index_course("A", COURSE_A_MD, "课程A")
        r1 = retrieval_gateway.retrieve(A_TERM, scope=RetrievalScope.course("A"), top_k=5)
        r2 = retrieval_gateway.retrieve(A_TERM, scope=RetrievalScope.course("A"), top_k=5)
        assert [c.chunk_id for c in r1] == [c.chunk_id for c in r2]


# =====================================================================
# 跨作用域隔离（course / knowledge_base）
# =====================================================================


class TestScopeIsolation:
    def test_course_a_not_polluted_by_course_b(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_course("B", COURSE_B_MD, "课程B")
        chunks = retrieval_gateway.retrieve(A_TERM, scope=RetrievalScope.course("A"), top_k=5)
        ctx = "\n".join(c.content for c in chunks)
        assert A_DISTINCTIVE in ctx
        assert B_DISTINCTIVE not in ctx

    def test_kb_does_not_leak_into_course(self):
        _index_course("1", COURSE_A_MD, "课程1")
        _index_kb("1", KB_MD, "知识库1")  # 同 ID=1，不同作用域
        # 课程 1 的检索不应命中知识库 1 的内容
        chunks = retrieval_gateway.retrieve(A_TERM, scope=RetrievalScope.course("1"), top_k=5)
        ctx = "\n".join(c.content for c in chunks)
        assert KB_DISTINCTIVE not in ctx
        # 知识库 1 可单独检索
        kb_chunks = retrieval_gateway.retrieve(
            "定积分", scope=RetrievalScope.knowledge_base("1"), top_k=5
        )
        assert len(kb_chunks) >= 1
        assert KB_DISTINCTIVE in "\n".join(c.content for c in kb_chunks)

    def test_clear_one_scope_does_not_affect_others(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_course("B", COURSE_B_MD, "课程B")
        assert retrieval_gateway.clear_scope(RetrievalScope.course("A")) is True
        # A 被清空
        assert retrieval_gateway.retrieve(
            A_TERM, scope=RetrievalScope.course("A")
        ) == []
        # B 仍可检索
        assert len(retrieval_gateway.retrieve(
            "深度学习", scope=RetrievalScope.course("B"), top_k=5
        )) >= 1

    def test_has_scope(self):
        assert retrieval_gateway.has_scope(RetrievalScope.course("A")) is False
        _index_course("A", COURSE_A_MD, "课程A")
        assert retrieval_gateway.has_scope(RetrievalScope.course("A")) is True
        assert retrieval_gateway.has_scope(RetrievalScope.knowledge_base("A")) is False


# =====================================================================
# 原子替换
# =====================================================================


class TestAtomicReplace:
    def test_rebuild_replaces_old_index_for_same_scope(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_course("A", COURSE_B_MD, "课程A-v2")  # 覆盖
        chunks = retrieval_gateway.retrieve(A_TERM, scope=RetrievalScope.course("A"), top_k=5)
        ctx = "\n".join(c.content for c in chunks)
        # 覆盖后应反映新内容（B 的特征），不再有旧 A 的独有内容
        assert A_DISTINCTIVE not in ctx

    def test_replacing_one_scope_does_not_affect_another(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_course("B", COURSE_B_MD, "课程B")
        _index_course("A", COURSE_B_MD, "课程A-v2")  # 只覆盖 A
        b_chunks = retrieval_gateway.retrieve(
            "深度学习", scope=RetrievalScope.course("B"), top_k=5
        )
        assert B_DISTINCTIVE in "\n".join(c.content for c in b_chunks)


# =====================================================================
# QAService 迁移
# =====================================================================


class TestQAServiceViaGateway:
    def test_retrieve_rag_context_uses_explicit_course_scope(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_course("B", COURSE_B_MD, "课程B")
        ctx, sources = qa_service.retrieve_rag_context(A_TERM, top_k=5, course_id="A")
        assert ctx != ""
        assert A_DISTINCTIVE in ctx
        assert B_DISTINCTIVE not in ctx
        # ragSources 旧结构兼容
        assert isinstance(sources, list) and len(sources) >= 1
        s = sources[0]
        assert {"path", "score", "match_type", "content_preview"} <= set(s.keys())

    def test_missing_rag_index_falls_back_to_empty(self):
        _index_course("A", COURSE_A_MD, "课程A")
        # 未知课程 -> 空 RAG 上下文（调用方应回退 DB course_context）
        ctx, sources = qa_service.retrieve_rag_context(
            A_TERM, top_k=5, course_id="UNKNOWN"
        )
        assert ctx == "" and sources == []

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_ask_question_with_rag_carries_course_scope(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_course("B", COURSE_B_MD, "课程B")
        result = self._run(
            qa_service.ask_question_with_rag(
                question=A_TERM,
                course_context="",
                use_rag=True,
                rag_top_k=5,
                course_id="A",
            )
        )
        assert result["rag_context"] is not None
        assert A_DISTINCTIVE in result["rag_context"]
        assert B_DISTINCTIVE not in result["rag_context"]
        assert result["answer"] == "fake llm response"

    def test_qa_does_not_access_provider_private_fields(self):
        """QAService.retrieve_rag_context 不再触碰 rag_pipeline._retriever /
        Provider 私有字段：未知课程路径不应抛 AttributeError。"""
        ctx, _ = qa_service.retrieve_rag_context(A_TERM, top_k=3, course_id="MISSING")
        assert ctx == ""


# =====================================================================
# 旧 rag_pipeline 兼容层
# =====================================================================


class TestLegacyRagPipelineCompat:
    def test_retrieve_with_course_id_still_works(self):
        _index_course("A", COURSE_A_MD, "课程A")
        # 旧签名：rag_pipeline.retrieve(query, course_id=...) 返回 RetrievalResult
        results = rag_pipeline.retrieve(A_TERM, course_id="A", top_k=3)
        assert len(results) >= 1
        assert hasattr(results[0], "context_path")  # RetrievalResult 旧类型

    def test_process_document_with_explicit_scope(self):
        rag_pipeline.process_document(
            markdown_text=COURSE_A_MD,
            doc_name="课程A",
            scope=RetrievalScope.course("A"),
        )
        assert rag_pipeline.has_course_index("A") is True
        assert rag_pipeline.retrieve(A_TERM, course_id="A", top_k=3)

    def test_has_and_clear_course_index_delegate_to_gateway(self):
        _index_course("A", COURSE_A_MD, "课程A")
        assert rag_pipeline.has_course_index("A") is True
        assert rag_pipeline.clear_course_index("A") is True
        assert rag_pipeline.has_course_index("A") is False
        assert rag_pipeline.clear_course_index("A") is False  # 再清返回 False

    def test_clear_all_scopes(self):
        _index_course("A", COURSE_A_MD, "课程A")
        _index_kb("B", KB_MD, "知识库B")
        n = rag_pipeline.clear_all_scopes()
        assert n >= 2
        assert rag_pipeline.has_course_index("A") is False

    def test_no_scope_retrieve_emits_deprecation_warning_once(self):
        """无作用域旧调用保持兼容行为并产生可控 deprecation warning。"""
        import app.common.RAG.rag_utils as rag_utils_mod
        # 重置每进程一次的告警标志，使本测试不依赖其他测试的执行顺序
        rag_utils_mod._legacy_no_scope_warned = False
        _index_course("A", COURSE_A_MD, "课程A")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            results = rag_pipeline.retrieve(A_TERM, top_k=3)  # 无 course_id
            # 至少产生一次 DeprecationWarning，且携带调用来源信息便于清理排查
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert dep_warnings, "expected a DeprecationWarning for no-scope retrieval"
            assert "Called from:" in str(dep_warnings[0].message)
        # 兼容行为：仍返回结果（命中最后构建的全局树）
        assert isinstance(results, list)
