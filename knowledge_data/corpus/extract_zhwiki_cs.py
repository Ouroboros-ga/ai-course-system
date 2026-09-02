#!/usr/bin/env python3
"""从中文维基百科 dump 抽取计算机学科子集，构建语料层 JSONL。

输入（.corpus_cache/）：
- zhwiki-categorylinks.sql.gz —— 页面/子分类 → 分类关系
- zhwiki-multistream.xml.bz2 —— 全量条目正文（multistream 格式）

流程：
1. 解析 categorylinks，构建子分类图与 page→分类映射
2. 从根分类（计算机科学等 7 个）做 BFS 闭包，收集 CS 分类集
3. 过滤黑名单分类（维护性/跨领域大类），防止闭包爆炸
4. 单遍流式解压 multistream XML，抽取命中的 ns=0 条目
5. 粗清洗 wikitext（模板/ref/链接语法），输出 JSONL：
   {"id":..., "title":..., "text":..., "categories":[...]}

许可：维基百科内容为 CC BY-SA 4.0，语料层须保留署名（见 README）。

用法：
    python extract_zhwiki_cs.py [--cache-dir ../.corpus_cache] [--out xxx.jsonl]
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import json
import re
import sys
from collections import deque
from pathlib import Path

# 根分类（zhwiki 分类名，不含前缀）
ROOT_CATEGORIES = {
    "计算机科学",
    "人工智能",
    "软件工程",
    "计算机网络",
    "信息安全",
    "计算机系统结构",
    "数据库",
}

# 闭包黑名单：维护性分类或会拖入大量非 CS 内容的大类（分类名含关键词即排除）
CATEGORY_BLACKLIST_KEYWORDS = (
    "维基百科", "隐藏分类", "快速删除", "小作品", "需要", "待翻译", "参考",
    "格式", "模板", "分类", "列表", "公司", "人物", "奖项", "组织", "大学",
    "教育", "学科", "职业", "网站", "游戏", "各", "按国家", "历史",
)

# SQL INSERT 行元组正则：抓 cl_from / cl_to / cl_type 三个字段
_TUPLE_RE = re.compile(
    r"\(((?:'[^']*'|[^,()\s][^,()]*?),"
    r"('(?:[^']|'')*'|[^,()\s][^,()]*?),"
    r"(?:'(?:[^']|'')*'|NULL),"
    r"(?:'(?:[^']|'')*'|NULL),"
    r"(?:'(?:[^']|'')*'|[^,()]*?),"
    r"(?:'(?:[^']|'')*'|[^,()]*?),"
    r"'(page|subcat|file)'\)"
)


def _unescape_sql(value: str) -> str:
    """反转义 MySQL 字符串转义；分类名下划线转空格。"""
    return (
        value.replace("\\'", "'")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("_", " ")
    )


def parse_categorylinks(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """流式解析 categorylinks.sql.gz。

    返回：
    - subcats: 子分类名 → 父分类名集合（cl_type='subcat'）
    - page_cats: page_id(str) → 分类名集合（cl_type='page'）
    """
    subcats: dict[str, set[str]] = {}
    page_cats: dict[str, set[str]] = {}
    page_count = 0
    # INSERT 行可能极长（单行数万元组），按块读并缓冲跨块的残行
    buffer = ""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        while True:
            chunk = fh.read(8 * 1024 * 1024)
            if not chunk:
                break
            buffer += chunk
            last_nl = buffer.rfind("\n")
            if last_nl == -1:
                continue
            block, buffer = buffer[: last_nl + 1], buffer[last_nl + 1 :]
            if "INSERT INTO" not in block:
                continue
            for m in _TUPLE_RE.finditer(block):
                cl_from, cl_to, cl_type = m.group(1), m.group(2), m.group(7)
                if cl_type == "subcat":
                    child = _unescape_sql(cl_from)
                    parent = _unescape_sql(cl_to)
                    subcats.setdefault(child, set()).add(parent)
                elif cl_type == "page":
                    page_cats.setdefault(cl_from, set()).add(_unescape_sql(cl_to))
                    page_count += 1
    print(f"[categorylinks] 子分类 {len(subcats)} 个；"
          f"页面 {len(page_cats)} 个；分类标注 {page_count} 条", file=sys.stderr)
    return subcats, page_cats


def build_cs_closure(
    subcats: dict[str, set[str]],
) -> set[str]:
    """从根分类 BFS 子分类闭包，返回 CS 分类名全集。

    subcats 是 子分类→父分类 方向，需翻转成 父→子 后向下遍历。
    """
    children: dict[str, set[str]] = {}
    for child, parents in subcats.items():
        for parent in parents:
            children.setdefault(parent, set()).add(child)

    def _blacklisted(name: str) -> bool:
        return any(k in name for k in CATEGORY_BLACKLIST_KEYWORDS)

    closure: set[str] = set()
    queue: deque[str] = deque()
    for root in ROOT_CATEGORIES:
        closure.add(root)
        queue.append(root)
    while queue:
        cat = queue.popleft()
        for child in children.get(cat, ()):
            if child in closure or _blacklisted(child):
                continue
            closure.add(child)
            queue.append(child)
    print(f"[closure] CS 分类闭包 {len(closure)} 个", file=sys.stderr)
    return closure


def collect_cs_pages(
    page_cats: dict[str, set[str]], closure: set[str],
) -> dict[str, set[str]]:
    """收集至少属于一个 CS 分类的页面：page_id → 命中的 CS 分类。"""
    hits: dict[str, set[str]] = {}
    for page_id, cats in page_cats.items():
        matched = cats & closure
        if matched:
            hits[page_id] = matched
    print(f"[pages] 命中 CS 分类的条目 {len(hits)} 个", file=sys.stderr)
    return hits


_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_NESTED_LIMIT = 8
_REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
_EXT_LINK_RE = re.compile(r"\[(?:https?://[^ \]]+)[ ]?([^\]]*)\]")
_HEADING_RE = re.compile(r"={2,}\s*(.*?)\s*={2,}")
_BOLD_RE = re.compile(r"'{2,}")


def clean_wikitext(text: str) -> str:
    """粗清洗 wikitext 为纯文本（语料层用，不求完美）。"""
    text = _COMMENT_RE.sub("", text)
    text = _REF_RE.sub("", text)
    # 模板可能嵌套，迭代剥离
    for _ in range(_NESTED_LIMIT):
        new = _TEMPLATE_RE.sub("", text)
        if new == text:
            break
        text = new
    text = _LINK_RE.sub(lambda m: m.group(1), text)
    text = _EXT_LINK_RE.sub(lambda m: m.group(1), text)
    text = _HEADING_RE.sub(lambda m: m.group(1), text)
    text = _BOLD_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_ID_RE = re.compile(r"<id>(\d+)</id>")
_NS_RE = re.compile(r"<ns>(\d+)</ns>")
_TEXT_RE = re.compile(r"<text[^>]*>(.*?)</text>", re.S)


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
    )


def extract_articles(
    dump_path: Path, target_ids: dict[str, set[str]], out_path: Path,
) -> dict[str, int]:
    """单遍流式解压 multistream XML，抽取命中条目。"""
    stats = {"total_pages": 0, "written": 0, "chars": 0, "skipped_short": 0}
    with bz2.open(dump_path, "rt", encoding="utf-8", errors="replace") as fh, \
            open(out_path, "w", encoding="utf-8") as out:
        buffer = ""
        while True:
            chunk = fh.read(16 * 1024 * 1024)
            if not chunk:
                break
            buffer += chunk
            # 处理所有完整 <page>...</page> 块
            while True:
                start = buffer.find("<page>")
                if start == -1:
                    buffer = buffer[-64:]  # 保留尾部防标签跨块截断
                    break
                end = buffer.find("</page>", start)
                if end == -1:
                    buffer = buffer[start:]
                    # 单条目超 32MB 视为异常，丢弃防内存膨胀
                    if len(buffer) > 32 * 1024 * 1024:
                        buffer = ""
                    break
                page = buffer[start: end + len("</page>")]
                buffer = buffer[end + len("</page>"):]
                stats["total_pages"] += 1
                m_ns = _NS_RE.search(page)
                if not m_ns or m_ns.group(1) != "0":
                    continue
                m_id = _ID_RE.search(page)
                if not m_id or m_id.group(1) not in target_ids:
                    continue
                m_title = _TITLE_RE.search(page)
                m_text = _TEXT_RE.search(page)
                if not m_title or not m_text:
                    continue
                title = _xml_unescape(m_title.group(1))
                text = clean_wikitext(_xml_unescape(m_text.group(1)))
                if len(text) < 80:
                    stats["skipped_short"] += 1
                    continue
                cats = sorted(target_ids[m_id.group(1)])
                out.write(json.dumps(
                    {
                        "id": f"zhwiki-{m_id.group(1)}",
                        "title": title,
                        "source": "zh.wikipedia.org",
                        "license": "CC BY-SA 4.0",
                        "categories": cats,
                        "text": text,
                    },
                    ensure_ascii=False,
                ) + "\n")
                stats["written"] += 1
                stats["chars"] += len(text)
                if stats["written"] % 2000 == 0:
                    print(f"  已写 {stats['written']} 条 / 扫描 "
                          f"{stats['total_pages']} 页", file=sys.stderr)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=str(
        Path(__file__).resolve().parents[2] / ".corpus_cache"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    out_path = Path(args.out) if args.out else cache / "corpus_zhwiki_cs.jsonl"

    subcats, page_cats = parse_categorylinks(cache / "zhwiki-categorylinks.sql.gz")
    closure = build_cs_closure(subcats)
    hits = collect_cs_pages(page_cats, closure)

    stats = extract_articles(cache / "zhwiki-multistream.xml.bz2", hits, out_path)
    print(json.dumps(stats, ensure_ascii=False))
    print(f"输出: {out_path}")


if __name__ == "__main__":
    main()
