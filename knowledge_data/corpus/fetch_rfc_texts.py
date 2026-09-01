#!/usr/bin/env python3
"""逐个抓取 rfc-editor.org 上的全部 RFC 文本（RIPE 镜像限速后的替代路径）。

- 每线程独立 HTTPSConnection（keep-alive 复用连接）
- 已存在的文件跳过（可断点续传）
- 404（编号空洞/未发布）记录后跳过

用法：
    python fetch_rfc_texts.py --out-dir ../.corpus_cache/rfc_txt --max 10038
"""
from __future__ import annotations

import argparse
import http.client
import ssl
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOST = "www.rfc-editor.org"
USER_AGENT = "CodeNexus-KB/1.0 (academic competition research)"
_ctx = ssl.create_default_context()


def fetch_range(lo: int, hi: int, out_dir: Path, counter: dict) -> None:
    conn = http.client.HTTPSConnection(HOST, timeout=60, context=_ctx)
    try:
        for n in range(lo, hi + 1):
            dest = out_dir / f"rfc{n}.txt"
            if dest.exists() and dest.stat().st_size > 0:
                with counter["lock"]:
                    counter["skip"] += 1
                continue
            for attempt in range(3):
                try:
                    conn.request(
                        "GET", f"/rfc/rfc{n}.txt",
                        headers={"User-Agent": USER_AGENT,
                                 "Connection": "keep-alive"})
                    resp = conn.getresponse()
                    body = resp.read()
                    if resp.status == 200 and body:
                        tmp = dest.with_suffix(".tmp")
                        tmp.write_bytes(body)
                        tmp.rename(dest)
                        with counter["lock"]:
                            counter["ok"] += 1
                            counter["bytes"] += len(body)
                    elif resp.status == 404:
                        with counter["lock"]:
                            counter["missing"] += 1
                        break
                    else:
                        raise OSError(f"HTTP {resp.status}")
                    break
                except Exception:  # noqa: BLE001
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = http.client.HTTPSConnection(
                        HOST, timeout=60, context=_ctx)
                    time.sleep(2)
            with counter["lock"]:
                done = counter["ok"] + counter["skip"] + counter["missing"]
                if done % 500 == 0:
                    print(f"  进度 {done}：ok={counter['ok']} "
                          f"skip={counter['skip']} miss={counter['missing']} "
                          f"({counter['bytes'] // 1048576}MB)", file=sys.stderr)
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max", type=int, default=10038)
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    counter = {"ok": 0, "skip": 0, "missing": 0, "bytes": 0,
               "lock": threading.Lock()}
    step = (args.max + args.threads - 1) // args.threads
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = []
        for t in range(args.threads):
            lo = t * step + 1
            hi = min((t + 1) * step, args.max)
            if lo > hi:
                continue
            futures.append(pool.submit(fetch_range, lo, hi, out_dir, counter))
        for f in futures:
            f.result()

    print(f"完成 ok={counter['ok']} skip={counter['skip']} "
          f"missing={counter['missing']} "
          f"bytes={counter['bytes'] // 1048576}MB")


if __name__ == "__main__":
    main()
