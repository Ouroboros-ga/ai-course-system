"""NX-R1a 证据规范：locator / coverage / 预算 / 引用登记。

任务书 T3 冻结语义：
- 证据对象必含 evidence_id、attachment_id、source_title、locator、excerpt、
  coverage（fulltext_excerpt / abstract_only）、is_supplementary；内容来自
  实际返回块。source_title 为用户上传文件标签（source_kind=upload_label），
  不伪装已验证书目信息。
- locator 来自附件解析块的原始定位；页面映射不可用时如实为 None，
  不编造 page 1。
- 预算：单次 ≤3 篇、≤12 条证据、每条 ≤1200 字符、总计 ≤12000 字符；
  触发预算必须如实标记 truncated。
- 引用登记（进程内）：模型只能引用服务端登记过的 evidence_id；登记条目
  绑定 owner+session，跨用户/跨会话不可解析。重启即清（属本批已知限制，
  报告引用随 Artifact 落盘不受影响）。
"""
from __future__ import annotations

import hashlib
from typing import Any

MAX_ATTACHMENTS_PER_CALL = 3
MAX_EVIDENCES_PER_CALL = 12
EVIDENCE_EXCERPT_MAX = 1200
EVIDENCE_TOTAL_CHARS_MAX = 12000
# 单附件解析总字符低于阈值 → abstract_only（大概率只有首页/摘要被解析出来，
# 不能冒充读过全文）。
ABSTRACT_ONLY_THRESHOLD_CHARS = 500

COVERAGE_FULLTEXT = "fulltext_excerpt"
COVERAGE_ABSTRACT = "abstract_only"
_REGISTRY_MAX_ENTRIES = 500


def _hash10(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def evidence_id_for(attachment_id: str, locator: str | None, excerpt: str) -> str:
    """确定性证据 id：同附件同定位同摘录 → 同 id（幂等登记不重复计数）。"""
    raw = f"{attachment_id}|{locator or ''}|{excerpt}"
    return f"ev-{_hash10(raw)}"


def build_evidence(
    *,
    attachment_id: str,
    filename: str,
    block: dict[str, Any],
    attachment_total_chars: int,
) -> dict[str, Any] | None:
    """从附件解析块构建证据对象；空块返回 None。

    coverage 按该附件实际解析量机械判定：总字符低于阈值即 abstract_only——
    这是解析产物的事实边界，不依赖模型自述。
    """
    if not isinstance(block, dict):
        return None
    text = block.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    excerpt = text.strip()[:EVIDENCE_EXCERPT_MAX]
    locator = block.get("locator")
    if not isinstance(locator, str) or not locator.strip():
        locator = None  # 页面映射缺失：如实 None，引用时明确标注，不编造
    coverage = COVERAGE_ABSTRACT if attachment_total_chars < ABSTRACT_ONLY_THRESHOLD_CHARS else COVERAGE_FULLTEXT
    return {
        "evidence_id": evidence_id_for(attachment_id, locator, excerpt),
        "attachment_id": attachment_id,
        "source_title": (filename or "用户上传文件")[:120],
        "source_kind": "upload_label",
        "locator": locator,
        "excerpt": excerpt,
        "coverage": coverage,
        "is_supplementary": True,
    }


def citation_line(index: int, evidence: dict[str, Any]) -> str:
    """渲染单条引用：来源（上传标签）· locator · coverage · 摘录。"""
    locator = evidence.get("locator")
    locator_text = f"定位 {locator}" if locator else "定位缺失（解析未提供页码映射）"
    coverage = evidence.get("coverage") or COVERAGE_FULLTEXT
    excerpt = (evidence.get("excerpt") or "")[:200]
    return (
        f"[{index}] {evidence.get('source_title', '')} · {locator_text} · "
        f"{coverage}\n  摘录：{excerpt}"
    )


class EvidenceRegistry:
    """进程内证据登记：evidence_id → (owner, session, evidence)。

    FIFO 容量上限防泄漏；resolve 校验 owner+session，模型引用他人/他会话
    的 evidence_id 一律拒绝。
    """

    def __init__(self, max_entries: int = _REGISTRY_MAX_ENTRIES) -> None:
        self._entries: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self._order: list[str] = []
        self._max = max_entries

    def register(self, user_id: str, session_id: str, evidences: list[dict[str, Any]]) -> None:
        for evidence in evidences:
            eid = str(evidence.get("evidence_id") or "")
            if not eid:
                continue
            if eid not in self._entries:
                self._order.append(eid)
                while len(self._order) > self._max:
                    self._entries.pop(self._order.pop(0), None)
            self._entries[eid] = (user_id, session_id, evidence)

    def resolve(
        self, evidence_id: str, *, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        entry = self._entries.get((evidence_id or "").strip())
        if entry is None:
            return None
        owner, sess, evidence = entry
        if owner != (user_id or "") or sess != (session_id or ""):
            return None  # 跨用户/跨会话引用：与不存在同等对待
        return evidence


_registry = EvidenceRegistry()


def get_registry() -> EvidenceRegistry:
    return _registry
