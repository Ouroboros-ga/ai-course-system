"""
RAG 课程范围隔离测试

验证 P0 修复：问答检索按 course_id 隔离，避免跨课程上下文污染。

背景（修复前）：
  rag_pipeline 是进程级全局单例，TreeRAGRetriever.build_index 每次覆盖唯一的全局树；
  QAService.retrieve_rag_context -> rag_pipeline.retrieve(question) 不传 course_id，
  因此上传课程 B 后，学生对课程 A 提问会命中“最后一次构建”的 B 的树。

修复后：
  RAGPipeline 维护按 course_id 隔离的检索器注册表；retrieve(course_id=...) 只查该课程，
  缺失时返回空（不回退到全局最新树），杜绝跨课程污染；course_id=None 保留旧行为。

本测试不依赖真实 LLM / 网络：retrieve 与 retrieve_rag_context 为纯检索路径；
ask_question_with_rag 集成测试使用 conftest 自动安装的 FakeLLMClient。
"""

import asyncio

import pytest

from app.common.RAG import rag_pipeline
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

A_TERM = "机器学习"
A_DISTINCTIVE = "监督学习需要标注数据"
B_DISTINCTIVE = "神经网络是其核心结构"


@pytest.fixture(autouse=True)
def _reset_rag_singleton():
    """每个测试前后清空全局 rag_pipeline 的作用域检索器，避免跨测试污染。"""
    rag_pipeline.clear_all_scopes()
    yield
    rag_pipeline.clear_all_scopes()


def _process(course_id, markdown, name):
    """以 course_id 为范围键处理文档，等价于上传主链的 RAGProcessor.process 行为。"""
    rag_pipeline.process_document(
        markdown_text=markdown, doc_name=name, doc_id=str(course_id)
    )


def _context_text(results):
    return "\n".join(rag_pipeline.get_context_for_result(r) for r in results)


class TestCourseScopedRetrieval:
    """RAGPipeline.retrieve 的课程范围隔离。"""

    def test_retrieve_returns_course_content(self):
        _process("A", COURSE_A_MD, "课程A")
        results = rag_pipeline.retrieve(A_TERM, course_id="A", top_k=3)
        assert len(results) >= 1
        assert A_DISTINCTIVE in _context_text(results)

    def test_cross_course_isolation_query_a_gets_a_not_b(self):
        # 顺序处理 A 后 B：B 会覆盖全局最新树（旧行为下的污染源）
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")

        # 课程 A 的提问只命中 A 的树，不泄漏 B 的内容
        results_a = rag_pipeline.retrieve(A_TERM, course_id="A", top_k=5)
        assert len(results_a) >= 1
        ctx_a = _context_text(results_a)
        assert A_DISTINCTIVE in ctx_a
        assert B_DISTINCTIVE not in ctx_a

        # 课程 B 的提问命中 B 的树
        results_b = rag_pipeline.retrieve("深度学习", course_id="B", top_k=5)
        assert len(results_b) >= 1
        assert B_DISTINCTIVE in _context_text(results_b)

    def test_missing_course_returns_empty_no_fallback(self):
        """关键修复点：未知课程不回退到全局最新树，返回空。"""
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")  # 全局最新树 = B

        results = rag_pipeline.retrieve(A_TERM, course_id="UNKNOWN", top_k=5)
        assert results == []

    def test_no_course_id_uses_latest_tree_legacy_behavior(self):
        """无 course_id 时保留旧行为：检索最后一次 build_index 的全局树。

        用以证明修复前的缺陷：A 的话题在无 course_id 时命中 B 的树（B 最后处理），
        即“向课程 A 学生提供课程 B 内容”。course_id 路径则修复了该行为。
        """
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")  # 全局最新树 = B

        results = rag_pipeline.retrieve(A_TERM, top_k=5)
        # A_TERM 在 B 的“深度学习”正文（“机器学习的子领域”）中也出现，故命中 B 的树
        assert len(results) >= 1
        ctx = _context_text(results)
        assert B_DISTINCTIVE in ctx
        assert A_DISTINCTIVE not in ctx

    def test_empty_query_does_not_raise(self):
        _process("A", COURSE_A_MD, "课程A")
        # 空查询不应抛异常
        results = rag_pipeline.retrieve("", course_id="A", top_k=3)
        assert isinstance(results, list)

    def test_top_k_larger_than_data(self):
        _process("A", COURSE_A_MD, "课程A")
        results = rag_pipeline.retrieve(A_TERM, course_id="A", top_k=1000)
        assert len(results) <= 1000
        assert isinstance(results, list)


class TestCourseIndexManagement:
    """has_course_index / clear_course_index。"""

    def test_has_course_index(self):
        assert rag_pipeline.has_course_index("A") is False
        _process("A", COURSE_A_MD, "课程A")
        assert rag_pipeline.has_course_index("A") is True
        assert rag_pipeline.has_course_index("B") is False
        assert rag_pipeline.has_course_index(None) is False

    def test_clear_course_index(self):
        _process("A", COURSE_A_MD, "课程A")
        assert rag_pipeline.has_course_index("A") is True
        assert rag_pipeline.clear_course_index("A") is True
        assert rag_pipeline.has_course_index("A") is False
        # 再次清除已不存在的索引返回 False
        assert rag_pipeline.clear_course_index("A") is False
        # 清除后检索回退为空（不回退到全局最新树）
        _process("B", COURSE_B_MD, "课程B")
        assert rag_pipeline.retrieve(A_TERM, course_id="A", top_k=5) == []


class TestQAServiceCourseScope:
    """QAService.retrieve_rag_context 正确传递 course_id。"""

    def test_retrieve_rag_context_threads_course_id_a(self):
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")
        ctx, sources = qa_service.retrieve_rag_context(
            A_TERM, top_k=5, course_id="A"
        )
        assert ctx != ""
        assert A_DISTINCTIVE in ctx
        assert B_DISTINCTIVE not in ctx
        assert isinstance(sources, list) and len(sources) >= 1
        # 来源元数据应包含基础字段
        first = sources[0]
        assert "path" in first and "score" in first and "match_type" in first

    def test_retrieve_rag_context_threads_course_id_b(self):
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")
        ctx, _ = qa_service.retrieve_rag_context(
            "深度学习", top_k=5, course_id="B"
        )
        assert ctx != ""
        assert B_DISTINCTIVE in ctx

    def test_retrieve_rag_context_missing_course_returns_empty(self):
        _process("A", COURSE_A_MD, "课程A")
        ctx, sources = qa_service.retrieve_rag_context(
            A_TERM, top_k=5, course_id="UNKNOWN"
        )
        assert ctx == ""
        assert sources == []

    def test_retrieve_rag_context_legacy_no_course_id(self):
        """无 course_id 保留旧行为：返回最新全局树内容。"""
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")
        ctx, _ = qa_service.retrieve_rag_context(A_TERM, top_k=5)
        # 旧行为命中 B 的树
        assert ctx != ""
        assert B_DISTINCTIVE in ctx


class TestAskQuestionWithRagCourseScope:
    """端到端：ask_question_with_rag 将 course_id 传递到检索层（使用 FakeLLM）。"""

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_ask_with_course_id_carries_rag_context(self):
        _process("A", COURSE_A_MD, "课程A")
        _process("B", COURSE_B_MD, "课程B")

        result = self._run(
            qa_service.ask_question_with_rag(
                question=A_TERM,
                course_context="",
                use_rag=True,
                rag_top_k=5,
                course_id="A",
            )
        )
        # RAG 上下文来自课程 A
        assert result["rag_context"] is not None
        assert A_DISTINCTIVE in result["rag_context"]
        assert B_DISTINCTIVE not in result["rag_context"]
        assert result["rag_sources"] is not None and len(result["rag_sources"]) >= 1
        # FakeLLMClient 返回固定文本，证明 LLM 调用链未被打断
        assert result["answer"] == "fake llm response"

    def test_ask_with_missing_course_id_no_rag_context(self):
        _process("A", COURSE_A_MD, "课程A")
        result = self._run(
            qa_service.ask_question_with_rag(
                question=A_TERM,
                course_context="",
                use_rag=True,
                rag_top_k=5,
                course_id="UNKNOWN",
            )
        )
        # 未知课程 -> 无 RAG 上下文，但仍正常生成回答（回退到 course_context）
        assert result["rag_context"] is None
        assert result["rag_sources"] is None
        assert result["answer"] == "fake llm response"

    def test_ask_backward_compat_no_course_id(self):
        """不传 course_id 时仍可正常调用（旧调用方兼容）。"""
        _process("A", COURSE_A_MD, "课程A")
        result = self._run(
            qa_service.ask_question_with_rag(
                question=A_TERM,
                course_context="",
                use_rag=True,
                rag_top_k=5,
            )
        )
        assert result["answer"] == "fake llm response"
