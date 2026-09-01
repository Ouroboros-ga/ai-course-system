"""学科语料层 FTS 检索（RAG 检索白名单接入，2026-09-01）。

语料层（``knowledge_data/.corpus_cache/corpus_*.jsonl``，3.26GB）由
``knowledge_data/corpus/build_corpus_index.py`` 预构建为 SQLite FTS5 索引；
本模块在**运行期只读**消费该索引：

- 分词：CJK 连续段 → 重叠二元组（bigram），ASCII 词保持原样；
  索引侧与查询侧共用 ``tokenize_for_fts``，保证命中口径一致。
- fail-closed：索引路径未配置（默认空）或文件缺失/损坏时检索返回空列表，
  绝不抛错阻断问答主链路，也不假装命中。
- 结果仅作 ``is_supplementary`` 补充参考（AGENTS.md §4.1.5）：无
  ``evidence_id``，不进课程证据闭包、掌握度或图谱。

诚实边界：本模块是检索白名单的语料段落级入口；启用需要
``DISCIPLINE_CORPUS_INDEX_PATH`` 指向已构建的索引文件。
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 与 discipline_kb._QUERY_NOISE_WORDS 同源的口语噪声词：剥离后再分词，
# 避免"怎么/什么"等引导词的二元组参与 AND 匹配导致整句无命中。
_QUERY_NOISE_WORDS = (
    "如何", "怎么", "怎样", "什么", "为什么", "请问", "解释", "讲解",
    "讲清楚", "说明", "介绍一下", "介绍", "学生", "学生们", "同学",
    "老师", "给我", "帮我", "理解", "区分",
)

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_+#]+")

_conn_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None


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


def _quote_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


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
    """语料段落检索：AND 匹配优先，无命中时回退 OR，bm25 排序。

    任何失败（未配置、文件缺失、SQL 错误）都返回空列表——补充参考检索
    失败不得阻断问答主链路，也不得伪造结果。
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
        tokens = tokenize_for_fts(cleaned).split()
        if not tokens:
            return []
        match_expr = " ".join(_quote_token(t) for t in tokens)  # 隐式 AND
        sql = (
            "SELECT p.doc_id, p.chunk_no, p.title_raw, p.book, p.source, p.license, p.body_raw, "
            "bm25(corpus_fts, 3.0, 1.0) AS rank "
            "FROM corpus_fts JOIN corpus_paragraph AS p ON p.rowid = corpus_fts.rowid "
            "WHERE corpus_fts MATCH ? ORDER BY rank LIMIT ?"
        )
        conn = _get_connection(path)
        with _conn_lock:
            rows = conn.execute(sql, (match_expr, limit)).fetchall()
            if not rows:
                or_expr = " OR ".join(_quote_token(t) for t in tokens)
                rows = conn.execute(sql, (or_expr, limit)).fetchall()
    except Exception:  # noqa: BLE001 - fail-closed：检索失败静默降级
        logger.exception("学科语料检索失败（query_length=%d）", len(query or ""))
        return []

    results: list[dict[str, Any]] = []
    for doc_id, chunk_no, title_raw, book, source, license_, body_raw, _rank in rows:
        results.append({
            "doc_id": str(doc_id or ""),
            "chunk_no": int(chunk_no or 0),
            "title": str(title_raw or ""),
            "book": str(book or ""),
            "source": str(source or ""),
            "license": str(license_ or ""),
            "snippet": _make_snippet(body_raw, cleaned, snippet_chars),
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
