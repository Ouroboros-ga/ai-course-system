"""NX-R1a 证据规范：locator / coverage / 预算 / 引用登记。

任务书 T3 冻结语义：
- 证据对象必含 evidence_id、attachment_id、source_title、locator、excerpt、
  coverage（fulltext_excerpt / abstract_only）、is_supplementary；内容来自
  实际返回块。source_title 为用户上传文件标签（source_kind=upload_label），
  不伪装已验证书目信息。
- locator 来自附件解析块的原始定位；页面映射不可用时如实为 None，
  不编造 page 1。
- 预算：单次 ≤3 篇、≤12 条证据、每条 ≤2400 字符、总计 ≤40000 字符；
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
# 2026-09-11 调整：1200→2400 / 12000→40000。
# 原预算下一次取证最多给模型 1.2 万字符原文（≈6000–8000 汉字），而报告只能引用
# 已登记证据——素材量直接封住报告深度（写长就触发伪引用风险）。V4 为 1M 上下文，
# 4 万字符注入仅占 2–3%，容量不是约束，故放宽。
EVIDENCE_EXCERPT_MAX = 2400
EVIDENCE_TOTAL_CHARS_MAX = 40000
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
        # NX-N0/R3：块级截断如实标记（超长块只取前 1200 字符，消费方不得
        # 把 excerpt 当全文）。
        "truncated": len(text.strip()) > EVIDENCE_EXCERPT_MAX,
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


def _evidence_pg_settings() -> tuple[str, str] | None:
    from nexus.experiment_runs import _pg_settings as runs_pg_settings

    try:
        return runs_pg_settings()
    except Exception:  # noqa: BLE001 - 配置不可读即跳过持久化
        return None


def persist_evidences(
    *, user_id: str, session_id: str, task_id: str = "",
    attachment_id: str = "", source_title: str = "",
    source_version: str = "", evidences: list[dict[str, Any]] | None = None,
) -> int:
    """F7：证据持久化（来源版本＋内容 hash＋locator＋覆盖范围＋权限）。

    best-effort：PG 不可用即跳过（内存登记不受影响），调用方不得因此失败。
    返回实际写入行数。复用既有解析块（excerpt 原样，不重新解析）。
    """
    import hashlib as _hashlib
    import logging as _logging
    import time as _time

    items = list(evidences or [])
    if not items or not (user_id or "").strip():
        return 0
    pg = _evidence_pg_settings()
    if pg is None:
        return 0
    dsn, schema = pg
    rows = []
    now = _time.time()
    for evidence in items:
        if not isinstance(evidence, dict):
            continue
        eid = str(evidence.get("evidence_id") or "")[:64]
        if not eid:
            continue
        excerpt = str(evidence.get("excerpt") or "")
        rows.append((
            eid, (user_id or "").strip()[:64], (session_id or "").strip()[:128],
            (task_id or "").strip()[:64], (attachment_id or "").strip()[:16],
            str(source_title or evidence.get("source_title") or "")[:120],
            str(source_version or "")[:64],
            _hashlib.sha1(excerpt.encode("utf-8")).hexdigest(),
            str(evidence.get("locator") or "")[:120], excerpt,
            str(evidence.get("coverage") or "")[:32],
            bool(evidence.get("truncated", False)), now,
        ))
    if not rows:
        return 0
    try:
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {schema}.nexus_research_evidence "
                    f"(evidence_id, owner, session_id, task_id, attachment_id, "
                    f"source_title, source_version, content_hash, locator, "
                    f"excerpt, coverage, truncated, created_at) "
                    f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    f"ON CONFLICT (evidence_id) DO NOTHING",
                    rows,
                )
                return int(cur.rowcount or 0)
    except Exception as error:  # noqa: BLE001 - 持久化失败不阻断研究
        _logging.getLogger("nexus.paper_evidence").warning(
            "evidence persist failed: %s", error)
        return 0


def resolve_persisted(
    evidence_id: str, *, user_id: str, session_id: str,
) -> dict[str, Any] | None:
    """F7：持久化证据回读（内存登记缺失时的恢复路径；归属一致才返回）。"""
    import logging as _logging

    eid = (evidence_id or "").strip()[:64]
    if not eid:
        return None
    pg = _evidence_pg_settings()
    if pg is None:
        return None
    dsn, schema = pg
    try:
        import psycopg

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT evidence_id, attachment_id, source_title, locator, "
                    f"excerpt, coverage, truncated FROM {schema}.nexus_research_evidence "
                    f"WHERE evidence_id=%s AND owner=%s AND session_id=%s",
                    (eid, (user_id or "").strip(), (session_id or "").strip()),
                )
                found = cur.fetchone()
        if found is None:
            return None
        return {
            "evidence_id": str(found[0] or ""),
            "attachment_id": str(found[1] or ""),
            "source_title": str(found[2] or ""),
            "source_kind": "upload_label",
            "locator": str(found[3] or "") or None,
            "excerpt": str(found[4] or ""),
            "coverage": str(found[5] or ""),
            "truncated": bool(found[6]),
            "is_supplementary": True,
        }
    except Exception as error:  # noqa: BLE001
        _logging.getLogger("nexus.paper_evidence").warning(
            "evidence resolve failed: %s", error)
        return None
