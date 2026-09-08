"""CR2 serve_corpus_embedding HTTP 语义与 HttpEmbedClient 验收。

覆盖：/health 身份、400（kind/空文本/超批）、409（指纹不一致）、
422（向量校验失败）、并发准入（文档批为查询预留 slots → 429 语义），
以及客户端重试/非重试错误分类（loopback 脚本化服务，不加载模型）。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "backend" / "scripts"

TEST_FP = "emfp_serve_test_001"
TEST_DIM = 4


class _FakeTokenizer:
    def encode(self, text, truncation=False):  # noqa: ARG002 - 只计数
        return list(range(max(1, len(str(text)) // 4)))


class _FakeProvider:
    """最小 provider：接口与 E5Provider 一致，不加载模型。"""

    def __init__(self, fail_with: str | None = None):
        self.model_fingerprint = TEST_FP
        self.dimension = TEST_DIM
        self.max_length = 64
        self._tokenizer = _FakeTokenizer()
        self.fail_with = fail_with
        self.calls: list[tuple[list[str], str]] = []

    def encode(self, texts, kind):
        from app.platform.knowledge.corpus_embedding import (
            EmbeddingValidationError,
        )

        self.calls.append((list(texts), kind))
        if self.fail_with:
            raise EmbeddingValidationError(self.fail_with, "fake failure")
        return [[1.0] + [0.0] * (TEST_DIM - 1) for _ in texts]


def _load_serve_module():
    spec = importlib.util.spec_from_file_location(
        "serve_corpus_embedding", SCRIPTS_DIR / "serve_corpus_embedding.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _client(provider):
    module = _load_serve_module()
    return module, TestClient(module.create_app(provider))


def test_health_reports_model_identity():
    _, client = _client(_FakeProvider())
    body = client.get("/health").json()
    assert body["ready"] is True
    assert body["model_fingerprint"] == TEST_FP
    assert body["dimension"] == TEST_DIM
    assert body["max_length"] == 64
    assert body["uptime_seconds"] >= 0


def test_embed_rejects_bad_kind_and_empty_texts():
    _, client = _client(_FakeProvider())
    assert client.post(
        "/embed", json={"kind": "bogus", "texts": ["x"]}).status_code == 400
    assert client.post(
        "/embed", json={"kind": "query", "texts": []}).status_code == 400
    assert client.post(
        "/embed", json={"kind": "query", "texts": ["  "]}).status_code == 400


def test_embed_enforces_batch_limits():
    _, client = _client(_FakeProvider())
    assert client.post(
        "/embed", json={"kind": "query", "texts": ["q"] * 9}).status_code == 400
    assert client.post(
        "/embed",
        json={"kind": "passage", "texts": ["p"] * 17}).status_code == 400
    ok = client.post("/embed", json={"kind": "passage", "texts": ["p"] * 16})
    assert ok.status_code == 200
    body = ok.json()
    assert body["dimension"] == TEST_DIM
    assert body["model_fingerprint"] == TEST_FP
    assert len(body["token_counts"]) == 16


def test_embed_fingerprint_mismatch_is_409():
    _, client = _client(_FakeProvider())
    response = client.post("/embed", json={
        "kind": "query", "texts": ["q"],
        "expected_model_fingerprint": "emfp_other"})
    assert response.status_code == 409


def test_embed_validation_error_is_422():
    _, client = _client(_FakeProvider(fail_with="NON_FINITE"))
    response = client.post("/embed", json={"kind": "query", "texts": ["q"]})
    assert response.status_code == 422
    assert "NON_FINITE" in response.json()["detail"]


class _ScriptedEmbedServer:
    """脚本化 loopback 服务：按顺序回放 (status, body)，并记录请求次数。"""

    def __init__(self, script: list[tuple[int, dict]]):
        self.script = list(script)
        self.requests = 0
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D102 - 测试静音
                pass

            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
                outer.requests += 1
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                status, body = outer.script[
                    min(outer.requests - 1, len(outer.script) - 1)]
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _ok_body(texts: int) -> dict:
    return {"vectors": [[1.0, 0.0, 0.0, 0.0] for _ in range(texts)],
            "token_counts": [1 for _ in range(texts)],
            "model_fingerprint": TEST_FP, "dimension": TEST_DIM}


def _embed_client(server, **kwargs):
    from app.platform.knowledge.corpus_embedding import HttpEmbedClient

    return HttpEmbedClient(base_url=server.url, **kwargs)


def test_http_client_retries_429_then_succeeds():
    server = _ScriptedEmbedServer([(429, {"detail": "busy"}),
                                   (200, _ok_body(1))])
    try:
        client = _embed_client(server, expected_fingerprint=TEST_FP)
        result = client.embed(["查询"], "query")
    finally:
        server.stop()
    assert server.requests == 2
    assert result["model_fingerprint"] == TEST_FP
    assert result["dimension"] == TEST_DIM


def test_http_client_retries_5xx_then_succeeds():
    server = _ScriptedEmbedServer([(503, {"detail": "oops"}),
                                   (200, _ok_body(1))])
    try:
        client = _embed_client(server, expected_fingerprint=TEST_FP)
        result = client.embed(["查询"], "query")
    finally:
        server.stop()
    assert server.requests == 2
    assert result["vectors"]


def test_http_client_fingerprint_mismatch_is_not_retried():
    from app.platform.knowledge.corpus_embedding import EmbeddingValidationError

    server = _ScriptedEmbedServer([(200, {**_ok_body(1),
                                          "model_fingerprint": "emfp_other"})])
    try:
        client = _embed_client(server, expected_fingerprint=TEST_FP)
        with pytest.raises(EmbeddingValidationError) as exc_info:
            client.embed(["查询"], "query")
    finally:
        server.stop()
    assert exc_info.value.error_code == "MODEL_MISMATCH"
    assert server.requests == 1  # 不可重试：拒绝混算


def test_http_client_4xx_is_provider_unavailable():
    from app.platform.knowledge.corpus_embedding import EmbeddingValidationError

    server = _ScriptedEmbedServer([(400, {"detail": "bad"})])
    try:
        client = _embed_client(server)
        with pytest.raises(EmbeddingValidationError) as exc_info:
            client.embed(["查询"], "query")
    finally:
        server.stop()
    assert exc_info.value.error_code == "PROVIDER_UNAVAILABLE"


def test_http_client_unreachable_after_retries():
    from app.platform.knowledge.corpus_embedding import (
        EmbeddingValidationError,
        HttpEmbedClient,
    )

    # 指向已关闭端口，模拟服务不可达
    client = HttpEmbedClient(base_url="http://127.0.0.1:9", max_retries=1)
    with pytest.raises(EmbeddingValidationError) as exc_info:
        client.embed(["查询"], "query")
    assert exc_info.value.error_code == "PROVIDER_UNAVAILABLE"


def test_admission_reserves_slots_for_queries():
    """并发准入：文档批为查询预留 slots，饱和返回 False（429 语义）。"""
    module = _load_serve_module()

    async def _scenario():
        module.STATE["inflight_query"] = 0
        module.STATE["inflight_passage"] = 0
        admitted = [await module._admit("passage") for _ in range(5)]
        query_first = await module._admit("query")
        query_second = await module._admit("query")
        for _ in range(5):
            await module._release("passage")
        return admitted, query_first, query_second

    admitted, query_first, query_second = asyncio.run(_scenario())
    # 默认 max_inflight=4、reserve=1 → 文档批最多 3；查询优先占预留位
    assert admitted[:3] == [True, True, True]
    assert admitted[3:] == [False, False]
    assert query_first is True
    assert query_second is False
