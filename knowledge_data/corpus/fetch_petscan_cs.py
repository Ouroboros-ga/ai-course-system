#!/usr/bin/env python3
"""通过 PetScan 获取维基百科 CS 分类树的文章 ID/标题清单。

PetScan（petscan.wmcloud.org）支持按分类树深度展开，返回命中条目清单。
本脚本对 7 个根分类逐一查询（避免超大规模联合查询超时），
输出 JSON：{category: [{"id":..., "title":...}, ...]}。

用法：
    python fetch_petscan_cs.py --lang zh --out ../.corpus_cache/petscan_zh_ids.json
    python fetch_petscan_cs.py --lang en --out ../.corpus_cache/petscan_en_ids.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

PETSCAN_URL = "https://petscan.wmcloud.org/"
USER_AGENT = "CodeNexus-KB/1.0 (academic competition research)"

# 根分类：zh/en 两个语言版的根分类名
ROOT_CATEGORIES = {
    "zh": [
        "计算机科学", "人工智能", "软件工程", "计算机网络",
        "信息安全", "计算机系统结构", "数据库",
    ],
    "en": [
        "Computer science", "Artificial intelligence", "Software engineering",
        "Computer networks", "Computer security", "Computer architecture",
        "Databases",
    ],
}


def query_category(lang: str, category: str, depth: int, timeout: int) -> list[dict]:
    """查询单个分类树，返回 [{'id':..,'title':..}, ...]。"""
    data = urllib.parse.urlencode({
        "language": lang,
        "project": "wikipedia",
        "categories": category,
        "depth": str(depth),
        "namespaces": "0",
        "format": "json",
        "doit": "1",
        "subpage_filter": "either",
    }).encode()
    req = urllib.request.Request(
        PETSCAN_URL, data=data,
        headers={"User-Agent": USER_AGENT}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    # PetScan JSON 结构：{"*": [{"a": {"*": [{id,title,namespace,...}, ...]}, ...}]}
    pages: list[dict] = []
    try:
        for block in payload.get("*", []):
            for page in block.get("a", {}).get("*", []):
                if page.get("namespace", 0) == 0:
                    pages.append({"id": page.get("id"), "title": page.get("title")})
    except (KeyError, TypeError):
        pass
    return pages


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["zh", "en"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    all_ids: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for cat in ROOT_CATEGORIES[args.lang]:
        pages = []
        for attempt in range(3):
            try:
                pages = query_category(args.lang, cat, args.depth, args.timeout)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  [{cat}] 第 {attempt + 1} 次失败: {exc}", file=sys.stderr)
                time.sleep(5)
        fresh = [p for p in pages if p["id"] not in seen]
        seen.update(p["id"] for p in pages)
        all_ids[cat] = fresh
        print(f"[{cat}] 命中 {len(pages)} 条（新增 {len(fresh)}）", file=sys.stderr)

    total = sum(len(v) for v in all_ids.values())
    print(f"[total] 去重后 {total} 条", file=sys.stderr)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(all_ids, fh, ensure_ascii=False)
    print(f"输出: {args.out}")


if __name__ == "__main__":
    main()
