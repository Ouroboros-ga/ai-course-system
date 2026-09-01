#!/usr/bin/env python3
"""抓取权威开放教材，构建教材语料层 corpus_textbooks.jsonl。

书目（全部为作者自由授权版本）：
1. OSTEP《Operating Systems: Three Easy Pieces》(Remzi & Andrea Arpaci-Dusseau)
   - CC BY-NC-ND，逐章 PDF，正文提取为纯文本
   - https://pages.cs.wisc.edu/~remzi/OSTEP/
2. SICP《Structure and Interpretation of Computer Programs》2e (MIT)
   - CC BY-SA，HTML 版
   - https://sarabander.github.io/sicp/
3. Think Python 2e (Allen B. Downey, Green Tea Press)
   - CC BY-NC，HTML 版
   - https://greenteapress.com/thinkpython2/html/

输出 JSONL：{"id":"ostep-<slug>","title":...,"book":...,"source":...,
"license":...,"text":...}

用法：
    python fetch_textbooks.py [--cache-dir ../.corpus_cache]
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

UA = "CodeNexus-KB/1.0 (academic competition research)"


def http_get(url: str, timeout: int = 60, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return data if binary else data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(3)


def strip_html(raw: str) -> str:
    """HTML → 纯文本（去 script/style/nav，保留段落换行）。"""
    raw = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>",
                 "", raw, flags=re.S | re.I)
    raw = re.sub(r"<br[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|div|h[1-6]|li|tr|pre|blockquote)>", "\n",
                 raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html_mod.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


# ---------------------------------------------------------------- OSTEP

def fetch_ostep(cache: Path) -> list[dict]:
    """OSTEP：抓主页全部章节 PDF，逐章提取文本。"""
    import fitz  # PyMuPDF

    index_html = http_get("https://pages.cs.wisc.edu/~remzi/OSTEP/")
    # OSTEP 页面的 href 无引号：<a href=cpu-intro.pdf>
    pdfs = sorted(set(re.findall(r'href=["\']?([^"\'\s>]+\.pdf)', index_html)))
    print(f"[ostep] 发现 {len(pdfs)} 个 PDF", file=sys.stderr)

    docs: list[dict] = []
    pdf_dir = cache / "textbooks" / "ostep"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name in pdfs:
        slug = name.rsplit(".", 1)[0]
        dest = pdf_dir / name
        if not dest.exists() or dest.stat().st_size == 0:
            data = http_get(
                f"https://pages.cs.wisc.edu/~remzi/OSTEP/{name}", binary=True)
            dest.write_bytes(data)
        try:
            with fitz.open(dest) as pdf:
                text = "\n".join(page.get_text() for page in pdf)
        except Exception as exc:  # noqa: BLE001
            print(f"  [ostep] {name} 提取失败: {exc}", file=sys.stderr)
            continue
        text = text.strip()
        if len(text) < 1000:
            continue
        docs.append({
            "id": f"ostep-{slug}",
            "title": slug.replace("-", " ").title(),
            "book": "Operating Systems: Three Easy Pieces",
            "source": "pages.cs.wisc.edu/~remzi/OSTEP",
            "license": "CC BY-NC-ND 3.0",
            "text": text,
        })
        print(f"  [ostep] {name}: {len(text)} 字符", file=sys.stderr)
    return docs


# ---------------------------------------------------------------- SICP

SICP_CHAPTERS = {
    "1": "Building Abstractions with Procedures",
    "2": "Building Abstractions with Data",
    "3": "Modularity, Objects, and State",
    "4": "Metalinguistic Abstraction",
    "5": "Register Machines for Abstract Machines",
}


def fetch_sicp() -> list[dict]:
    """SICP 2e：sarabander HTML 版，按章抓取合并小节。

    小节文件名为 texinfo 转义形式：<ch>_002e<sec>.xhtml（002e 即 '.'），
    小节编号从 1 连续递增至 404。
    """
    docs: list[dict] = []
    for ch, title in SICP_CHAPTERS.items():
        parts: list[str] = []
        for sec in range(1, 12):
            url = (f"https://sarabander.github.io/sicp/html/"
                   f"{ch}_002e{sec}.xhtml")
            try:
                raw = http_get(url, timeout=30)
            except Exception:  # noqa: BLE001
                break
            text = strip_html(raw)
            if len(text) < 200:
                break
            parts.append(text)
        if not parts:
            print(f"  [sicp] 第 {ch} 章无内容", file=sys.stderr)
            continue
        docs.append({
            "id": f"sicp-ch{ch}",
            "title": f"Chapter {ch}: {title}",
            "book": "Structure and Interpretation of Computer Programs (2e)",
            "source": "sarabander.github.io/sicp",
            "license": "CC BY-SA 4.0",
            "text": "\n\n".join(parts),
        })
        print(f"  [sicp] 第 {ch} 章: {len(parts)} 小节", file=sys.stderr)
    return docs


# ---------------------------------------------------------------- Think Python

def fetch_think_python() -> list[dict]:
    """Think Python 2e：Green Tea Press HTML 版，逐章抓取。"""
    docs: list[dict] = []
    for n in range(0, 22):
        name = f"thinkpython2{n:04d}.html"
        url = f"https://greenteapress.com/thinkpython2/html/{name}"
        try:
            raw = http_get(url, timeout=30)
        except Exception:  # noqa: BLE001
            continue
        text = strip_html(raw)
        if len(text) < 800:
            continue
        title_m = re.search(
            r"^(Chapter\s+\d+[^\n]*|Preface[^\n]*|Introduction[^\n]*)",
            text, re.M)
        docs.append({
            "id": f"thinkpython2e-{n:04d}",
            "title": (title_m.group(1).strip() if title_m
                      else f"Section {n}"),
            "book": "Think Python 2e",
            "source": "greenteapress.com/thinkpython2",
            "license": "CC BY-NC 3.0",
            "text": text,
        })
        print(f"  [thinkpython] {name}: {len(text)} 字符", file=sys.stderr)
    return docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=str(
        Path(__file__).resolve().parents[2] / ".corpus_cache"))
    args = ap.parse_args()
    cache = Path(args.cache_dir)
    out_path = cache / "corpus_textbooks.jsonl"

    docs: list[dict] = []
    docs += fetch_ostep(cache)
    docs += fetch_sicp()
    docs += fetch_think_python()

    chars = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for doc in docs:
            out.write(json.dumps(doc, ensure_ascii=False) + "\n")
            chars += len(doc["text"])
    print(json.dumps(
        {"written": len(docs), "chars": chars}, ensure_ascii=False))
    print(f"输出: {out_path}")


if __name__ == "__main__":
    main()
