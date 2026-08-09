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


def _submit(language_id: int, source_code: str, **limits: object) -> dict:
    # Judge0 1.13.1 runs wait=true submissions in the API container. Enqueue
    # and poll so execution stays inside the dedicated privileged Worker.
    query = urllib.parse.urlencode({"base64_encoded": "false", "wait": "false"})
    payload: dict[str, object] = {
        "source_code": source_code,
        "language_id": language_id,
        "cpu_time_limit": 2,
        "wall_time_limit": 5,
        "memory_limit": 131072,
        "max_processes_and_or_threads": 16,
        "max_file_size": 1024,
        "enable_per_process_and_thread_time_limit": True,
        "enable_per_process_and_thread_memory_limit": True,
        "enable_network": False,
    }
    payload.update(limits)
    result = _request(f"/submissions?{query}", method="POST", payload=payload)
    if not isinstance(result, dict):
        raise RuntimeError("Judge0 submission did not return an object")

    token = result.get("token")
    for _ in range(40):
        status = result.get("status") or {}
        if int(status.get("id", 0)) > 2:
            return result
        if not token:
            raise RuntimeError("queued submission did not return a token")
        time.sleep(0.5)
        polled = _request(
            f"/submissions/{urllib.parse.quote(str(token))}?base64_encoded=false"
        )
        if not isinstance(polled, dict):
            raise RuntimeError("Judge0 submission poll did not return an object")
        result = polled
    raise RuntimeError("Judge0 submission did not finish within 20 seconds")


def _status_id(result: dict) -> int:
    return int((result.get("status") or {}).get("id", 0))


def _assert_status(case: str, result: dict, expected: set[int]) -> None:
    actual = _status_id(result)
    if actual not in expected:
        description = (result.get("status") or {}).get("description")
        stderr = str(result.get("stderr") or "")[:300]
        message = str(result.get("message") or "")[:300]
        raise RuntimeError(
            f"{case}: expected status {sorted(expected)}, got {actual} "
            f"({description}); stderr={stderr!r}; message={message!r}"
        )


def _case_summary(result: dict) -> dict:
    status = result.get("status") or {}
    return {
        "status_id": status.get("id"),
        "status": status.get("description"),
        "time": result.get("time"),
        "memory_kb": result.get("memory"),
    }


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

    language_id = int(language["id"])
    results: dict[str, dict] = {}

    results["accepted"] = _submit(
        language_id, 'print("JUDGE0_SMOKE_OK")'
    )
    _assert_status("accepted", results["accepted"], {3})
    if str(results["accepted"].get("stdout") or "").strip() != "JUDGE0_SMOKE_OK":
        raise RuntimeError("accepted: stdout marker missing")

    results["compile_error"] = _submit(language_id, "def broken(:\n    pass")
    _assert_status("compile_error", results["compile_error"], {6})

    results["runtime_error"] = _submit(
        language_id, 'raise RuntimeError("synthetic runtime failure")'
    )
    _assert_status("runtime_error", results["runtime_error"], {7, 8, 9, 10, 11, 12})

    results["timeout"] = _submit(
        language_id,
        "while True:\n    pass",
        cpu_time_limit=1,
        wall_time_limit=2,
    )
    _assert_status("timeout", results["timeout"], {5})

    results["memory_limit"] = _submit(
        language_id,
        "payload = bytearray(256 * 1024 * 1024)\nprint(len(payload))",
        memory_limit=32768,
    )
    if _status_id(results["memory_limit"]) == 3:
        raise RuntimeError("memory_limit: oversized allocation was accepted")

    results["file_size_limit"] = _submit(
        language_id,
        'open("/tmp/judge0-large-output", "wb").write(b"x" * 262144)',
        max_file_size=64,
    )
    _assert_status("file_size_limit", results["file_size_limit"], {8, 11, 12})

    results["process_limit"] = _submit(
        language_id,
        "import os\n"
        "try:\n"
        "    pid = os.fork()\n"
        "except OSError:\n"
        "    print('PROCESS_BLOCKED')\n"
        "else:\n"
        "    if pid == 0:\n"
        "        os._exit(0)\n"
        "    os.waitpid(pid, 0)\n"
        "    print('PROCESS_CREATED')\n",
        max_processes_and_or_threads=1,
    )
    _assert_status("process_limit", results["process_limit"], {3})
    if str(results["process_limit"].get("stdout") or "").strip() != "PROCESS_BLOCKED":
        raise RuntimeError("process_limit: fork was not blocked")

    results["network_isolation"] = _submit(
        language_id,
        "import socket\n"
        "try:\n"
        "    sock = socket.create_connection(('1.1.1.1', 53), timeout=1)\n"
        "except OSError:\n"
        "    print('NETWORK_BLOCKED')\n"
        "else:\n"
        "    sock.close()\n"
        "    print('NETWORK_REACHABLE')\n",
        enable_network=False,
    )
    _assert_status("network_isolation", results["network_isolation"], {3})
    if str(results["network_isolation"].get("stdout") or "").strip() != "NETWORK_BLOCKED":
        raise RuntimeError("network_isolation: outbound connection was not blocked")

    summary = {
        "language": language.get("name"),
        "cases": {name: _case_summary(result) for name, result in results.items()},
        "process_limit_enforced": True,
        "file_size_limit_enforced": True,
        "memory_limit_enforced": True,
        "network_enabled": False,
        "network_isolation_enforced": True,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
