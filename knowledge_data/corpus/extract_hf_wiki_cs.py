#!/usr/bin/env python3
"""从 HF wikimedia/wikipedia parquet 分片按 PetScan ID 清单过滤 CS 子集。

HF 20231101 数据集的 text 列已是纯文本（无 wikitext 标记），id 与维基
page id 一致，可与 PetScan 返回的条目 ID 直接匹配。

用法（用 backend/.venv 的 python，需要 pyarrow）：
    python extract_hf_wiki_cs.py --lang zh \
        --parquet-dir ../.corpus_cache/hf_zh \
        --ids ../.corpus_cache/petscan_zh_ids.json \
        --out ../.corpus_cache/corpus_zhwiki_cs.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_ids(ids_path: Path) -> set[int]:
    with open(ids_path, encoding="utf-8") as fh:
        data = json.load(fh)
    ids: set[int] = set()
    for pages in data.values():
        for p in pages:
            try:
                ids.add(int(p["id"]))
            except (TypeError, ValueError):
                continue
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, help="zh/en，决定 source 字段")
    ap.add_argument("--parquet-dir", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import pyarrow.parquet as pq

    ids = load_ids(Path(args.ids))
    print(f"[ids] PetScan 清单 {len(ids)} 条", file=sys.stderr)

    domain = "zh.wikipedia.org" if args.lang == "zh" else "en.wikipedia.org"
    written = 0
    chars = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for path in sorted(Path(args.parquet_dir).glob("*.parquet")):
            table = pq.read_table(path, columns=["id", "title", "text"])
            ids_col = table.column("id").to_pylist()
            titles = table.column("title").to_pylist()
            texts = table.column("text").to_pylist()
            hit = 0
            for pid, title, text in zip(ids_col, titles, texts):
                # parquet id 可能是字符串，统一转 int 比对
                try:
                    pid_key = int(pid)
                except (TypeError, ValueError):
                    continue
                if pid_key not in ids or not text:
                    continue
                text = text.strip()
                if len(text) < 80:
                    continue
                out.write(json.dumps(
                    {
                        "id": f"{args.lang}wiki-{pid_key}",
                        "title": title,
                        "source": domain,
                        "license": "CC BY-SA 4.0",
                        "text": text,
                    },
                    ensure_ascii=False,
                ) + "\n")
                written += 1
                hit += 1
                chars += len(text)
            print(f"  {path.name}: 命中 {hit}", file=sys.stderr)

    print(json.dumps(
        {"matched": written, "petscan_ids": len(ids), "chars": chars},
        ensure_ascii=False))
    print(f"输出: {args.out}")


if __name__ == "__main__":
    main()
