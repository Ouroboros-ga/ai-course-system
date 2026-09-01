#!/usr/bin/env python3
"""汇总语料层各 JSONL，生成 manifest.json（文档数/字符数/字节数/许可）。

用法：
    python build_manifest.py --corpus-dir ../.corpus_cache --out ../knowledge_data/corpus/manifest.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# 语料文件 → 人类可读名称
CORPUS_FILES = {
    "corpus_zhwiki_cs.jsonl": "中文维基百科·计算机学科子集",
    "corpus_enwiki_cs.jsonl": "英文维基百科·计算机学科子集",
    "corpus_rfc.jsonl": "RFC 全集",
    "corpus_arxiv_cs.jsonl": "arXiv·计算机学科论文全文（CC 授权子集）",
    "corpus_textbooks.jsonl": "权威开放教材（OSTEP/SICP）",
}


def stats_for(path: Path) -> dict:
    docs = 0
    chars = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            docs += 1
            chars += len(doc.get("text", ""))
    return {
        "file": path.name,
        "docs": docs,
        "chars": chars,
        "bytes": path.stat().st_size,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    corpus_dir = Path(args.corpus_dir)

    manifest: dict = {"sources": [], "total": {"docs": 0, "chars": 0, "bytes": 0}}
    for filename, label in CORPUS_FILES.items():
        path = corpus_dir / filename
        if not path.exists():
            continue
        s = stats_for(path)
        s["label"] = label
        manifest["sources"].append(s)
        manifest["total"]["docs"] += s["docs"]
        manifest["total"]["chars"] += s["chars"]
        manifest["total"]["bytes"] += s["bytes"]

    manifest["notes"] = (
        "语料层为开放许可来源：维基百科 CC BY-SA 4.0 署名、RFC 自由分发、"
        "arXiv CC 授权论文子集（Common Pile）、OSTEP/SICP 作者自由授权版本；"
        "作为学科知识库的补充参考层，与 knowledge_data/ 精编概念层分层使用；"
        "未包含任何未经授权的版权书籍全文。"
    )
    Path(args.out).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["total"], ensure_ascii=False))


if __name__ == "__main__":
    main()
