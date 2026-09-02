#!/usr/bin/env python3
"""从 Common Pile arXiv 论文集（CC 授权子集）过滤出计算机学科语料。

输入：
- .corpus_cache/hf_arxiv_meta/train-*.parquet
  （librarian-bots/arxiv-metadata-snapshot，含 id/categories/title）
- .corpus_cache/hf_arxiv/XXXXX_arxiv-papers.jsonl.gz
  （common-pile/arxiv_papers，CC 授权 arXiv 论文全文，markdown 文本）

流程：
1. 读元数据快照，构建 categories 含 cs.* 的论文 ID → (title, categories) 映射
2. 流式读论文分片，按 ID 过滤
3. 输出 JSONL：{"id":"arxiv-XXXX","title":...,"source":"arxiv.org",
   "license":<论文自带授权>,"text":...}

用法（backend/.venv python，需 pyarrow）：
    python extract_arxiv_cs.py [--cache-dir ../.corpus_cache] [--out xxx.jsonl]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path


def load_cs_ids(meta_dir: Path) -> dict[str, tuple[str, str]]:
    """返回 {arxiv_id: (title, 首个 cs 类别)}。"""
    import pyarrow.parquet as pq

    cs_map: dict[str, tuple[str, str]] = {}
    for path in sorted(meta_dir.glob("train-*.parquet")):
        table = pq.read_table(path, columns=["id", "title", "categories"])
        for aid, title, cats in zip(
            table.column("id").to_pylist(),
            table.column("title").to_pylist(),
            table.column("categories").to_pylist(),
        ):
            if not aid or not cats:
                continue
            # categories 是空格分隔的字符串，如 "math.NA cs.NA"
            cs_cats = [c for c in str(cats).split() if c.startswith("cs.")]
            if not cs_cats:
                continue
            cs_map[str(aid)] = (
                (title or "").strip(),
                cs_cats[0],
            )
        print(f"  {path.name}: 累计 cs 论文 {len(cs_map)}", file=sys.stderr)
    return cs_map


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=str(
        Path(__file__).resolve().parents[2] / ".corpus_cache"))
    ap.add_argument("--out", default="")
    ap.add_argument("--shards", default="", help="逗号分隔的分片编号，默认全部")
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    out_path = Path(args.out) if args.out else cache / "corpus_arxiv_cs.jsonl"

    cs_map = load_cs_ids(cache / "hf_arxiv_meta")
    print(f"[meta] cs.* 论文 {len(cs_map)} 篇", file=sys.stderr)

    if args.shards:
        keep = {f"{int(s):05d}" for s in args.shards.split(",")}
        paths = [
            p for p in sorted(cache.glob("hf_arxiv/*_arxiv-papers.jsonl.gz"))
            if p.name[:5] in keep
        ]
    else:
        paths = sorted(cache.glob("hf_arxiv/*_arxiv-papers.jsonl.gz"))

    written = 0
    chars = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for path in paths:
            hit = 0
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    aid = str(doc.get("id", ""))
                    title, cat = cs_map.get(aid, ("", ""))
                    if not cat:
                        continue
                    text = (doc.get("text") or "").strip()
                    if len(text) < 500:
                        continue
                    meta = doc.get("metadata") or {}
                    out.write(json.dumps(
                        {
                            "id": f"arxiv-{aid}",
                            "title": title,
                            "category": cat,
                            "date": (doc.get("created") or "")[:10],
                            "source": "arxiv.org",
                            "license": meta.get("license", ""),
                            "text": text,
                        },
                        ensure_ascii=False,
                    ) + "\n")
                    written += 1
                    hit += 1
                    chars += len(text)
            print(f"  {path.name}: 命中 {hit}", file=sys.stderr)

    print(json.dumps(
        {"written": written, "cs_meta": len(cs_map), "chars": chars},
        ensure_ascii=False))
    print(f"输出: {out_path}")


if __name__ == "__main__":
    main()
