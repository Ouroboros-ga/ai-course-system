"""离线构建学科语料向量嵌入（方案 C 第一步，2026-09-01）。

从已构建的 FTS 索引（``corpus_index.sqlite3``）读取**中文高权威子集**
（默认 zhwiki-/ostep-/sicp- 前缀段落），用本地 BGE 模型
（复用 ``app.platform.knowledge.embedding.LocalBgeEmbeddingProvider``，
段落侧不加 query instruction——BGE 约定指令只用于查询侧）离线嵌入，
写入 PostgreSQL pgvector 表 ``discipline_corpus_embedding``：

- ``row_id`` 对齐 sqlite ``corpus_paragraph.rowid``（查询侧按 rowid 关联回原文）；
- ``model`` 记录嵌入模型标识，供陈旧性审计；
- 构建结束建 HNSW 余弦索引并 ANALYZE。

该表是**可重建的派生数据**（同 FTS 索引定位，不属于 alembic 业务 schema）；
每次运行先清空整表再写入（单模型全量重建语义）。

用法（服务器端，backend 工作目录）::

    source /opt/smartcarb/shared/env/backend.env
    source /opt/smartcarb/shared/env/database.env
    nice -n 19 python knowledge_data/corpus/build_corpus_embeddings.py

可选参数：``--index``（sqlite 索引路径）、``--db-url``（默认取
AI_COURSE_DATABASE_URL）、``--model-path``（默认取 GRAPHRAG_EMBEDDING_LOCAL_PATH）、
``--doc-prefixes``、``--batch-size``、``--limit``（小样本验证）。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_INDEX = REPO_ROOT / ".corpus_cache" / "corpus_index.sqlite3"
DEFAULT_PREFIXES = ("zhwiki-", "ostep-", "sicp-")
PROGRESS_EVERY = 2000  # 段落

_EMBEDDING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS discipline_corpus_embedding (
    row_id BIGINT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding vector({dimension}) NOT NULL
)
"""

_INSERT_SQL = (
    "INSERT INTO discipline_corpus_embedding"
    "(row_id, doc_id, model, embedding) VALUES "
    "(:row_id, :doc_id, :model, CAST(:embedding AS vector))"
)


def _load_env_file(path: Path) -> None:
    """读取部署 env 文件中的简单 KEY=VALUE 行（不覆盖已设变量）。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _resolve_model_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    raw = os.environ.get("GRAPHRAG_EMBEDDING_LOCAL_PATH", "").strip()
    if not raw:
        raise SystemExit("未指定 --model-path，且 GRAPHRAG_EMBEDDING_LOCAL_PATH 未配置")
    path = Path(raw)
    if not path.is_absolute():
        # 部署配置使用 ./models/... 相对 backend 工作目录
        candidate = (REPO_ROOT / "backend" / raw).resolve()
        if candidate.is_dir():
            return candidate
    return path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="构建学科语料向量嵌入（pgvector）")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--db-url", default=None, help="默认取 AI_COURSE_DATABASE_URL")
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--doc-prefixes", default=",".join(DEFAULT_PREFIXES))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=None, help="只嵌入前 N 段（小样本验证）")
    parser.add_argument("--no-hnsw", action="store_true", help="跳过 HNSW 索引构建（调试用）")
    args = parser.parse_args()

    db_url = args.db_url or os.environ.get("AI_COURSE_DATABASE_URL", "").strip()
    if not db_url or not db_url.startswith("postgresql"):
        raise SystemExit("需要 PostgreSQL 的 --db-url 或 AI_COURSE_DATABASE_URL")
    if not args.index.is_file():
        raise SystemExit(f"FTS 索引不存在: {args.index}")

    # 手动运行时兜底读取 backend/.env（不覆盖已导出的部署变量）。
    _load_env_file(REPO_ROOT / "backend" / ".env")

    from sqlalchemy import create_engine, text

    from app.platform.knowledge.embedding import LocalBgeEmbeddingProvider

    model_path = _resolve_model_path(args.model_path)
    # 段落嵌入不加 query instruction（BGE 约定：指令仅用于查询侧）。
    provider = LocalBgeEmbeddingProvider(
        model_path=model_path,
        model_name=model_path.name,
        expected_dimension=int(os.environ.get("GRAPHRAG_EMBEDDING_DIMENSION", "0") or 0),
        batch_size=max(1, args.batch_size),
        max_length=max(8, int(os.environ.get("GRAPHRAG_EMBEDDING_MAX_LENGTH", "512") or 512)),
        query_instruction="",
    )
    print(f"[model] {model_path} (dim={provider.expected_dimension or 'auto'})", file=sys.stderr)

    prefixes = tuple(p.strip() for p in args.doc_prefixes.split(",") if p.strip())
    like_clause = " OR ".join("doc_id LIKE ?" for _ in prefixes)
    fetch_sql = (
        "SELECT rowid, doc_id, body_raw FROM corpus_paragraph "
        f"WHERE {like_clause} ORDER BY rowid"
    )
    # LIKE 模式需要显式 % 通配符（裸前缀是精确匹配，恒为 0 行）。
    patterns = tuple(f"{p}%" for p in prefixes)

    pg = create_engine(db_url, pool_pre_ping=True)
    started = time.monotonic()
    state = {"done": 0, "table_ready": False}

    def flush(batch: list[tuple]) -> None:
        if not batch:
            return
        vectors = provider.embed([item[2] for item in batch])
        if len(vectors) != len(batch):
            raise SystemExit("嵌入数量与输入不一致，中止")
        if not state["table_ready"]:
            dimension = len(vectors[0])
            with pg.begin() as conn:
                conn.execute(text(_EMBEDDING_TABLE_SQL.format(dimension=dimension)))
                conn.execute(text("DELETE FROM discipline_corpus_embedding"))
            print(f"[table] discipline_corpus_embedding 已重建（dim={dimension}）", file=sys.stderr)
            state["table_ready"] = True
        with pg.begin() as conn:
            conn.execute(
                text(_INSERT_SQL),
                [
                    {
                        "row_id": item[0],
                        "doc_id": item[1],
                        "model": model_path.name,
                        "embedding": "[" + ",".join(f"{x:.6f}" for x in vec) + "]",
                    }
                    for item, vec in zip(batch, vectors)
                ],
            )
        state["done"] += len(batch)
        if state["done"] % PROGRESS_EVERY < len(batch):
            print(f"[embed] {state['done']} 段落 / {time.monotonic() - started:.0f}s", file=sys.stderr)

    with sqlite3.connect(f"file:{args.index.as_posix()}?mode=ro", uri=True) as src:
        cur = src.execute(fetch_sql, patterns)
        batch: list[tuple] = []
        for row in cur:
            if args.limit is not None and state["done"] + len(batch) >= args.limit:
                break
            batch.append(row)
            if len(batch) >= provider.batch_size:
                flush(batch)
                batch = []
        flush(batch)

    if not args.no_hnsw and state["done"]:
        with pg.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_discipline_corpus_embedding_hnsw "
                    "ON discipline_corpus_embedding USING hnsw (embedding vector_cosine_ops)"
                )
            )
            conn.execute(text("ANALYZE discipline_corpus_embedding"))
        print("[hnsw] 余弦索引构建完成", file=sys.stderr)

    if state["table_ready"]:
        with pg.connect() as conn:
            total, models = conn.execute(
                text("SELECT COUNT(*), COUNT(DISTINCT model) FROM discipline_corpus_embedding")
            ).fetchone()
    else:
        total, models = 0, 0
    print(
        f"[done] 本次嵌入 {state['done']} 段落 / 表内共 {total} 行（{models} 个模型）"
        f" / {time.monotonic() - started:.0f}s",
        file=sys.stderr,
    )
    pg.dispose()


if __name__ == "__main__":
    main()
