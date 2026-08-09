#!/usr/bin/env python3
"""Run a secret-safe, synthetic Judge0 execution smoke test."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = os.getenv("JUDGE0_URL", "http://127.0.0.1:2358").rstrip("/")
AUTHN_TOKEN = os.getenv("JUDGE0_AUTHN_TOKEN", "")
AUTHZ_TOKEN = os.getenv("JUDGE0_AUTHZ_TOKEN", "")


def _request(path: str, *, method: str = "GET", payload: dict | None = None) -> object:
    headers = {"Accept": "application/json"}
    if AUTHN_TOKEN:
        headers["X-Auth-Token"] = AUTHN_TOKEN
    if AUTHZ_TOKEN:
        headers["X-Auth-User"] = AUTHZ_TOKEN
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        error_body = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Judge0 HTTP {exc.code}: {error_body}") from exc


def main() -> int:
    if not AUTHN_TOKEN or not AUTHZ_TOKEN:
        print("missing Judge0 authentication environment", file=sys.stderr)
        return 2

    languages = _request("/languages")
    if not isinstance(languages, list):
        raise RuntimeError("Judge0 /languages did not return a list")
    python_languages = [
        item
        for item in languages
        if isinstance(item, dict)
        and str(item.get("name", "")).casefold().startswith("python")
    ]
    if not python_languages:
        raise RuntimeError("Judge0 has no enabled Python language")
    language = max(python_languages, key=lambda item: int(item.get("id", 0)))

    query = urllib.parse.urlencode({"base64_encoded": "false", "wait": "true"})
    result = _request(
        f"/submissions?{query}",
        method="POST",
        payload={
            "source_code": 'print("JUDGE0_SMOKE_OK")',
            "language_id": language["id"],
            "cpu_time_limit": 2,
            "wall_time_limit": 5,
            "memory_limit": 131072,
            "enable_network": False,
        },
    )
    if not isinstance(result, dict):
        raise RuntimeError("Judge0 submission did not return an object")

    token = result.get("token")
    for _ in range(20):
        status = result.get("status") or {}
        if int(status.get("id", 0)) > 2:
            break
        if not token:
            raise RuntimeError("queued submission did not return a token")
        time.sleep(0.5)
        result = _request(
            f"/submissions/{urllib.parse.quote(str(token))}?base64_encoded=false"
        )
    else:
        raise RuntimeError("Judge0 submission did not finish within 10 seconds")

    status = result.get("status") or {}
    stdout = str(result.get("stdout") or "").strip()
    summary = {
        "language": language.get("name"),
        "status_id": status.get("id"),
        "status": status.get("description"),
        "stdout": stdout,
        "stderr": str(result.get("stderr") or "").strip()[:500],
        "message": str(result.get("message") or "").strip()[:500],
        "time": result.get("time"),
        "memory_kb": result.get("memory"),
        "network_enabled": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if status.get("id") == 3 and stdout == "JUDGE0_SMOKE_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
