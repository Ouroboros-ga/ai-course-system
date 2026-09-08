"""CR2 本地 embedding 离线服务（loopback only，不对公网暴露）。

构建 Worker 与 Backend 查询经本服务取向量，Nexus 不加载模型：

    python backend/scripts/serve_corpus_embedding.py \\
        --model-dir /opt/smartcarb/models/multilingual-e5-small \\
        --model-config knowledge_data/corpus/rag/config.json

- 启动时离线加载固定模型（``local_files_only``，请求时绝不下载），
  校验文件存在、tokenizer 一致、维度经固定探针前向核验；
  任一失败拒绝启动；
- 接口：``GET /health`` 返回 model_fingerprint/dimension/ready；
  ``POST /embed`` 接收 kind=query|passage、texts、
  expected_model_fingerprint，返回 vectors/token_counts；
- 批次上限：查询批最多 8，文档批初始 16；超限 400；
  并发有上限，查询预留 slots 优先于批构建，超限 429（客户端退避重试）；
- 指纹不一致 409（拒绝混算，不可重试）。

退出码：0=正常退出；2=模型校验失败，拒绝启动。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logger = logging.getLogger("corpus_embedding_serve")

STATE: dict[str, Any] = {
    "provider": None,
    "fingerprint": "",
    "dimension": 0,
    "max_length": 0,
    "started_at": 0.0,
    "inflight_query": 0,
    "inflight_passage": 0,
}


def _limits() -> tuple[int, int, int, int]:
    try:
        from app.core.config import settings

        return (
            max(1, int(settings.CORPUS_EMBEDDING_QUERY_BATCH_MAX or 8)),
            max(1, int(settings.CORPUS_EMBEDDING_DOC_BATCH or 16)),
            max(1, int(settings.CORPUS_EMBEDDING_MAX_INFLIGHT or 4)),
            max(0, int(settings.CORPUS_EMBEDDING_QUERY_RESERVE or 1)),
        )
    except Exception:  # noqa: BLE001 - 无配置环境用计划默认值
        return (8, 16, 4, 1)


_GUARD_LOCK = asyncio.Lock()


async def _admit(kind: str) -> bool:
    """并发准入：查询优先（文档批为查询预留 slots），饱和即 False（429）。"""
    _, _, max_inflight, reserve = _limits()
    async with _GUARD_LOCK:
        total = STATE["inflight_query"] + STATE["inflight_passage"]
        if kind == "query":
            if total >= max_inflight:
                return False
            STATE["inflight_query"] += 1
            return True
        if total >= max(1, max_inflight - reserve):
            return False
        STATE["inflight_passage"] += 1
        return True


async def _release(kind: str) -> None:
    async with _GUARD_LOCK:
        key = "inflight_query" if kind == "query" else "inflight_passage"
        STATE[key] = max(0, STATE[key] - 1)


def create_app(provider) -> Any:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="corpus-embedding")
    STATE["provider"] = provider
    STATE["fingerprint"] = provider.model_fingerprint
    STATE["dimension"] = provider.dimension
    STATE["max_length"] = provider.max_length
    STATE["started_at"] = time.monotonic()

    @app.get("/health")
    def health():
        return {
            "ready": True,
            "model_fingerprint": STATE["fingerprint"],
            "dimension": STATE["dimension"],
            "max_length": STATE["max_length"],
            "uptime_seconds": round(time.monotonic() - STATE["started_at"], 1),
        }

    @app.post("/embed")
    async def embed(payload: dict):
        from app.platform.knowledge.corpus_embedding import (
            EmbeddingValidationError,
        )

        kind = str((payload or {}).get("kind") or "")
        texts = (payload or {}).get("texts") or []
        expected = str((payload or {}).get("expected_model_fingerprint") or "")
        query_max, doc_max, _, _ = _limits()
        if kind not in ("query", "passage"):
            return JSONResponse({"detail": "kind must be query|passage"},
                                status_code=400)
        if not isinstance(texts, list) or not texts or not all(
                isinstance(t, str) and t.strip() for t in texts):
            return JSONResponse({"detail": "texts must be non-empty strings"},
                                status_code=400)
        limit = query_max if kind == "query" else doc_max
        if len(texts) > limit:
            return JSONResponse(
                {"detail": f"batch too large (max {limit} for {kind})"},
                status_code=400)
        if expected and expected != STATE["fingerprint"]:
            return JSONResponse(
                {"detail": "model fingerprint mismatch（拒绝混算）",
                 "model_fingerprint": STATE["fingerprint"]},
                status_code=409)
        if not await _admit(kind):
            return JSONResponse({"detail": "server busy（退避重试）"},
                                status_code=429)
        try:
            loop = asyncio.get_running_loop()
            vectors = await loop.run_in_executor(
                None, lambda: provider.encode(texts, kind))
        except EmbeddingValidationError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        finally:
            await _release(kind)
        counts = [len(provider._tokenizer.encode(t, truncation=False))
                  for t in texts]
        return {"vectors": vectors, "token_counts": counts,
                "model_fingerprint": STATE["fingerprint"],
                "dimension": STATE["dimension"]}

    return app


def load_model_config(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, dict):
        raise SystemExit("SCHEMA_INVALID: 配置缺少 model 节")
    return {
        "model_id": model.get("id"),
        "revision": model.get("revision"),
        "files_hash": model.get("files_hash"),
        "tokenizer": model.get("tokenizer", model.get("id")),
        "pooling": model.get("pooling"),
        "prefixes": model.get("prefixes"),
        "dimension": model.get("dimension"),
        "max_length": model.get("max_length"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CR2 本地 embedding 离线服务")
    parser.add_argument("--model-dir", required=True, help="已下载模型目录")
    parser.add_argument("--model-config", required=True,
                        help="冻结模型配置 JSON（含 model 节）")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址（默认仅 loopback）")
    parser.add_argument("--port", type=int, default=8310, help="监听端口")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"拒绝监听非 loopback 地址：{args.host}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.platform.knowledge.corpus_embedding import E5Provider

    try:
        provider = E5Provider.load(args.model_dir, load_model_config(args.model_config))
    except Exception as exc:
        print(f"模型校验失败，拒绝启动：{exc}", file=sys.stderr)
        return 2
    logger.info("embedding 服务就绪：fingerprint=%s dimension=%s",
                provider.model_fingerprint, provider.dimension)
    import uvicorn

    uvicorn.run(create_app(provider), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
