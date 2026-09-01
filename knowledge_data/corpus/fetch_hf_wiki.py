#!/usr/bin/env python3
"""从 hf-mirror.com（HuggingFace 国内镜像）下载 wikimedia/wikipedia parquet 分片。

用法：
    python fetch_hf_wiki.py --lang zh --shards 41 --out-dir ../.corpus_cache/hf_zh
    python fetch_hf_wiki.py --lang en --shards 330 --out-dir ../.corpus_cache/hf_en
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://hf-mirror.com/datasets/wikimedia/wikipedia/resolve/main"
USER_AGENT = "CodeNexus-KB/1.0 (academic competition research)"


def fetch(url: str, dest: Path, timeout: int = 120) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  已存在，跳过: {dest.name}")
        return True
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(dest.with_suffix(".part"), "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        dest.with_suffix(".part").rename(dest)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  失败 {dest.name}: {exc}", file=sys.stderr)
        dest.with_suffix(".part").unlink(missing_ok=True)
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    for i in range(args.shards):
        name = f"train-{i:05d}-of-{args.shards:05d}.parquet"
        url = f"{BASE}/20231101.{args.lang}/{name}"
        for attempt in range(3):
            if fetch(url, out_dir / name):
                ok += 1
                break
            time.sleep(5)
        print(f"[{i + 1}/{args.shards}] ok={ok}", file=sys.stderr)
    print(f"完成: {ok}/{args.shards}")
    if ok < args.shards:
        sys.exit(1)


if __name__ == "__main__":
    main()
