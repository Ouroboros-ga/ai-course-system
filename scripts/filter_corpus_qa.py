#!/usr/bin/env python3
"""过滤语料 QA：CS 主题相关性 + 去重 + 长度校验，输出训练用 corpus_qa.jsonl 与溯源文件。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

IN_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/corpus_qa_raw.jsonl")
OUT_TRAIN = Path("data/corpus_qa.jsonl")
OUT_META = Path("data/corpus_qa_provenance.jsonl")

CS_ZH = ("算法", "复杂度", "数据结构", "操作系统", "数据库", "网络协议", "编译", "机器学习",
         "深度学习", "进程", "线程", "内存", "缓存", "加密", "排序", "检索", "计算机", "软件工程",
         "编程", "代码", "处理器", "指令", "路由", "传输", "图论", "二叉", "哈希", "堆", "链表",
         "栈", "队列", "递归", "字节", "服务器", "带宽", "内核", "文件系统", "死锁", "人工智能",
         "神经网络", "密码", "防火墙", "协议", "带宽", "散列", "指针", "数组", "程序")
CS_EN = ("algorithm", "complexity", "data structure", "operating system", "database", "protocol",
         "compiler", "machine learning", "process", "thread", "memory", "cache", "encryption",
         "sorting", "computer", "software", "programming", "code", "processor", "instruction",
         "routing", "graph", "tree", "hash", "heap", "linked list", "stack", "queue", "recursion",
         "kernel", "file system", "deadlock", "neural network", "cpu", "tcp", "ip ", "http",
         "encryption", "authentication", "binary search", "array", "pointer", "server", "bandwidth",
         "packet", "scheduling", "virtual memory", "deadlock", "sql", "query", "distributed",
         "cryptograph", "network", "comput", "compile", "runtime", "function", "variable")

JUNK_ZH = ("电视", "电视剧", "电影", "游戏机", "歌手", "演员", "足球俱乐部", "选举", "省份", "明星")
JUNK_EN = ("television", "video game console", "football club", "singer", "celebrity")


def relevant(text: str) -> bool:
    low = text.lower()
    if any(j in text for j in JUNK_ZH) or any(j in low for j in JUNK_EN):
        return False
    return any(k in text for k in CS_ZH) or any(k in low for k in CS_EN)


def main() -> int:
    rows = [json.loads(l) for l in IN_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    kept, rej_topic, rej_dup, rej_len = [], 0, 0, 0
    seen = set()
    for r in rows:
        q = r["messages"][0]["content"]
        a = r["messages"][1]["content"]
        if not (10 <= len(q) <= 150 and 30 <= len(a) <= 800):
            rej_len += 1
            continue
        if q in seen:
            rej_dup += 1
            continue
        if not relevant(q + " " + a):
            rej_topic += 1
            continue
        seen.add(q)
        kept.append(r)
    with OUT_TRAIN.open("w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")
    with OUT_META.open("w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r.get("meta", {}), ensure_ascii=False) + "\n")

    from collections import Counter
    langs = Counter(m.get("lang", "?") for m in (r.get("meta", {}) for r in kept))
    srcs = Counter((m.get("source", "") or "?")[:30] for m in (r.get("meta", {}) for r in kept))
    print(f"[OK] 保留 {len(kept)} / {len(rows)}（主题过滤 {rej_topic}，重复 {rej_dup}，长度 {rej_len}）")
    print(f"     语言分布: {dict(langs)}")
    print(f"     Top 来源: {srcs.most_common(5)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
