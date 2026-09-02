#!/usr/bin/env python3
"""将 RFC 全集清洗为语料层 JSONL。

输入（.corpus_cache/rfc_txt/rfcXXXX.txt，rfc-editor.org 逐篇抓取）：
- 每个文件是一篇 RFC 纯文本

流程：
1. 逐个读取 RFC 文本
2. 从首页头部解析标题/日期/状态；正文原样保留（RFC 即权威文本，不做清洗）
3. 输出 JSONL：{"id":"rfc-XXXX","title":...,"source":"rfc-editor.org","text":...}

许可：RFC 文档本身可自由分发（IETF/RFC Editor 政策）。

用法：
    python build_rfc_corpus.py [--cache-dir ../.corpus_cache] [--out xxx.jsonl]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TITLE_RE = re.compile(r"^\s*Title:\s*(.+?)\s*$", re.M)
_DATE_RE = re.compile(r"^\s*Date:\s*(.+?)\s*$", re.M)
_STATUS_RE = re.compile(r"^\s*Status:\s*(.+?)\s*$", re.M)


def parse_rfc(filename: str, raw: str) -> dict | None:
    """解析单个 RFC 文本。"""
    m = re.search(r"rfc(\d+)\.txt$", filename, re.I)
    if not m:
        return None
    number = m.group(1)
    # 头部信息在文件前部，限定搜索范围避免误匹配
    head = raw[:4000]
    title_m = _TITLE_RE.search(head)
    date_m = _DATE_RE.search(head)
    status_m = _STATUS_RE.search(head)
    return {
        "id": f"rfc-{number}",
        "title": title_m.group(1) if title_m else f"RFC {number}",
        "date": date_m.group(1) if date_m else "",
        "status": status_m.group(1) if status_m else "",
        "source": "rfc-editor.org",
        "license": "freely distributable (IETF/RFC Editor)",
        "text": raw,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=str(
        Path(__file__).resolve().parents[2] / ".corpus_cache"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    out_path = Path(args.out) if args.out else cache / "corpus_rfc.jsonl"
    txt_dir = cache / "rfc_txt"

    written = 0
    chars = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for path in sorted(txt_dir.glob("rfc*.txt")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            doc = parse_rfc(path.name, raw)
            if doc is None or len(doc["text"]) < 200:
                continue
            out.write(json.dumps(doc, ensure_ascii=False) + "\n")
            written += 1
            chars += len(doc["text"])
            if written % 1000 == 0:
                print(f"  已写 {written} 篇", file=sys.stderr)

    print(json.dumps({"written": written, "chars": chars}, ensure_ascii=False))
    print(f"输出: {out_path}")


if __name__ == "__main__":
    main()
