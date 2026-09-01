"""学科语料层 FTS + 向量混合检索（RAG 检索白名单接入，2026-09-01）。

语料层（``knowledge_data/.corpus_cache/corpus_*.jsonl``，3.26GB）由
``knowledge_data/corpus/build_corpus_index.py`` 预构建为 SQLite FTS5 索引；
中文高权威子集（教材 + 中文维基 CS）另由 ``build_corpus_embeddings.py``
用本地 BGE 离线嵌入写入 pgvector 表 ``discipline_corpus_embedding``。
本模块在**运行期只读**消费两路索引并做 RRF 融合：

- FTS 路：CJK 二元组 + ASCII 词分词（索引/查询共用 ``tokenize_for_fts``），
  AND 匹配优先、无命中回退 OR，bm25 排序（标题权重 3:1）；
- 向量路（方案 C 第一步）：查询经本地 BGE 嵌入（复用
  ``app.platform.knowledge.embedding.LocalBgeEmbeddingProvider``，查询侧带
  query instruction），pgvector HNSW 余弦召回；默认关闭，启用需
  ``DISCIPLINE_CORPUS_VECTOR_ENABLED=true`` 且向量表已构建；
- 融合：``_rrf_fuse`` 对两路排名做 Reciprocal Rank Fusion（k=60）；
- fail-closed：索引未配置/文件缺失/向量表缺失/模型加载失败时对应通路
  静默返回空，绝不抛错阻断问答主链路，也不假装命中。
- 结果仅作 ``is_supplementary`` 补充参考（AGENTS.md §4.1.5）：无
  ``evidence_id``，不进课程证据闭包、掌握度或图谱。
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 与 discipline_kb._QUERY_NOISE_WORDS 同源的口语噪声词：剥离后再分词/嵌入，
# 避免"怎么/什么"等引导词参与匹配导致整句无命中或语义漂移。
_QUERY_NOISE_WORDS = (
    "如何", "怎么", "怎样", "什么", "为什么", "请问", "解释", "讲解",
    "讲清楚", "说明", "介绍一下", "介绍", "学生", "学生们", "同学",
    "老师", "给我", "帮我", "理解", "区分",
)

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_+#]+")

# RRF 融合参数：score(d) = Σ_channel 1 / (RRF_K + rank)。
_RRF_K = 60
# FTS 召回深度（融合前的 top-n）。
_FTS_RECALL = 8


class EmbeddingPathUnavailable(RuntimeError):
    pass


_conn_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None

_vector_lock = threading.Lock()
_vector_provider: Any = None
_vector_disabled = False


def tokenize_for_fts(text: str) -> str:
    """索引/查询共用的分词器：CJK 二元组 + ASCII 词，空格连接。

    中文连续段拆成重叠 bigram（"进程调度" → "进程 程调 调度"），
    英文/数字串保持整词（lowercase）。两侧使用同一函数是命中一致性的前提。
    """
    if not text:
        return ""
    lowered = str(text).lower()
    out: list[str] = []
    pos = 0
    for run_match in _CJK_RUN_RE.finditer(lowered):
        out.extend(_ASCII_TOKEN_RE.findall(lowered[pos : run_match.start()]))
        run = run_match.group()
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i : i + 2] for i in range(len(run) - 1))
        pos = run_match.end()
    out.extend(_ASCII_TOKEN_RE.findall(lowered[pos:]))
    return " ".join(out)


def strip_query_noise(query: str) -> str:
    """剥离教学口语化查询中的无信息量引导词（与概念层检索同策略）。"""
    cleaned = str(query or "")
    for word in _QUERY_NOISE_WORDS:
        cleaned = cleaned.replace(word, " ")
    return cleaned.strip()


def _resolve_index_path() -> Path | None:
    """读取配置的索引路径；未配置或文件不存在时返回 None（fail-closed）。"""
    from app.core.config import settings

    raw = str(getattr(settings, "DISCIPLINE_CORPUS_INDEX_PATH", "") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        logger.warning("学科语料索引未找到（DISCIPLINE_CORPUS_INDEX_PATH=%s）", raw)
        return None
    return path


def _get_connection(path: Path) -> sqlite3.Connection:
    """进程内单连接（只读 URI），跨线程由 _conn_lock 串行化。"""
    global _conn, _conn_path
    with _conn_lock:
        if _conn is not None and _conn_path == str(path):
            return _conn
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001 - 只读连接关闭失败无需处理
                pass
        conn = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False
        )
        _conn = conn
        _conn_path = str(path)
        return conn


def corpus_index_available() -> bool:
    """语料层索引是否已配置且存在（用于端点/诊断如实上报接入状态）。"""
    return _resolve_index_path() is not None


def close_corpus_connection() -> None:
    """关闭缓存的只读连接（测试/索引热替换场景显式释放文件句柄）。"""
    global _conn, _conn_path
    with _conn_lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001 - 只读连接关闭失败无需处理
                pass
        _conn, _conn_path = None, None


def _reset_vector_state() -> None:
    """重置向量通路进程内状态（测试场景）。"""
    global _vector_provider, _vector_disabled
    with _vector_lock:
        _vector_provider = None
        _vector_disabled = False


def _get_vector_provider() -> Any | None:
    """懒加载查询侧本地 BGE Provider；任何失败都进程内禁用（fail-closed）。"""
    global _vector_provider, _vector_disabled
    if _vector_disabled:
        return None
    if _vector_provider is not None:
        return _vector_provider
    with _vector_lock:
        if _vector_disabled:
            return None
        if _vector_provider is not None:
            return _vector_provider
        try:
            from app.core.config import settings
            from app.platform.knowledge.embedding import LocalBgeEmbeddingProvider

            raw = (
                str(getattr(settings, "DISCIPLINE_CORPUS_VECTOR_MODEL_PATH", "") or "").strip()
                or str(getattr(settings, "GRAPHRAG_EMBEDDING_LOCAL_PATH", "") or "").strip()
            )
            if not raw:
                raise EmbeddingPathUnavailable("向量检索未配置模型路径")
            path = Path(raw)
            if not path.is_absolute():
                backend_root = Path(__file__).resolve().parents[3]
                candidate = (backend_root / raw).resolve()
                if candidate.is_dir():
                    path = candidate
            _vector_provider = LocalBgeEmbeddingProvider(
                model_path=path,
                model_name=path.name,
                expected_dimension=int(getattr(settings, "GRAPHRAG_EMBEDDING_DIMENSION", 0) or 0),
                batch_size=max(1, int(getattr(settings, "GRAPHRAG_EMBEDDING_BATCH_SIZE", 32) or 32)),
                max_length=max(8, int(getattr(settings, "GRAPHRAG_EMBEDDING_MAX_LENGTH", 512) or 512)),
                # 查询侧带 query instruction（BGE 约定；段落侧构建脚本不加）。
                query_instruction=str(
                    getattr(settings, "GRAPHRAG_EMBEDDING_QUERY_INSTRUCTION", "") or ""
                ),
            )
        except Exception as error:  # noqa: BLE001 - fail-closed：模型不可用即禁用向量路
            logger.warning("学科语料向量检索禁用（%s）", type(error).__name__)
            _vector_disabled = True
            return None
        return _vector_provider


def _quote_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _fts_search(cleaned: str, recall: int) -> list[dict[str, Any]]:
    """FTS 召回：AND 优先、无命中回退 OR，返回带 rowid 的段落行。"""
    tokens = tokenize_for_fts(cleaned).split()
    if not tokens:
        return []
    sql = (
        "SELECT p.rowid AS rowid, p.doc_id, p.chunk_no, p.title_raw, p.book, "
        "p.source, p.license, p.body_raw, "
        "bm25(corpus_fts, 3.0, 1.0) AS rank "
        "FROM corpus_fts JOIN corpus_paragraph AS p ON p.rowid = corpus_fts.rowid "
        "WHERE corpus_fts MATCH ? ORDER BY rank LIMIT ?"
    )
    conn = _get_connection(_resolve_index_path())  # 调用方已确保 path 非 None
    with _conn_lock:
        match_expr = " ".join(_quote_token(t) for t in tokens)  # 隐式 AND
        rows = conn.execute(sql, (match_expr, recall)).fetchall()
        if not rows:
            or_expr = " OR ".join(_quote_token(t) for t in tokens)
            rows = conn.execute(sql, (or_expr, recall)).fetchall()
    keys = ("rowid", "doc_id", "chunk_no", "title_raw", "book", "source", "license", "body_raw")
    return [dict(zip(keys, row)) for row in rows]


def _fetch_paragraphs(rowids: list[int]) -> dict[int, dict[str, Any]]:
    """按 rowid 从 sqlite 索引回取段落原文（向量命中但 FTS 未命中的行）。"""
    if not rowids:
        return {}
    conn = _get_connection(_resolve_index_path())  # 调用方已确保 path 非 None
    placeholders = ",".join("?" for _ in rowids)
    sql = (
        "SELECT rowid, doc_id, chunk_no, title_raw, book, source, license, body_raw "
        f"FROM corpus_paragraph WHERE rowid IN ({placeholders})"
    )
    with _conn_lock:
        rows = conn.execute(sql, rowids).fetchall()
    keys = ("rowid", "doc_id", "chunk_no", "title_raw", "book", "source", "license", "body_raw")
    return {row[0]: dict(zip(keys, row)) for row in rows}


def _vector_search(cleaned: str, recall: int) -> list[tuple[int, float]]:
    """向量召回：查询嵌入 + pgvector HNSW 余弦，返回 (rowid, cosine) 列表。

    未启用/模型不可用/表缺失/任何异常都返回空列表（fail-closed），
    并在进程内禁用后续向量尝试，直到服务重启。
    """
    global _vector_disabled
    from app.core.config import settings

    if not getattr(settings, "DISCIPLINE_CORPUS_VECTOR_ENABLED", False):
        return []
    provider = _get_vector_provider()
    if provider is None:
        return []
    try:
        vector = provider.embed([cleaned])[0]
        literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
        from sqlalchemy import text

        from app.models.database import engine

        sql = (
            "SELECT row_id, 1 - (embedding <=> CAST(:q AS vector)) AS score "
            "FROM discipline_corpus_embedding "
            "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
        )
        with engine.connect() as conn:
            rows = conn.execute(text(sql), {"q": literal, "k": recall}).fetchall()
        return [(int(row[0]), float(row[1])) for row in rows]
    except Exception:  # noqa: BLE001 - fail-closed：向量路失败静默降级 FTS
        logger.warning("学科语料向量检索失败，本进程内降级为纯 FTS", exc_info=True)
        with _vector_lock:
            _vector_disabled = True
        return []


def _rrf_fuse(fts_rowids: list[int], vec_rowids: list[int]) -> list[int]:
    """Reciprocal Rank Fusion（k=60）：两路排名倒数求和后降序。"""
    scores: dict[int, float] = {}
    for channel in (fts_rowids, vec_rowids):
        for rank, rowid in enumerate(channel):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (_RRF_K + rank)
    return [rowid for rowid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def _make_snippet(body: str, query: str, max_chars: int) -> str:
    """从段落原文截取首个命中附近的窗口；无显式命中时取段首。"""
    body = str(body or "")
    if len(body) <= max_chars:
        return body
    lowered = body.lower()
    probe = str(query or "").lower()
    start = 0
    # 优先找查询前缀（最长 12 字符）在段落中的首个命中位置
    for size in range(min(len(probe), 12), 1, -1):
        idx = lowered.find(probe[:size])
        if idx >= 0:
            start = idx
            break
    window_start = max(0, start - max_chars // 3)
    window = body[window_start : window_start + max_chars]
    prefix = "…" if window_start > 0 else ""
    suffix = "…" if window_start + max_chars < len(body) else ""
    return prefix + window + suffix


def search_corpus(
    query: str,
    *,
    top_k: int = 2,
    snippet_chars: int = 260,
) -> list[dict[str, Any]]:
    """语料段落混合检索：FTS + 向量（可选）RRF 融合后取 top-k。

    任何失败（未配置、文件缺失、SQL 错误、向量路异常）都静默降级，
    绝不阻断问答主链路，也不伪造结果。
    """
    cleaned = strip_query_noise(query)
    if not cleaned:
        return []
    try:
        path = _resolve_index_path()
        if path is None:
            return []
        from app.core.config import settings

        limit = max(1, int(getattr(settings, "DISCIPLINE_CORPUS_TOP_K", 2) or top_k))
        vec_recall = max(1, int(getattr(settings, "DISCIPLINE_CORPUS_VECTOR_TOP_K", 8) or 8))

        fts_rows = _fts_search(cleaned, _FTS_RECALL)
        vec_hits = _vector_search(cleaned, vec_recall)
        fts_ids = {row["rowid"] for row in fts_rows}
        if vec_hits:
            vec_ids = {rid for rid, _ in vec_hits}
            fused = _rrf_fuse([row["rowid"] for row in fts_rows], [rid for rid, _ in vec_hits])
            by_id = {row["rowid"]: row for row in fts_rows}
            missing = [rid for rid in fused if rid not in by_id]
            by_id.update(_fetch_paragraphs(missing))
            ordered = [by_id[rid] for rid in fused[:limit] if rid in by_id]
        else:
            # 向量路未启用/降级：与纯 FTS 行为完全一致。
            vec_ids = set()
            ordered = fts_rows[:limit]
    except Exception:  # noqa: BLE001 - fail-closed：检索失败静默降级
        logger.exception("学科语料检索失败（query_length=%d）", len(query or ""))
        return []

    results: list[dict[str, Any]] = []
    for row in ordered:
        matched_by = []
        if row["rowid"] in fts_ids:
            matched_by.append("fts")
        if row["rowid"] in vec_ids:
            matched_by.append("vector")
        results.append({
            "rowid": int(row["rowid"]),
            "doc_id": str(row["doc_id"] or ""),
            "chunk_no": int(row["chunk_no"] or 0),
            "title": str(row["title_raw"] or ""),
            "book": str(row["book"] or ""),
            "source": str(row["source"] or ""),
            "license": str(row["license"] or ""),
            "snippet": _make_snippet(row["body_raw"], cleaned, snippet_chars),
            "matched_by": matched_by,
            "retrieval_source": "discipline_corpus",
            "is_supplementary": True,
        })
    return results


__all__ = [
    "close_corpus_connection",
    "corpus_index_available",
    "search_corpus",
    "strip_query_noise",
    "tokenize_for_fts",
]
