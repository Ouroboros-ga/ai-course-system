"""
Docling 结构感知的树状 RAG 检索架构

基于 Docling 输出的 Markdown 文档结构，构建层次化的知识树，
实现精准的结构感知检索。

核心思路：
  1. 解析 Docling Markdown 的标题层级，构建知识树
  2. 每个树节点包含：标题、内容、子节点、元数据
  3. 检索时沿树结构定位最相关子树，避免平铺检索的语义混淆
  4. 支持多种检索策略：结构路径检索、语义检索、混合检索
  5. 结合商业 Embedding API 生成向量

树状 RAG 的优势：
  - 结构感知：保留文档的章节层级关系
  - 精准定位：通过路径缩小检索范围
  - 上下文完整：返回整个子树而非碎片文本
  - 避免混淆：不同章节的同名概念不会混淆
"""

import json
import logging
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    """知识树节点类型"""

    ROOT = "root"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FORMULA = "formula"
    CODE = "code"
    LIST = "list"
    IMAGE = "image"


@dataclass
class TreeNode:
    """
    知识树节点

    每个节点对应文档中的一个结构单元，
    包含内容、层级信息和检索元数据
    """

    node_id: str
    node_type: NodeType
    title: str
    content: str
    level: int
    children: List["TreeNode"] = field(default_factory=list)
    parent_id: Optional[str] = None
    path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    token_count: int = 0

    def to_dict(self, include_children: bool = True) -> Dict:
        result = {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "title": self.title,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "level": self.level,
            "path": self.path,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }
        if include_children:
            result["children"] = [c.to_dict() for c in self.children]
        return result

    def get_full_content(self, max_depth: int = -1) -> str:
        """获取节点及其子节点的完整内容"""
        parts = []
        if self.title:
            parts.append(f"{'#' * self.level} {self.title}" if self.level > 0 else self.title)
        if self.content:
            parts.append(self.content)

        if max_depth != 0:
            for child in self.children:
                child_content = child.get_full_content(max_depth - 1 if max_depth > 0 else -1)
                if child_content:
                    parts.append(child_content)

        return "\n\n".join(parts)

    def get_leaf_nodes(self) -> List["TreeNode"]:
        """获取所有叶子节点"""
        if not self.children:
            return [self]
        leaves = []
        for child in self.children:
            leaves.extend(child.get_leaf_nodes())
        return leaves

    def find_by_path(self, path_prefix: str) -> Optional["TreeNode"]:
        """按路径前缀查找节点"""
        if self.path.startswith(path_prefix):
            return self
        for child in self.children:
            result = child.find_by_path(path_prefix)
            if result:
                return result
        return None

    def find_by_id(self, node_id: str) -> Optional["TreeNode"]:
        """按节点ID查找"""
        if self.node_id == node_id:
            return self
        for child in self.children:
            result = child.find_by_id(node_id)
            if result:
                return result
        return None

    def count_nodes(self) -> int:
        """统计节点总数"""
        count = 1
        for child in self.children:
            count += child.count_nodes()
        return count


@dataclass
class RetrievalResult:
    """检索结果"""

    node: TreeNode
    score: float
    match_type: str
    matched_content: str
    context_path: str


@dataclass
class TreeBuildResult:
    """知识树构建结果"""

    root: TreeNode
    total_nodes: int
    max_depth: int
    node_type_counts: Dict[str, int]
    doc_metadata: Dict[str, Any]


class DoclingTreeBuilder:
    """
    Docling 结构感知知识树构建器

    解析 Docling 输出的 Markdown 文件，根据标题层级构建知识树。
    Docling 的 Markdown 输出具有明确的结构特征：
    - 标题层级 (# ~ ######)
    - 代码块 (```)
    - 表格 (|...|)
    - 公式 ($$...$$)
    - 列表 (- / 1.)
    """

    _HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    _CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    _TABLE_BLOCK_PATTERN = re.compile(
        r"(?:^[ \t]*\|?.+\|[ \t]*$\n?)+", re.MULTILINE
    )
    _FORMULA_BLOCK_PATTERN = re.compile(r"\$\$[\s\S]*?\$\$", re.MULTILINE)
    _LIST_PATTERN = re.compile(r"^[\s]*[-*+]\s+.+$|^[\s]*\d+\.\s+.+$", re.MULTILINE)

    def __init__(self, doc_name: str = ""):
        self._doc_name = doc_name
        self._node_counter = 0

    def _next_id(self) -> str:
        self._node_counter += 1
        return f"node_{self._node_counter:04d}"

    def build(self, markdown_text: str) -> TreeBuildResult:
        """
        从 Docling Markdown 构建知识树
        """
        self._node_counter = 0

        root = TreeNode(
            node_id="root",
            node_type=NodeType.ROOT,
            title=self._doc_name or "文档",
            content="",
            level=0,
            path="",
        )

        sections = self._split_by_headings(markdown_text)

        for heading_level, heading_text, content in sections:
            self._add_section_to_tree(root, heading_level, heading_text, content)

        total_nodes = root.count_nodes()
        max_depth = self._compute_max_depth(root)
        type_counts = self._count_node_types(root)

        doc_metadata = {
            "doc_name": self._doc_name,
            "total_chars": len(markdown_text),
            "total_sections": len(sections),
        }

        logger.info(
            f"知识树构建完成: {total_nodes}个节点, "
            f"最大深度{max_depth}, "
            f"类型分布{type_counts}"
        )

        return TreeBuildResult(
            root=root,
            total_nodes=total_nodes,
            max_depth=max_depth,
            node_type_counts=type_counts,
            doc_metadata=doc_metadata,
        )

    def _split_by_headings(
        self, text: str
    ) -> List[Tuple[int, str, str]]:
        """
        按标题拆分文档

        返回: [(标题级别, 标题文本, 标题下内容)]
        """
        sections: List[Tuple[int, str, str]] = []

        heading_positions = []
        for match in self._HEADING_PATTERN.finditer(text):
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_positions.append((match.start(), match.end(), level, title))

        if not heading_positions:
            if text.strip():
                sections.append((1, "文档内容", text.strip()))
            return sections

        if heading_positions[0][0] > 0:
            preamble = text[:heading_positions[0][0]].strip()
            if preamble:
                sections.append((1, "概述", preamble))

        for i, (start, end, level, title) in enumerate(heading_positions):
            next_start = (
                heading_positions[i + 1][0]
                if i + 1 < len(heading_positions)
                else len(text)
            )
            content = text[end:next_start].strip()
            sections.append((level, title, content))

        return sections

    def _add_section_to_tree(
        self,
        parent: TreeNode,
        level: int,
        title: str,
        content: str,
    ) -> None:
        """将一个章节添加到知识树"""
        node_id = self._next_id()
        path = f"{parent.path}/{title}" if parent.path else title

        content_parts = self._parse_content_elements(content)

        main_content = content_parts.get("text", "")
        node_type = self._determine_node_type(level, content_parts)

        node = TreeNode(
            node_id=node_id,
            node_type=node_type,
            title=title,
            content=main_content,
            level=level,
            parent_id=parent.node_id,
            path=path,
            token_count=len(main_content),
            metadata={
                "has_table": bool(content_parts.get("tables")),
                "has_formula": bool(content_parts.get("formulas")),
                "has_code": bool(content_parts.get("code_blocks")),
                "has_list": bool(content_parts.get("lists")),
                "element_counts": {
                    k: len(v) for k, v in content_parts.items() if isinstance(v, list)
                },
            },
        )

        for table_text in content_parts.get("tables", []):
            table_node = TreeNode(
                node_id=self._next_id(),
                node_type=NodeType.TABLE,
                title="",
                content=table_text,
                level=level + 1,
                parent_id=node_id,
                path=f"{path}/[表格]",
                token_count=len(table_text),
            )
            node.children.append(table_node)

        for formula_text in content_parts.get("formulas", []):
            formula_node = TreeNode(
                node_id=self._next_id(),
                node_type=NodeType.FORMULA,
                title="",
                content=formula_text,
                level=level + 1,
                parent_id=node_id,
                path=f"{path}/[公式]",
                token_count=len(formula_text),
            )
            node.children.append(formula_node)

        for code_text in content_parts.get("code_blocks", []):
            code_node = TreeNode(
                node_id=self._next_id(),
                node_type=NodeType.CODE,
                title="",
                content=code_text,
                level=level + 1,
                parent_id=node_id,
                path=f"{path}/[代码]",
                token_count=len(code_text),
            )
            node.children.append(code_node)

        if level > parent.level:
            parent.children.append(node)
        else:
            target = self._find_ancestor_at_level(parent, level - 1)
            if target:
                target.children.append(node)
            else:
                parent.children.append(node)

    def _find_ancestor_at_level(
        self, node: TreeNode, target_level: int
    ) -> Optional[TreeNode]:
        """在树中向上查找指定层级的祖先节点"""
        if node.level == target_level:
            return node
        if node.level < target_level:
            return node
        return None

    def _parse_content_elements(self, content: str) -> Dict[str, Any]:
        """解析内容中的结构元素"""
        result: Dict[str, Any] = {
            "text": content,
            "tables": [],
            "formulas": [],
            "code_blocks": [],
            "lists": [],
        }

        tables = self._TABLE_BLOCK_PATTERN.findall(content)
        if tables:
            result["tables"] = tables

        formulas = self._FORMULA_BLOCK_PATTERN.findall(content)
        if formulas:
            result["formulas"] = formulas

        code_blocks = self._CODE_BLOCK_PATTERN.findall(content)
        if code_blocks:
            result["code_blocks"] = code_blocks

        list_items = self._LIST_PATTERN.findall(content)
        if list_items:
            result["lists"] = list_items

        return result

    def _determine_node_type(
        self, level: int, content_parts: Dict[str, Any]
    ) -> NodeType:
        """确定节点类型"""
        if level == 1:
            return NodeType.CHAPTER
        elif level == 2:
            return NodeType.SECTION
        elif level >= 3:
            return NodeType.SUBSECTION
        return NodeType.PARAGRAPH

    def _compute_max_depth(self, node: TreeNode) -> int:
        """计算树的最大深度"""
        if not node.children:
            return node.level
        return max(self._compute_max_depth(c) for c in node.children)

    def _count_node_types(self, node: TreeNode) -> Dict[str, int]:
        """统计各类型节点数量"""
        counts: Dict[str, int] = {}
        self._collect_type_counts(node, counts)
        return counts

    def _collect_type_counts(
        self, node: TreeNode, counts: Dict[str, int]
    ) -> None:
        t = node.node_type.value
        counts[t] = counts.get(t, 0) + 1
        for child in node.children:
            self._collect_type_counts(child, counts)


class TreeRAGRetriever:
    """
    树状 RAG 检索器

    基于知识树的结构感知检索，支持多种检索策略：
    1. 关键词检索：基于 IK 分词的词项匹配
    2. 结构路径检索：按章节路径定位
    3. 混合检索：结合关键词和结构信息

    检索流程：
    1. 对查询进行分词
    2. 在知识树中匹配相关节点
    3. 按结构路径聚合结果
    4. 返回最相关的子树上下文
    """

    def __init__(
        self,
        top_k: int = 5,
        context_window: int = 1,
        min_score: float = 0.1,
    ):
        self._top_k = top_k
        self._context_window = context_window
        self._min_score = min_score
        self._tree: Optional[TreeNode] = None
        self._index: Dict[str, List[Tuple[TreeNode, float]]] = {}

    def build_index(self, tree_result: TreeBuildResult) -> None:
        """
        构建检索索引

        为知识树中的每个节点建立倒排索引
        """
        self._tree = tree_result.root
        self._index = {}

        self._build_inverted_index(self._tree)

        logger.info(
            f"检索索引构建完成: "
            f"{len(self._index)}个索引项, "
            f"{tree_result.total_nodes}个节点"
        )

    def _build_inverted_index(self, node: TreeNode) -> None:
        """构建倒排索引"""
        from app.common.ik_tokenizer import IKTokenizer

        tokenizer = IKTokenizer()

        searchable_text = f"{node.title} {node.content}"
        result = tokenizer.tokenize(searchable_text)

        for token in result.tokens:
            if token.token_type.value in ("PUNCTUATION",):
                continue

            term = token.text.lower()
            if term not in self._index:
                self._index[term] = []

            score = 1.0
            if token.is_domain_term:
                score = 2.0
            if token.token_type.value == "FORMULA_PLACEHOLDER":
                score = 1.5

            self._index[term].append((node, score))

        for child in node.children:
            self._build_inverted_index(child)

    def retrieve(
        self,
        query: str,
        strategy: str = "hybrid",
        top_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """
        执行检索

        Args:
            query: 查询文本
            strategy: 检索策略 (keyword/path/hybrid)
            top_k: 返回结果数
        """
        k = top_k or self._top_k

        if strategy == "keyword":
            results = self._keyword_retrieve(query)
        elif strategy == "path":
            results = self._path_retrieve(query)
        else:
            keyword_results = self._keyword_retrieve(query)
            path_results = self._path_retrieve(query)
            results = self._merge_results(keyword_results, path_results)

        results.sort(key=lambda r: r.score, reverse=True)
        results = [r for r in results if r.score >= self._min_score]

        return results[:k]

    def _keyword_retrieve(self, query: str) -> List[RetrievalResult]:
        """关键词检索"""
        from app.common.ik_tokenizer import IKTokenizer

        tokenizer = IKTokenizer()
        query_result = tokenizer.tokenize(query)

        node_scores: Dict[str, Tuple[TreeNode, float]] = {}

        for token in query_result.tokens:
            if token.token_type.value == "PUNCTUATION":
                continue

            term = token.text.lower()
            if term in self._index:
                for node, base_score in self._index[term]:
                    boost = 2.0 if token.is_domain_term else 1.0
                    score = base_score * boost

                    if node.node_id in node_scores:
                        old_node, old_score = node_scores[node.node_id]
                        node_scores[node.node_id] = (old_node, old_score + score)
                    else:
                        node_scores[node.node_id] = (node, score)

        results = []
        for node_id, (node, score) in node_scores.items():
            results.append(RetrievalResult(
                node=node,
                score=score,
                match_type="keyword",
                matched_content=node.content[:300],
                context_path=node.path,
            ))

        return results

    def _path_retrieve(self, query: str) -> List[RetrievalResult]:
        """结构路径检索"""
        if not self._tree:
            return []

        results = []
        query_lower = query.lower()

        self._search_by_path(self._tree, query_lower, results)

        return results

    def _search_by_path(
        self,
        node: TreeNode,
        query: str,
        results: List[RetrievalResult],
        depth: int = 0,
    ) -> None:
        """递归搜索路径匹配的节点"""
        path_lower = node.path.lower()
        title_lower = node.title.lower()

        score = 0.0
        if query in path_lower:
            score = 3.0 / (depth + 1)
        elif query in title_lower:
            score = 2.5 / (depth + 1)

        path_parts = query.split()
        if len(path_parts) > 1:
            match_count = sum(1 for p in path_parts if p in path_lower)
            if match_count > 0:
                score = max(score, match_count / len(path_parts) * 2.0)

        if score > 0:
            results.append(RetrievalResult(
                node=node,
                score=score,
                match_type="path",
                matched_content=node.get_full_content(max_depth=1)[:500],
                context_path=node.path,
            ))

        for child in node.children:
            self._search_by_path(child, query, results, depth + 1)

    def _merge_results(
        self,
        keyword_results: List[RetrievalResult],
        path_results: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """合并关键词和路径检索结果"""
        merged: Dict[str, RetrievalResult] = {}

        for r in keyword_results:
            merged[r.node.node_id] = RetrievalResult(
                node=r.node,
                score=r.score,
                match_type="keyword",
                matched_content=r.matched_content,
                context_path=r.context_path,
            )

        for r in path_results:
            if r.node.node_id in merged:
                existing = merged[r.node.node_id]
                merged[r.node.node_id] = RetrievalResult(
                    node=r.node,
                    score=existing.score + r.score * 1.5,
                    match_type="hybrid",
                    matched_content=r.matched_content,
                    context_path=r.context_path,
                )
            else:
                merged[r.node.node_id] = r

        return list(merged.values())

    def get_context_for_result(
        self, result: RetrievalResult, window: Optional[int] = None
    ) -> str:
        """
        获取检索结果的上下文

        返回匹配节点及其前后兄弟节点的完整内容，
        确保返回的上下文在结构上完整
        """
        w = window or self._context_window
        node = result.node

        context_parts = []

        context_parts.append(node.get_full_content())

        if node.children:
            for child in node.children[:3]:
                context_parts.append(child.get_full_content(max_depth=0))

        return "\n\n".join(context_parts)

    def get_tree_summary(self) -> Dict:
        """获取知识树摘要信息"""
        if not self._tree:
            return {}

        return {
            "root_title": self._tree.title,
            "total_nodes": self._tree.count_nodes(),
            "max_depth": self._compute_depth(self._tree),
            "index_terms": len(self._index),
            "chapters": [
                {"title": c.title, "path": c.path, "children": len(c.children)}
                for c in self._tree.children
            ],
        }

    def _compute_depth(self, node: TreeNode) -> int:
        if not node.children:
            return 1
        return 1 + max(self._compute_depth(c) for c in node.children)
