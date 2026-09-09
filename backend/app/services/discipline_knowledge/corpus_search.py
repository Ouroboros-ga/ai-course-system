"""CR3 统一语料检索：同版本 FTS + 向量融合、回源去重与引用。

``CorpusSearchService.search(session, query, *, top_k=6, release_id=None,
filters=None, embed_client=None)`` ——学科页面、TeachingAgent、Nexus 三个
入口共用；单次请求固定 ``release_id``（head 或显式），此次所有召回/
回源/引用沿用该版本，一份回答不混入两个学科版本。

- 词法 / 向量并行召回各初始 30 条，RRF（k=60）合并；按文档限重复
  （每文档最多 2 块）、合并相邻重叠片段，取最多 6 个正文块；
- 展示 ``snippet`` 与模型 ``context_text`` 分开：``context_text`` 可扩展
  前后各 1 邻块（同版本、同文档、不重复），全部 ``context_text`` 共用
  3000 tokens 上下文预算，超预算的块只给 snippet 并标
  ``context_truncated``；
- RRF 是排序，不是可信度概率；无合适证据返回空结果（``match: none``），
  由回答方说明不足，不得编造引用；
- 向量暂不可用 → FTS 命中 + ``VECTOR_UNAVAILABLE``（带 60 秒重试冷却，
  不永久禁用）；两路均失败 → ``unavailable``，与无命中区分；
- 来源撤回实时过滤；``is_supplementary`` 恒 True（补充参考，不进课程
  证据闭包）；``reference_id = {release_id}:{chunk_id}``，100% 属于本次
  release（``get_chunk_reference`` 同一成员表校验）。
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Any, NamedTuple, Optional

from sqlmodel import Session, select

from app.models.discipline_knowledge_model import (
    DisciplineChunk,
    DisciplineDocumentVersion,
)
from app.services.discipline_knowledge.corpus_index import (
    CORPUS_SCOPE,
    CorpusIndexError,
    get_chunk_reference,
    open_fts_readonly,
    read_head,
)

SCHEMA_VERSION = "discipline-corpus/2"

LEXICAL_RECALL = 30
VECTOR_RECALL = 30
RRF_K = 60
DEFAULT_TOP_K = 6
CONTEXT_BUDGET_TOKENS = 3000
MAX_CHUNKS_PER_DOC = 2

VECTOR_COOLDOWN_SECONDS = 60


class _LiveMember(NamedTuple):
    """release 内实时成员（单次 JOIN 的行投影；替代逐成员 ORM 往返）。"""

    chunk_id: str
    embedding_id: str | None
    display_metadata: dict

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_cooldown_lock = threading.Lock()
_vector_cooldown_until: dict[str, float] = {}


def reset_vector_cooldown() -> None:
    """清空向量冷却（测试场景）。"""
    with _cooldown_lock:
        _vector_cooldown_until.clear()


def _estimate_tokens(text: str) -> int:
    text = str(text or "")
    if not text:
        return 0
    return max(1, len(text) // 4 + len(_CJK_RE.findall(text)))


def _rrf_fuse(lexical_ids: list[str], vector_ids: list[str]) -> list[str]:
    scores: dict[str, float] = {}
    for channel in (lexical_ids, vector_ids):
        for rank, chunk_id in enumerate(channel):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return [cid for cid, _ in sorted(scores.items(),
                                     key=lambda kv: (-kv[1], kv[0]))]


def _make_snippet(body: str, query: str, max_chars: int = 260) -> str:
    body = str(body or "")
    if len(body) <= max_chars:
        return body
    lowered = body.lower()
    probe = str(query or "").lower()
    start = 0
    for size in range(min(len(probe), 12), 1, -1):
        idx = lowered.find(probe[:size])
        if idx >= 0:
            start = idx
            break
    window_start = max(0, start - max_chars // 3)
    window = body[window_start:window_start + max_chars]
    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_start + max_chars < len(body) else ""
    return prefix + window + suffix


def _rank_by_cosine(query_vector: list[float], vectors: list[list[float]],
                    keys: list[str], k: int) -> list[tuple[float, str]]:
    """按余弦取 top-k（numpy 矩阵化优先，缺 numpy/维度异常时逐行兜底）。

    - 排序键与旧实现一致：``(-score, key)``（并列时按 chunk_id 稳定）；
    - 向量已由 provider L2 归一，此处防御性再归一（与 ``_cosine`` 同语义）；
    - 查询零向量返回空（不硬凑）；numpy 缺失只降速不降级语义。
    """
    if not vectors:
        return []
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - 部署环境随 torch 装有 numpy
        np = None  # type: ignore[assignment]
    if np is not None:
        try:
            matrix = np.asarray(vectors, dtype=np.float32)
            query = np.asarray(query_vector, dtype=np.float32)
            if matrix.ndim == 2 and query.ndim == 1 \
                    and matrix.shape[1] == query.shape[0]:
                query_norm = float(np.linalg.norm(query))
                if query_norm <= 0.0:
                    return []
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                sims = (matrix / np.maximum(norms, 1e-12)) @ (query / query_norm)
                take = min(k, int(sims.shape[0]))
                if take < int(sims.shape[0]):
                    idx = np.argpartition(-sims, take - 1)[:take]
                else:
                    idx = np.arange(int(sims.shape[0]))
                return sorted(((float(sims[i]), keys[i]) for i in idx),
                              key=lambda kv: (-kv[0], kv[1]))[:k]
        except (TypeError, ValueError):
            pass  # 形状不一致等 → 逐行兜底
    scored = [(_cosine(query_vector, vector), key)
              for vector, key in zip(vectors, keys)]
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    return scored[:k]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class CorpusSearchService:
    """统一检索服务（无状态； Hungry 冷却为进程级）。"""

    def search(
        self,
        session: Session,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        release_id: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
        embed_client: Any = None,
    ) -> dict[str, Any]:
        """混合检索，返回 §5.1 契约字典（全合成示例字段名，真实查询结果）。

        前置条件失败（版本缺失/未 ready）抛 ``CorpusIndexError``；
        运行时通路失败以降级状态返回，不抛错阻断问答。
        """
        from app.models.discipline_corpus_index_model import (
            DisciplineCorpusIndexMember,
            DisciplineCorpusVector,
        )
        from app.platform.knowledge.corpus_embedding import input_hash_for
        from app.platform.knowledge.discipline_corpus import (
            strip_query_noise,
            tokenize_for_fts,
        )
        from app.services.discipline_knowledge.corpus_index import get_release
        from app.services.discipline_knowledge.corpus_text import (
            read_chunk_text,
        )

        cleaned = str(query or "").strip()
        if not cleaned:
            raise CorpusIndexError("SCHEMA_INVALID", "query 为空")
        filters = dict(filters or {})

        if release_id:
            release = get_release(session, release_id)
            # active 由 head 指针表达，行状态恒为 ready；非 ready 显式版本拒绝
            if release["status"] != "ready":
                raise CorpusIndexError(
                    "INDEX_NOT_READY", f"版本 {release_id} 未就绪")
            rid = release_id
        else:
            head = read_head(session)
            if not head["release_id"]:
                raise CorpusIndexError("NOT_READY", "尚无已发布语料版本")
            rid = head["release_id"]
            release = get_release(session, rid)

        counts = release["counts"]
        model_fp = counts.get("model_fingerprint") or ""
        # -- 版本内成员表 + 撤回实时过滤（单次 JOIN） --
        # 旧实现逐成员查 chunk/version：3899 成员 ≈ 7800 次往返/查询（实测
        # 纯词法 7.3s 的主因）。改为一条 JOIN，语义不变：chunk 缺失跳过、
        # version 缺失或 withdrawn 计入 withdrawn。
        member_rows = session.exec(
            select(DisciplineCorpusIndexMember.chunk_id,
                   DisciplineCorpusIndexMember.embedding_id,
                   DisciplineCorpusIndexMember.display_metadata,
                   DisciplineDocumentVersion.status)
            .join(DisciplineChunk,
                  DisciplineChunk.chunk_id == DisciplineCorpusIndexMember.chunk_id)
            .join(DisciplineDocumentVersion,
                  DisciplineDocumentVersion.version_id == DisciplineChunk.version_id,
                  isouter=True)
            .where(DisciplineCorpusIndexMember.release_id == rid)
        ).all()
        live: dict[str, _LiveMember] = {}
        withdrawn = 0
        for chunk_id, embedding_id, display_metadata, version_status in member_rows:
            if version_status is None or version_status == "withdrawn":
                withdrawn += 1
                continue
            live[chunk_id] = _LiveMember(chunk_id, embedding_id,
                                         dict(display_metadata or {}))
        eligible = len(live)
        embedded_ids = {cid for cid, m in live.items() if m.embedding_id}

        degraded: list[str] = []
        lexical_ids: list[str] = []
        lexical_rows: dict[str, dict] = {}
        lexical_failed = False
        try:
            lexical_ids, lexical_rows = self._lexical_recall(
                session, rid, cleaned, strip_query_noise, tokenize_for_fts)
        except CorpusIndexError as exc:
            lexical_failed = True
            degraded.append(f"FTS_UNAVAILABLE:{exc.error_code}")

        vector_ids: list[str] = []
        vector_ok = False
        vector_failed = False
        if embedded_ids and embed_client is not None and self._vector_allowed(model_fp):
            try:
                vector_ids = self._vector_recall(
                    session, cleaned, live, model_fp, embed_client,
                    input_hash_for)
                vector_ok = True
            except Exception:  # noqa: BLE001 - 向量路失败只降级
                vector_failed = True
                degraded.append("VECTOR_UNAVAILABLE")
                with _cooldown_lock:
                    _vector_cooldown_until[model_fp] = (
                        time.monotonic() + VECTOR_COOLDOWN_SECONDS)
        elif embedded_ids and (embed_client is None
                               or not self._vector_allowed(model_fp)):
            vector_failed = True
            degraded.append("VECTOR_UNAVAILABLE")
        mode = "hybrid" if vector_ok else "lexical"

        # 仅两路都失败才算 unavailable：某路正常但零命中是 no-match，
        # 不得伪装成故障（与"与无命中区分"的契约一致）。
        if lexical_failed and (vector_failed or not embedded_ids):
            return {"schema_version": SCHEMA_VERSION, "release_id": rid,
                    "status": "unavailable", "mode": mode,
                    "degraded_reasons": degraded,
                    "coverage": self._coverage(
                        release, eligible, len(embedded_ids), withdrawn),
                    "results": [], "match": "none"}

        fused = _rrf_fuse(lexical_ids, vector_ids)
        fused = [cid for cid in fused if cid in live]
        fused = self._apply_filters(session, fused, live, filters)
        fused = self._dedup_per_doc(session, fused, live)
        fused = self._merge_overlaps(session, fused, live)

        results = self._assemble(session, rid, cleaned, fused[:max(1, top_k)],
                                 set(lexical_ids), set(vector_ids), live,
                                 read_chunk_text)
        return {"schema_version": SCHEMA_VERSION, "release_id": rid,
                "status": "degraded" if degraded else "ok", "mode": mode,
                "degraded_reasons": degraded,
                "coverage": self._coverage(
                    release, eligible, len(embedded_ids), withdrawn),
                "results": results,
                "match": "hit" if results else "none"}

    # -- 内部步骤 ------------------------------------------------------

    @staticmethod
    def _coverage(release: dict, eligible: int, embedded: int,
                  withdrawn: int) -> dict[str, Any]:
        return {"eligible_chunks": eligible, "embedded_chunks": embedded,
                "withdrawn_filtered": withdrawn,
                "scope": release.get("scope") or CORPUS_SCOPE}

    @staticmethod
    def _vector_allowed(model_fp: str) -> bool:
        with _cooldown_lock:
            return time.monotonic() >= _vector_cooldown_until.get(model_fp, 0.0)

    @staticmethod
    def _lexical_recall(session: Session, release_id: str, query: str,
                        strip_noise, tokenize) -> tuple[list[str], dict]:
        from app.services.discipline_knowledge.corpus_index import (
            fts_object_key_for,
            open_fts_readonly,
        )

        cleaned = strip_noise(query)
        tokens = tokenize(cleaned).split() if cleaned else []
        terms = tokens or tokenize(query).split()
        if not terms:
            return [], {}
        conn = open_fts_readonly(fts_object_key_for(release_id),
                                 expected_release_id=release_id)

        def _quote(token: str) -> str:
            return '"' + token.replace('"', '""') + '"'

        sql = (
            "SELECT p.chunk_id, p.title, p.body, p.source, "
            "bm25(corpus_fts, 3.0, 1.0) AS rank "
            "FROM corpus_fts JOIN paragraph AS p "
            "ON p.rowid = corpus_fts.rowid "
            "WHERE corpus_fts MATCH ? ORDER BY rank LIMIT ?"
        )
        with _lock_for(conn):
            rows = conn.execute(
                sql, (" ".join(_quote(t) for t in terms),
                      LEXICAL_RECALL)).fetchall()
            if not rows:
                rows = conn.execute(
                    sql, (" OR ".join(_quote(t) for t in terms),
                          LEXICAL_RECALL)).fetchall()
        ids: list[str] = []
        by_id: dict[str, dict] = {}
        for chunk_id, title, body, source, _rank in rows:
            if chunk_id not in by_id:
                ids.append(chunk_id)
                by_id[chunk_id] = {"title": title, "body": body,
                                   "source": source}
        return ids, by_id

    @staticmethod
    def _vector_recall(session: Session, query: str, live: dict,
                       model_fp: str, embed_client: Any,
                       input_hash_for) -> list[str]:
        from app.models.discipline_corpus_index_model import (
            DisciplineCorpusVector,
        )

        result = embed_client.embed([query], "query")
        if str(result.get("model_fingerprint") or "") != model_fp:
            raise CorpusIndexError(
                "MODEL_MISMATCH", "查询向量指纹与版本指纹不一致")
        vectors = result.get("vectors") or []
        if len(vectors) != 1:
            raise CorpusIndexError("COUNT_MISMATCH", "查询向量数量异常")
        query_vector = list(vectors[0])
        eids = [m.embedding_id for m in live.values() if m.embedding_id]
        # 只取两列（不 hydrate ORM 行）；矩阵化打分在 _rank_by_cosine。
        rows = session.exec(
            select(DisciplineCorpusVector.embedding_id,
                   DisciplineCorpusVector.embedding).where(
                DisciplineCorpusVector.embedding_id.in_(eids),
                DisciplineCorpusVector.model_fingerprint == model_fp,
            )
        ).all() if eids else []
        by_embedding = {eid: vec for eid, vec in rows}
        chunk_ids: list[str] = []
        matrix_rows: list[list[float]] = []
        for chunk_id, member in live.items():
            if not member.embedding_id:
                continue
            vector = by_embedding.get(member.embedding_id)
            if vector is None:
                continue
            chunk_ids.append(chunk_id)
            matrix_rows.append(list(vector or []))
        scored = _rank_by_cosine(query_vector, matrix_rows, chunk_ids,
                                 VECTOR_RECALL)
        # 零相似全部排除（无合适证据返回空，不硬凑 top-k）
        return [cid for score, cid in scored if score > 0.0]

    @staticmethod
    def _apply_filters(session: Session, fused: list[str], live: dict,
                       filters: dict) -> list[str]:
        kinds = filters.get("source_kind")
        if isinstance(kinds, str):
            kinds = [kinds]
        doc_ids = filters.get("doc_id")
        if isinstance(doc_ids, str):
            doc_ids = [doc_ids]
        want_vector = filters.get("has_vector")
        if not kinds and not doc_ids and want_vector is None:
            return fused
        kept = []
        for chunk_id in fused:
            meta = dict(live[chunk_id].display_metadata or {})
            if kinds and meta.get("source_kind") not in kinds:
                continue
            if doc_ids and meta.get("external_id") not in doc_ids:
                continue
            if want_vector is True and not live[chunk_id].embedding_id:
                continue
            if want_vector is False and live[chunk_id].embedding_id:
                continue
            kept.append(chunk_id)
        return kept

    @staticmethod
    def _dedup_per_doc(session: Session, fused: list[str],
                       live: dict) -> list[str]:
        counts: dict[str, int] = {}
        kept = []
        for chunk_id in fused:
            doc = str(dict(live[chunk_id].display_metadata or {}).get(
                "version_id") or "")
            if counts.get(doc, 0) >= MAX_CHUNKS_PER_DOC:
                continue
            counts[doc] = counts.get(doc, 0) + 1
            kept.append(chunk_id)
        return kept

    @staticmethod
    def _merge_overlaps(session: Session, fused: list[str],
                        live: dict) -> list[str]:
        """合并同文档相邻/重叠块（chunk_no 差 ≤1），保留最好排名。"""
        order = {cid: rank for rank, cid in enumerate(fused)}
        groups: dict[str, list[str]] = {}
        for chunk_id in fused:
            meta = dict(live[chunk_id].display_metadata or {})
            groups.setdefault(str(meta.get("version_id") or ""), []).append(
                chunk_id)
        merged: list[tuple[int, str]] = []
        for chunks in groups.values():
            ordered = sorted(chunks, key=lambda c: int(
                dict(live[c].display_metadata or {}).get("chunk_no") or 0))
            current = [ordered[0]]
            for nxt in ordered[1:]:
                prev_no = int(dict(live[current[-1]].display_metadata or {}).get(
                    "chunk_no") or 0)
                nxt_no = int(dict(live[nxt].display_metadata or {}).get(
                    "chunk_no") or 0)
                if nxt_no - prev_no <= 1:
                    current.append(nxt)
                else:
                    merged.append((min(order[c] for c in current), current[0]))
                    current = [nxt]
            merged.append((min(order[c] for c in current), current[0]))
        merged.sort()
        return [cid for _, cid in merged]

    @staticmethod
    def _assemble(session: Session, release_id: str, query: str,
                  chunk_ids: list[str], lexical_set: set[str],
                  vector_set: set[str], live: dict,
                  read_chunk_text) -> list[dict[str, Any]]:
        # 版本 → chunk_no → chunk_id 索引：每查询构建一次，替代每个结果重扫
        # 全部成员（旧实现 6 结果 × 3899 成员 ≈ 2.3 万次 JSON 解析/查询）。
        by_version: dict[str, dict[int, str]] = {}
        meta_by_cid: dict[str, tuple[str, int]] = {}
        for cid, member in live.items():
            meta = dict(member.display_metadata or {})
            version_id = str(meta.get("version_id") or "")
            chunk_no = int(meta.get("chunk_no") or 0)
            meta_by_cid[cid] = (version_id, chunk_no)
            by_version.setdefault(version_id, {})[chunk_no] = cid
        results = []
        spent = 0
        for chunk_id in chunk_ids:
            try:
                ref = get_chunk_reference(session, chunk_id, release_id)
            except CorpusIndexError:
                continue  # 成员与引用双检，异常块跳过不中断
            matched = []
            if chunk_id in lexical_set:
                matched.append("fts")
            if chunk_id in vector_set:
                matched.append("vector")
            snippet = _make_snippet(ref["text"], query)
            version_id, chunk_no = meta_by_cid.get(chunk_id, ("", 0))
            context, truncated, cost = CorpusSearchService._context(
                session, by_version, version_id, chunk_no, chunk_id,
                ref["text"], CONTEXT_BUDGET_TOKENS - spent, read_chunk_text)
            spent += cost
            results.append({
                "reference_id": ref["reference_id"],
                "chunk_id": chunk_id,
                "doc_id": ref["doc_id"],
                "chunk_no": ref["chunk_no"],
                "title": ref["title"],
                "source_kind": ref["source_kind"],
                "source_url": ref["source_url"],
                "license": ref["license"],
                "section_path": ref["section_path"],
                "snippet": snippet,
                "context_text": context,
                "context_truncated": truncated,
                "matched_by": matched or ["fts"],
                "is_supplementary": True,
            })
        return results

    @staticmethod
    def _context(session: Session, by_version: dict[str, dict[int, str]],
                 version_id: str, chunk_no: int, chunk_id: str, text: str,
                 budget: int, read_chunk_text) -> tuple[str, bool, int]:
        """前后各 1 邻块（同版本、同文档、成员内、不重复），共用预算。"""
        by_no = by_version.get(version_id) or {}
        parts = [text]
        for neighbor in (chunk_no - 1, chunk_no + 1):
            nid = by_no.get(neighbor)
            if nid is None or nid == chunk_id:
                continue
            try:
                parts.append(read_chunk_text(session, nid))
            except CorpusIndexError:
                continue
            if neighbor == chunk_no - 1:
                parts = [parts.pop()] + parts
        full = "\n".join(parts)
        cost = _estimate_tokens(full)
        if cost <= max(0, budget):
            return full, False, cost
        snippet_cost = _estimate_tokens(text)
        return text, True, snippet_cost


_fts_conn_locks: dict[int, threading.Lock] = {}
_fts_conn_locks_guard = threading.Lock()


def _lock_for(conn) -> threading.Lock:
    key = id(conn)
    with _fts_conn_locks_guard:
        lock = _fts_conn_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _fts_conn_locks[key] = lock
        return lock
