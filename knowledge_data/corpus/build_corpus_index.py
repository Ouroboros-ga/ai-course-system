"""构建学科语料层 FTS5 索引（RAG 检索白名单接入，2026-09-01）。

把 ``.corpus_cache/`` 下的 ``corpus_*.jsonl``（3.26GB / 184,435 篇）切块
（chunk）后写入 SQLite FTS5 索引，供后端 ``app.platform.knowledge.discipline_corpus``
只读检索：

- 分词器复用后端 ``tokenize_for_fts``（CJK 二元组 + ASCII 词），索引/查询
  两侧同源，保证命中口径一致；
- ``corpus_paragraph`` 表存段落原文与元数据（doc_id/chunk_no/title/book/
  source/license）；contentless FTS5 表 ``corpus_fts`` 只存倒排索引
  （``title``/``body`` 为分词后文本，bm25 权重 3:1），查询按 rowid 关联；
- 运行期只读（``mode=ro`` URI），构建是一次性离线操作。

用法::

    python build_corpus_index.py                       # 全量构建到默认输出
    python build_corpus_index.py --limit 200           # 小样本验证大小/质量
    python build_corpus_index.py --files corpus_textbooks.jsonl,corpus_zhwiki_cs.jsonl

默认语料目录 ``<repo>/.corpus_cache``，默认输出
``<repo>/.corpus_cache/corpus_index.sqlite3``。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.platform.knowledge.discipline_corpus import tokenize_for_fts  # noqa: E402

DEFAULT_CORPUS_DIR = REPO_ROOT / ".corpus_cache"
DEFAULT_OUTPUT = DEFAULT_CORPUS_DIR / "corpus_index.sqlite3"

DEFAULT_FILES = (
    "corpus_textbooks.jsonl",
    "corpus_zhwiki_cs.jsonl",
    "corpus_enwiki_cs.jsonl",
    "corpus_rfc.jsonl",
    "corpus_arxiv_cs.jsonl",
)

CHUNK_TARGET_CHARS = 1000
CHUNK_MAX_CHARS = 1600
CHUNK_MIN_CHARS = 40
CHUNK_FLUSH_MIN = 200  # 空行触发切段的最小缓冲长度，避免 RFC/TeX 产生大量碎块
BATCH_ROWS = 5000


def iter_chunks(text: str, target: int = CHUNK_TARGET_CHARS, max_chars: int = CHUNK_MAX_CHARS):
    """按换行切段并合并到 target 附近；超长段硬切到 max_chars。"""
    buf: list[str] = []
    buf_len = 0
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if buf_len >= CHUNK_FLUSH_MIN:  # 空行视为段落边界，短缓冲继续攒
                yield "\n".join(buf)
                buf, buf_len = [], 0
            continue
        while len(line) > max_chars:  # 超长行（RFC 表格/TeX 长行）硬切
            if buf_len >= CHUNK_FLUSH_MIN:
                yield "\n".join(buf)
                buf, buf_len = [], 0
            yield line[:max_chars]
            line = line[max_chars:]
        if buf_len + len(line) + 1 > max_chars:
            yield "\n".join(buf)
            buf, buf_len = [], 0
        buf.append(line)
        buf_len += len(line) + 1
        if buf_len >= target:
            yield "\n".join(buf)
            buf, buf_len = [], 0
    if buf:
        yield "\n".join(buf)


def build_index(
    corpus_dir: Path,
    output: Path,
    files: list[str],
    limit: int | None,
    progress_every: int = 2000,
) -> None:
    if output.exists():
        output.unlink()
    conn = sqlite3.connect(output)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-262144")  # 256MB page cache
    conn.execute(
        """
        CREATE TABLE corpus_paragraph(
            rowid INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_no INTEGER NOT NULL,
            title_raw TEXT NOT NULL,
            body_raw TEXT NOT NULL,
            book TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            license TEXT NOT NULL DEFAULT ''
        )
        """
    )
    # contentless FTS5：只存倒排索引（title/body 为分词后文本），
    # 原文由 corpus_paragraph 承载，查询按 rowid 关联。
    conn.execute(
        """
        CREATE VIRTUAL TABLE corpus_fts USING fts5(
            title, body, tokenize='unicode61', content=''
        )
        """
    )

    total_docs = 0
    total_chunks = 0
    started = time.monotonic()
    for name in files:
        path = corpus_dir / name
        if not path.is_file():
            print(f"[skip] 缺少语料文件: {path}", file=sys.stderr)
            continue
        docs = chunks = 0
        para_batch: list[tuple] = []
        fts_batch: list[tuple] = []

        def flush() -> None:
            nonlocal para_batch, fts_batch
            if para_batch:
                conn.executemany(
                    "INSERT INTO corpus_paragraph"
                    "(rowid, doc_id, chunk_no, title_raw, body_raw, book, source, license) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    para_batch,
                )
                conn.executemany(
                    "INSERT INTO corpus_fts(rowid, title, body) VALUES (?, ?, ?)",
                    fts_batch,
                )
                para_batch, fts_batch = [], []

        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh):
                if limit is not None and docs >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = str(doc.get("text") or "")
                if len(text) < CHUNK_MIN_CHARS:
                    continue
                doc_id = str(doc.get("id") or f"{name}:{line_no}")
                title = str(doc.get("title") or doc_id)
                book = str(doc.get("book") or "")
                source = str(doc.get("source") or "")
                license_ = str(doc.get("license") or "")
                title_tok = tokenize_for_fts(title)
                for chunk_no, chunk in enumerate(iter_chunks(text)):
                    if len(chunk) < CHUNK_MIN_CHARS:
                        continue
                    rowid = total_chunks + chunks + 1
                    para_batch.append((
                        rowid, doc_id, chunk_no, title, chunk, book, source, license_,
                    ))
                    fts_batch.append((rowid, title_tok, tokenize_for_fts(chunk)))
                    chunks += 1
                    if len(para_batch) >= BATCH_ROWS:
                        flush()
                docs += 1
                if docs % progress_every == 0:
                    flush()
                    print(f"[{name}] {docs} docs / {chunks} chunks / {time.monotonic()-started:.0f}s", file=sys.stderr)
        flush()
        total_docs += docs
        total_chunks += chunks
        print(f"[done] {name}: {docs} docs -> {chunks} chunks", file=sys.stderr)

    conn.execute("INSERT INTO corpus_fts(corpus_fts) VALUES('optimize')")
    conn.commit()
    db_bytes = output.stat().st_size
    conn.close()
    print(
        f"[index] {total_docs} docs / {total_chunks} chunks / "
        f"{db_bytes / 1_000_000_000:.2f} GB / {time.monotonic()-started:.0f}s -> {output}",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="构建学科语料层 FTS5 索引")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--files", type=str, default=",".join(DEFAULT_FILES))
    parser.add_argument("--limit", type=int, default=None, help="每文件只取前 N 篇（小样本验证）")
    args = parser.parse_args()
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    build_index(args.corpus_dir, args.output, files, args.limit)


if __name__ == "__main__":
    main()
