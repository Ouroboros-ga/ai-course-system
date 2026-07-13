"""
RAG 工具入口与集成

将公式占位替换、表格展平、IK 分词、树状检索整合为统一的 RAG 流水线，
提供面向上层服务的高层 API。

完整逻辑链条：
  Docling 结构化感知 → 公式占位替换 → 表格展平 → IK 分词索引 → 树状 RAG 检索 → 商业 API

使用方式：
  from app.common.rag_utils import rag_pipeline

  # 处理文档
  result = rag_pipeline.process_document(markdown_text, doc_name="高等数学")

  # 检索
  results = rag_pipeline.retrieve("什么是傅里叶变换")

  # 生成回答（结合检索结果 + 商业 LLM API）
  answer = await rag_pipeline.generate_answer("什么是傅里叶变换", top_k=3)
"""

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.common.RAG.formula_placeholder import FormulaPlaceholderReplacer, FormulaReplaceResult
from app.common.RAG.table_flattener import TableFlattener, FlattenResult
from app.common.RAG.ik_tokenizer import IKTokenizer, TokenizeResult, EducationalDictionary
from app.common.RAG.tree_rag import (
    DoclingTreeBuilder,
    TreeRAGRetriever,
    TreeBuildResult,
    TreeNode,
    RetrievalResult,
)
from app.platform.retrieval import RetrievalScope, retrieval_gateway

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 无作用域（裸全局）检索的弃用提示，每进程只告警一次，避免测试噪声。
_legacy_no_scope_warned = False


@dataclass
class DocumentProcessResult:
    """文档处理结果"""

    original_text: str
    processed_text: str
    formula_result: FormulaReplaceResult
    table_results: List[FlattenResult]
    tokenize_result: TokenizeResult
    tree_result: TreeBuildResult
    doc_metadata: Dict[str, Any]


@dataclass
class RAGAnswer:
    """RAG 生成的回答"""

    question: str
    answer: str
    sources: List[Dict[str, Any]]
    retrieval_count: int
    formula_count: int
    table_count: int
    domain_terms: List[str]


class RAGPipeline:
    """
    RAG 流水线

    整合 Docling 文档处理的完整逻辑链：
    1. 公式占位替换：将 LaTeX 公式替换为语义化占位符
    2. 表格展平：将 Markdown 表格转为自然语言描述
    3. IK 分词索引：对处理后的文本进行教育场景定制分词
    4. 树状检索：基于文档结构的知识树检索
    5. 商业 API 集成：结合 LLM 生成最终回答
    """

    def __init__(
        self,
        formula_prefix: str = "FORMULA",
        table_max_rows: int = 50,
        rag_top_k: int = 5,
        rag_context_window: int = 1,
    ):
        self._formula_replacer = FormulaPlaceholderReplacer(
            placeholder_prefix=formula_prefix
        )
        self._table_flattener = TableFlattener(max_row_desc=table_max_rows)
        self._tokenizer = IKTokenizer()
        self._tree_builder = DoclingTreeBuilder()
        self._rag_top_k = rag_top_k
        self._rag_context_window = rag_context_window
        self._retriever = TreeRAGRetriever(
            top_k=rag_top_k,
            context_window=rag_context_window,
        )

        self._processed_docs: Dict[str, DocumentProcessResult] = {}
        # 统一检索网关：课程 / 知识库作用域隔离的注册表由 gateway 持有。
        # 本兼容层通过 gateway.index / gateway.get_raw_retriever 委托，
        # 不再自维护 _course_retrievers 裸字符串注册表（避免 course/kb ID 冲突）。
        self._gateway = retrieval_gateway

    def process_document(
        self,
        markdown_text: str,
        doc_name: str = "",
        doc_id: Optional[str] = None,
        scope: Optional[RetrievalScope] = None,
    ) -> DocumentProcessResult:
        """
        处理单个文档，执行完整的 RAG 预处理流水线

        流程：
        1. 公式占位替换
        2. 表格展平
        3. IK 分词
        4. 构建知识树
        5. 建立检索索引（作用域隔离）

        Args:
            scope: 显式检索作用域。传入时按 ``scope.key`` 注册到统一网关，
                课程与知识库作用域互不冲突。推荐上传主链传
                ``RetrievalScope.course(course_id)``、知识库导入传
                ``RetrievalScope.knowledge_base(kb_id)``。
            doc_id: 遗留参数。``scope`` 未传时，按 P0 行为视为课程作用域
                ``course:<doc_id>``（会产生一次性弃用告警）。新代码应传 ``scope``。
        """
        logger.info(f"开始处理文档: {doc_name or '未命名'}")

        # Step 1: 公式占位替换
        formula_result = self._formula_replacer.replace(markdown_text)
        text_after_formula = formula_result.processed_text
        logger.info(
            f"  [Step 1] 公式占位替换: "
            f"{formula_result.formula_count}个公式被替换"
        )

        # Step 2: 表格展平
        table_results = self._table_flattener.flatten_all(text_after_formula)
        text_after_table = self._table_flattener.replace_tables_in_text(
            text_after_formula
        )
        logger.info(
            f"  [Step 2] 表格展平: {len(table_results)}个表格被展平"
        )

        # Step 3: IK 分词
        tokenize_result = self._tokenizer.tokenize(text_after_table)
        logger.info(
            f"  [Step 3] IK分词: "
            f"{tokenize_result.word_count}个词项, "
            f"{tokenize_result.domain_term_count}个领域术语"
        )

        # Step 4: 构建知识树
        self._tree_builder = DoclingTreeBuilder(doc_name=doc_name)
        tree_result = self._tree_builder.build(text_after_table)
        logger.info(
            f"  [Step 4] 知识树构建: "
            f"{tree_result.total_nodes}个节点, "
            f"最大深度{tree_result.max_depth}"
        )

        # Step 5: 建立检索索引
        # 5a. 旧全局树（保留无作用域 retrieve 的兼容行为；已弃用，见 retrieve）
        self._retriever.build_index(tree_result)
        # 5b. 作用域隔离注册：course:<id> 与 knowledge_base:<id> 互不冲突。
        register_scope: Optional[RetrievalScope]
        if scope is not None:
            register_scope = scope
        elif doc_id is not None:
            # 遗留调用：仅传 doc_id，按 P0 行为视为课程作用域。
            global _legacy_no_scope_warned
            if not _legacy_no_scope_warned:
                warnings.warn(
                    "rag_pipeline.process_document called with doc_id but no explicit "
                    "scope; defaulting to course scope. Pass RetrievalScope explicitly. "
                    "Legacy doc_id-only indexing is deprecated.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                _legacy_no_scope_warned = True
            register_scope = RetrievalScope.course(str(doc_id))
        else:
            register_scope = None

        if register_scope is not None:
            self._gateway.index(register_scope, tree_result)
            logger.info(f"  [Step 5] 作用域检索器已注册: {register_scope.key}")
        logger.info("  [Step 5] 检索索引构建完成")

        # 保存处理结果
        result = DocumentProcessResult(
            original_text=markdown_text,
            processed_text=text_after_table,
            formula_result=formula_result,
            table_results=table_results,
            tokenize_result=tokenize_result,
            tree_result=tree_result,
            doc_metadata={
                "doc_name": doc_name,
                "doc_id": doc_id,
                "original_length": len(markdown_text),
                "processed_length": len(text_after_table),
                "formula_count": formula_result.formula_count,
                "table_count": len(table_results),
                "domain_term_count": tokenize_result.domain_term_count,
                "tree_nodes": tree_result.total_nodes,
                "tree_depth": tree_result.max_depth,
            },
        )

        if doc_id:
            self._processed_docs[doc_id] = result

        logger.info(f"文档处理完成: {doc_name}")
        return result

    def retrieve(
        self,
        query: str,
        strategy: str = "hybrid",
        top_k: int = 5,
        course_id: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        """
        执行 RAG 检索

        Args:
            query: 查询文本
            strategy: 检索策略 (keyword/path/hybrid)
            top_k: 返回结果数
            course_id: 课程 ID。传入时只检索该课程的知识树；
                若当前进程未为该课程构建过树（例如进程重启后、或课程在本修复前上传），
                返回空列表，**不回退**到最后一次构建的全局树，以避免跨课程污染。
                不传时保留旧行为：检索最后一次 process_document 构建的全局树。
        """
        if course_id is not None and str(course_id) != "":
            scope = RetrievalScope.course(course_id)
            retriever = self._gateway.get_raw_retriever(scope)
            if retriever is None:
                logger.info(
                    f"检索跳过: 当前进程未为课程 {scope.key} 构建知识树，"
                    f"返回空结果（避免跨课程污染，问答将回退到课程文档上下文）"
                )
                return []
            results = retriever.retrieve(query, strategy=strategy, top_k=top_k)
        else:
            # 无作用域检索：使用“最后一次构建”的全局树。该路径已弃用，
            # 生产问答主链应通过 RetrievalGateway + 显式 scope 检索。
            global _legacy_no_scope_warned
            if not _legacy_no_scope_warned:
                import inspect

                caller = inspect.stack()[1]
                caller_loc = (
                    f"{caller.filename}:{caller.lineno} ({caller.function})"
                    if caller
                    else "unknown"
                )
                warnings.warn(
                    "rag_pipeline.retrieve called without course_id/scope; using the "
                    "legacy last-built global tree. This is deprecated; use "
                    "RetrievalGateway.retrieve with an explicit RetrievalScope. "
                    f"Called from: {caller_loc}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                _legacy_no_scope_warned = True
            results = self._retriever.retrieve(query, strategy=strategy, top_k=top_k)
        logger.info(
            f"检索完成: query='{query}', strategy={strategy}, "
            f"course_id={course_id}, 返回{len(results)}个结果"
        )
        return results

    def get_context_for_result(
        self, result: RetrievalResult, window: Optional[int] = None
    ) -> str:
        """
        获取检索结果的上下文文本。

        委托给检索器实现。该方法仅依赖 result.node 自身结构，
        与具体检索器实例无关，因此无论结果来自全局树还是课程范围树均可使用。
        """
        return self._retriever.get_context_for_result(result, window=window)

    def has_course_index(self, course_id: Any) -> bool:
        """当前进程是否已为指定课程构建过知识树。"""
        if course_id is None:
            return False
        return self._gateway.has_scope(RetrievalScope.course(course_id))

    def clear_course_index(self, course_id: Any) -> bool:
        """
        清除指定课程的内存检索器。

        用于课程删除/重新上传场景，以及测试隔离。返回是否确实存在并清除。
        注意：仅清除进程内索引，不影响数据库中已持久化的文档内容。
        """
        if course_id is None:
            return False
        return self._gateway.clear_scope(RetrievalScope.course(course_id))

    def clear_all_scopes(self) -> int:
        """
        清除所有作用域（课程与知识库）的内存检索器。

        主要用于测试隔离。返回清除数量。仅影响进程内索引。
        """
        return self._gateway.clear_all()

    async def generate_answer(
        self,
        question: str,
        top_k: int = 5,
        strategy: str = "hybrid",
        system_prompt: Optional[str] = None,
        course_id: Optional[Any] = None,
    ) -> RAGAnswer:
        """
        生成 RAG 回答

        结合检索结果和商业 LLM API 生成最终回答
        """
        retrieval_results = self.retrieve(
            question, strategy=strategy, top_k=top_k, course_id=course_id
        )

        context_parts = []
        sources = []
        for i, result in enumerate(retrieval_results):
            context = self._retriever.get_context_for_result(result)
            context_parts.append(f"【来源{i+1}: {result.context_path}】\n{context}")
            sources.append({
                "path": result.context_path,
                "score": result.score,
                "match_type": result.match_type,
                "content_preview": result.matched_content[:200],
            })

        context_text = "\n\n---\n\n".join(context_parts)

        if not system_prompt:
            system_prompt = (
                "你是一个专业的教育知识助手。请根据提供的参考资料回答问题。"
                "如果参考资料中没有相关信息，请明确说明。"
                "回答时请引用具体的来源章节。"
            )

        prompt = f"参考资料：\n{context_text}\n\n问题：{question}"

        answer_text = ""
        try:
            from app.common.llm_client import llm_client
            answer_text = await llm_client.simple_chat(
                prompt=prompt,
                system_prompt=system_prompt,
            )
        except Exception as e:
            logger.error(f"LLM 生成回答失败: {e}")
            answer_text = f"[LLM 生成失败] 基于检索结果: {context_text[:500]}"

        formula_count = 0
        table_count = 0
        domain_terms = []

        if self._processed_docs:
            latest_doc = list(self._processed_docs.values())[-1]
            formula_count = latest_doc.formula_result.formula_count
            table_count = len(latest_doc.table_results)
            domain_terms = latest_doc.tokenize_result.domain_terms

        return RAGAnswer(
            question=question,
            answer=answer_text,
            sources=sources,
            retrieval_count=len(retrieval_results),
            formula_count=formula_count,
            table_count=table_count,
            domain_terms=domain_terms,
        )

    def get_pipeline_stats(self) -> Dict[str, Any]:
        """获取流水线统计信息"""
        stats = {
            "processed_docs": len(self._processed_docs),
            "tree_summary": self._retriever.get_tree_summary(),
        }

        if self._processed_docs:
            latest = list(self._processed_docs.values())[-1]
            stats["latest_doc"] = latest.doc_metadata

        return stats


rag_pipeline = RAGPipeline()
