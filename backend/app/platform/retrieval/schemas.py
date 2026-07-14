"""
统一检索核心数据模型。

定义知识检索的「作用域」与「检索结果块」，作为所有 Retriever Provider 与
Retrieval Gateway 的统一契约。

设计要点：
- ``RetrievalScope`` 用显式 ``scope_type`` 区分课程作用域与知识库作用域，
  避免 ``course_id`` 与 ``knowledge_base_id`` 同值时在裸字符串注册表中冲突。
- ``RetrievedChunk`` 是面向上层（QA / 证据组装）的统一结果结构。当前树式
  关键词检索不具备的数据（页码、章节 ID 等）明确置空，绝不伪造。
- ``chunk_id`` 为树节点级过渡稳定标识（SHA-256(scope.key + 路径 + 内容摘要)），
  **不等同于未来 DocumentIR 持久化 chunk 主键**；不使用 Python 内置 ``hash()``
  以保证跨进程稳定可复现。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Literal, Optional

if TYPE_CHECKING:
    from app.platform.evidence.contracts import EvidenceSpan


ScopeType = Literal["course", "knowledge_base", "document"]


@dataclass(frozen=True)
class RetrievalScope:
    """
    知识检索作用域。

    ``course:12`` 与 ``knowledge_base:12`` 是两个互不冲突的作用域。
    ``scope_id`` 统一转为字符串；对象可哈希，可直接作为字典键。
    """

    scope_type: ScopeType
    scope_id: str

    def __post_init__(self) -> None:
        # dataclass(frozen=True) 下用 object.__setattr__ 规范化 scope_id 为 str。
        object.__setattr__(self, "scope_id", str(self.scope_id))

    @property
    def key(self) -> str:
        """注册表唯一键，形如 ``course:12`` / ``knowledge_base:5``。"""
        return f"{self.scope_type}:{self.scope_id}"

    @staticmethod
    def course(course_id: Any) -> "RetrievalScope":
        return RetrievalScope(scope_type="course", scope_id=course_id)

    @staticmethod
    def knowledge_base(kb_id: Any) -> "RetrievalScope":
        return RetrievalScope(scope_type="knowledge_base", scope_id=kb_id)

    @staticmethod
    def document(document_id: Any) -> "RetrievalScope":
        """A single-document scope for per-document retrieval.

        Missing document scope MUST return empty (no fallback to course/global).
        """
        return RetrievalScope(scope_type="document", scope_id=document_id)


@dataclass
class RetrievedChunk:
    """
    统一检索结果块。

    当前树式关键词检索仅能填充部分字段；未具备的字段保持 ``None``，
    不得用路径字符串冒充数据库章节 ID，不得凭空生成页码。

    Evidence fields (optional first, per P1-03 contract):
      ``artifact_id`` / ``document_id`` / ``unit_id`` / ``block_id`` reference
      P1-01 stable IDs when available.  Currently None for tree-keyword provider;
      populated when a DocumentIR-backed provider is used.
      ``evidence_spans`` carries ``EvidenceSpan`` objects when available.
    """

    chunk_id: str
    content: str
    scope: RetrievalScope

    source_id: Optional[str] = None
    source_name: Optional[str] = None
    chapter_id: Optional[str] = None
    chapter_title: Optional[str] = None
    page_number: Optional[int] = None

    retrieval_score: Optional[float] = None
    retrieval_source: str = "tree_keyword"
    match_type: Optional[str] = None
    path: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # ---- P1-03 evidence-preserving fields (optional, added in minor update) ----

    artifact_id: Optional[str] = None
    document_id: Optional[str] = None
    unit_id: Optional[str] = None
    block_id: Optional[str] = None
    evidence_spans: List["EvidenceSpan"] = field(default_factory=list)


def _normalize_for_id(text: str) -> str:
    """
    规范化文本以生成稳定的 chunk_id 输入。

    统一：Unicode NFC 规范化、CRLF/CR -> LF、首尾空白、连续空白折叠。
    规范化路径分隔符（``\\`` -> ``/``），使不同来源的相同路径生成相同 id。
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\", "/")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stable_chunk_id(scope: RetrievalScope, node_path: str, content: str) -> str:
    """
    生成跨进程稳定的过渡 chunk_id。

    输入：作用域键 + 树节点路径 + 内容前缀（160 字符），均经 ``_normalize_for_id``
    规范化，避免换行符差异（``\\r\\n`` vs ``\\n``）、多余空白、路径分隔符差异、
    Unicode 不同表示形式导致相同内容生成不同 id。
    输出：SHA-256 摘要前 16 个十六进制字符。

    说明：这是树节点级标识，节点路径由文档标题层级决定，可复现；
    未来 DocumentIR 持久化后会替换为数据库主键。
    """
    raw = "|".join(
        [
            _normalize_for_id(scope.key),
            _normalize_for_id(node_path),
            _normalize_for_id(content[:160]),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
