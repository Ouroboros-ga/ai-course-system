#!/usr/bin/env python3
"""英文维基 CS 分类清单获取（健壮版）。

大分类（Computer science）depth 3 的响应可达 12MB+，弱网下 IncompleteRead
频发。本脚本：
- 每个分类查询失败自动降深度重试（3 → 2 → 1 → 0）
- 每个分类成功后立即落盘（增量保存，中途失败不丢已完成部分）
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PETSCAN_URL = "https://petscan.wmcloud.org/"
USER_AGENT = "CodeNexus-KB/1.0 (academic competition research)"

ROOT_CATEGORIES = [
    "Computer science", "Artificial intelligence", "Software engineering",
    "Computer networks", "Computer security", "Computer architecture",
    "Databases",
]

# 大分类 depth 3 响应可达 12MB+（弱网必断），上限降到 2；
# 小分类保持 depth 3。
MAX_DEPTH_HINTS = {
    "Computer science": 2,
    "Artificial intelligence": 2,
    # 第二轮补充分类：过宽的分类收窄深度，避免混入大量
    # 公司/游戏/人物等非学科条目
    "Computing": 1,
    "Internet": 1,
    "Information technology": 1,
    "Software": 2,
    "Robotics": 2,
    "Natural language processing": 2,
    "Neural networks": 2,
}

# 第一轮（已完成）：
#   Operating systems, Compilers, Computer graphics, Theory of computation,
#   Data structures, Algorithms, Parallel computing, Distributed computing,
#   Cryptography, Programming languages, Human–computer interaction,
#   Computer vision, Machine learning
# 第二轮补充：
EXTRA_CATEGORIES = [
    "Computing", "Internet", "World Wide Web",
    "Theoretical computer science", "Software", "Supercomputing",
    "Quantum computing", "Computational science", "Informatics",
    "Information technology", "Natural language processing",
    "Neural networks", "Robotics", "Cloud computing",
    "Embedded systems", "Data mining", "Information retrieval",
    "Computer programming",
]


def query(lang: str, category: str, depth: int, timeout: int) -> list[dict]:
    data = urllib.parse.urlencode({
        "language": lang, "project": "wikipedia",
        "categories": category, "depth": str(depth),
        "namespaces": "0", "format": "json", "doit": "1",
    }).encode()
    req = urllib.request.Request(
        PETSCAN_URL, data=data,
        headers={"User-Agent": USER_AGENT}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return [
        {"id": pg.get("id"), "title": pg.get("title")}
        for block in payload.get("*", [])
        for pg in block.get("a", {}).get("*", [])
        if pg.get("namespace", 0) == 0
    ]


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "petscan_en_ids.json")
    result: dict[str, list[dict]] = {}
    if out_path.exists():
        result = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] 已有 {sum(len(v) for v in result.values())} 条", file=sys.stderr)

    for cat in ROOT_CATEGORIES + EXTRA_CATEGORIES:
        if cat in result and result[cat]:
            print(f"[skip] {cat} 已完成", file=sys.stderr)
            continue
        pages: list[dict] = []
        max_depth = MAX_DEPTH_HINTS.get(cat, 3)
        depths = tuple(d for d in (3, 2, 1, 0) if d <= max_depth)
        for depth in depths:
            for attempt in range(2):
                try:
                    pages = query("en", cat, depth, 300)
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{cat}] depth={depth} 第 {attempt + 1} 次失败: "
                          f"{type(exc).__name__}", file=sys.stderr)
                    time.sleep(5)
            if pages:
                break
            print(f"  [{cat}] depth={depth} 无结果，降深度", file=sys.stderr)
        result[cat] = pages
        out_path.write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(f"[{cat}] 最终命中 {len(pages)} 条（已落盘）", file=sys.stderr)

    total = sum(len(v) for v in result.values())
    print(f"[total] {total} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
