"""CR6 语料 RAG 检索验收 CLI（默认不调用回答模型）。

用法（§7.3）：

    python backend/scripts/verify_corpus_rag.py \
        --release-id "$CORPUS_RELEASE_ID" --suite public-cs --retrieval-only

- 对指定 release 逐条跑 ``CorpusSearchService``（词法 + 向量同源路径），
  统计命中/未命中/降级/错误码、每个返回 ``reference_id`` 是否可解析且
  属于本次 release、以及单查询延迟分位；
- **默认只检查检索**：``--with-generation`` 必须同时给
  ``--max-generation-calls N>0``（显式开启 + 调用预算），且需要
  ``VERIFY_CORPUS_GENERATION_URL`` 已配置，否则拒绝运行（exit 3），
  不静默跳过、不默认调用任何回答模型；
- 生成问答返回的引用逐条回读校验（越版本/伪造引用计入 fabricated）。

退出码：0=执行完成；1=引用完整性失败（不可解析或伪造引用）；
2=参数/版本错误；3=生成问答未配置。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent

VERIFY_VERSION = "corpus-verify/1"

#: 检索题集注册表（suite → 相对仓库根的 queries.jsonl 路径）。
SUITES = {
    "public-cs": "knowledge_data/corpus/rag/queries.jsonl",
}


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1,
                max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return round(sorted_values[index], 1)


def _load_queries(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _build_embed_client(environ: dict, model_fingerprint: str):
    """按部署配置构造推理客户端；无配置返回 None（词法降级，如实报告）。"""
    url = str(environ.get("CORPUS_EMBEDDING_URL") or "").strip()
    if url:
        from app.platform.knowledge.corpus_embedding import HttpEmbedClient

        return HttpEmbedClient(base_url=url,
                               expected_fingerprint=model_fingerprint)
    model_path = str(environ.get("CORPUS_EMBEDDING_MODEL_PATH") or "").strip()
    if not model_path:
        return None
    from app.platform.knowledge.corpus_embedding import E5Provider

    def _attr(name: str, default: Any = "") -> Any:
        try:
            from app.core.config import settings

            return getattr(settings, name, default)
        except Exception:  # noqa: BLE001 - 无配置环境用默认
            return default

    from app.platform.knowledge.corpus_embedding import family_spec

    spec = family_spec(_attr("CORPUS_EMBEDDING_FAMILY", "e5"))
    provider = E5Provider.load(model_path, {
        "family": spec["family"],
        "model_id": _attr("CORPUS_EMBEDDING_MODEL_ID"),
        "revision": _attr("CORPUS_EMBEDDING_MODEL_REVISION"),
        "files_hash": _attr("CORPUS_EMBEDDING_FILES_HASH"),
        "tokenizer": _attr("CORPUS_EMBEDDING_TOKENIZER"),
        "pooling": spec["pooling"],
        "prefixes": spec["prefixes"],
        "dimension": _attr("CORPUS_EMBEDDING_DIMENSION"),
        "max_length": _attr("CORPUS_EMBEDDING_MAX_LENGTH"),
    })

    class _LocalAdapter:
        def embed(self, texts, kind="passage"):
            vectors = provider.encode(list(texts), kind)
            counts = [len(provider._tokenizer.encode(
                t, truncation=False)) for t in texts]
            return {"vectors": vectors, "token_counts": counts,
                    "model_fingerprint": provider.model_fingerprint}

    return _LocalAdapter()


def _run_generation(environ: dict, session, queries: list[dict],
                    release_id: str, budget: int) -> dict:
    """显式开启的生成问答（有预算）：逐条回读校验返回引用。"""
    import httpx

    from app.services.discipline_knowledge.corpus_index import (
        CorpusIndexError,
        get_chunk_reference,
    )

    url = str(environ.get("VERIFY_CORPUS_GENERATION_URL") or "").strip()
    token = str(environ.get("VERIFY_CORPUS_GENERATION_TOKEN") or "").strip()
    stats = {"calls": 0, "answers": 0, "failures": 0,
             "citations_checked": 0, "citations_resolved": 0,
             "citations_fabricated": 0}
    for row in queries:
        if stats["calls"] >= budget:
            break
        stats["calls"] += 1
        try:
            response = httpx.post(
                url, json={"query": str(row.get("text") or ""),
                           "release_id": release_id},
                headers={"Authorization": f"Bearer {token}"} if token else {},
                timeout=120.0)
            response.raise_for_status()
            body = response.json()
        except Exception:  # noqa: BLE001 - 单条失败计数，不中断验收
            stats["failures"] += 1
            continue
        stats["answers"] += 1
        for reference_id in body.get("reference_ids") or []:
            stats["citations_checked"] += 1
            ref_release, _, chunk_id = str(reference_id).partition(":")
            if ref_release != release_id:
                stats["citations_fabricated"] += 1
                continue
            try:
                get_chunk_reference(session, chunk_id, release_id)
                stats["citations_resolved"] += 1
            except CorpusIndexError:
                stats["citations_fabricated"] += 1
    return stats


def _run_retrieval(session, queries: list[dict], release_id: str, top_k: int,
                   embed_client) -> dict:
    from app.services.discipline_knowledge.corpus_index import (
        CorpusIndexError,
        get_chunk_reference,
    )
    from app.services.discipline_knowledge.corpus_search import (
        CorpusSearchService,
    )

    service = CorpusSearchService()
    stats = {"queries": 0, "scorable": 0, "unscorable": 0, "hit": 0, "miss": 0,
             "unavailable": 0, "errors": 0, "no_answer_queries": 0,
             "no_answer_with_results": 0}
    references = {"checked": 0, "resolved": 0, "failed": 0,
                  "not_in_release": 0}
    modes = {"hybrid": 0, "lexical": 0}
    error_codes: dict[str, int] = {}
    latencies: list[float] = []
    reciprocal_ranks: list[float] = []

    for row in queries:
        stats["queries"] += 1
        query_id = str(row.get("query_id") or f"q{stats['queries']}")
        text = str(row.get("text") or "")
        relevant = {str(item) for item in (row.get("relevant_passage_ids") or [])}
        is_no_answer = str(row.get("kind") or "") == "no_answer"
        if is_no_answer:
            stats["no_answer_queries"] += 1
        started = time.perf_counter()
        try:
            outcome = service.search(session, text, top_k=top_k,
                                     release_id=release_id,
                                     embed_client=embed_client)
        except CorpusIndexError as exc:
            stats["errors"] += 1
            error_codes[exc.error_code] = error_codes.get(exc.error_code, 0) + 1
            continue
        latencies.append((time.perf_counter() - started) * 1000.0)
        modes[outcome.get("mode") or "lexical"] = modes.get(
            outcome.get("mode") or "lexical", 0) + 1
        for reason in outcome.get("degraded_reasons") or []:
            code = str(reason).split(":", 1)[0]
            error_codes[code] = error_codes.get(code, 0) + 1
        if outcome.get("status") == "unavailable":
            stats["unavailable"] += 1
        results = outcome.get("results") or []
        if is_no_answer and results:
            stats["no_answer_with_results"] += 1

        matched_rank = 0
        for rank, result in enumerate(results, start=1):
            references["checked"] += 1
            try:
                get_chunk_reference(session, result["chunk_id"], release_id)
                references["resolved"] += 1
            except CorpusIndexError as exc:
                references["failed"] += 1
                if exc.error_code == "NOT_IN_RELEASE":
                    references["not_in_release"] += 1
            if not matched_rank and relevant and (
                    result["chunk_id"] in relevant
                    or str(result.get("doc_id")) in relevant):
                matched_rank = rank

        if not relevant:
            stats["unscorable"] += 1
        else:
            stats["scorable"] += 1
            if matched_rank:
                stats["hit"] += 1
                reciprocal_ranks.append(1.0 / matched_rank)
            else:
                stats["miss"] += 1

    latencies.sort()
    scorable = stats["scorable"]
    return {
        "stats": {
            **stats,
            "hit_at_k": round(stats["hit"] / scorable, 4) if scorable else None,
            "mrr": round(sum(reciprocal_ranks) / scorable, 4)
            if scorable else None,
        },
        "references": references,
        "modes": modes,
        "error_codes": error_codes,
        "latency_ms": {
            "samples": len(latencies),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(latencies[-1], 1) if latencies else 0.0,
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="CR6 语料 RAG 检索验收（默认 retrieval-only）")
    parser.add_argument("--release-id", default="",
                        help="待验收版本（缺省用当前 head）")
    parser.add_argument("--suite", default="public-cs",
                        help="检索题集名（默认 public-cs）")
    parser.add_argument("--queries", type=Path, default=None,
                        help="自定义 queries.jsonl（覆盖 --suite）")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--retrieval-only", action="store_true",
                        help="只检查检索（默认行为，显式声明用）")
    parser.add_argument("--with-generation", action="store_true",
                        help="显式开启生成问答（必须配 --max-generation-calls）")
    parser.add_argument("--max-generation-calls", type=int, default=0,
                        help="生成问答调用预算（>0 才允许开启）")
    parser.add_argument("--json-out", type=Path, default=None,
                        help="把报告同时写入文件")
    args = parser.parse_args(argv)

    if args.with_generation and args.max_generation_calls <= 0:
        print("GENERATION_BUDGET_REQUIRED: --with-generation 必须同时给 "
              "--max-generation-calls N>0（生成问答有调用预算）", file=sys.stderr)
        return 2
    environ = dict(os.environ)
    if args.with_generation and not str(
            environ.get("VERIFY_CORPUS_GENERATION_URL") or "").strip():
        print("GENERATION_NOT_CONFIGURED: VERIFY_CORPUS_GENERATION_URL "
              "未配置，拒绝调用回答模型", file=sys.stderr)
        return 3

    if args.queries is not None:
        queries_path = args.queries
    else:
        relative = SUITES.get(args.suite)
        if relative is None:
            print(f"SUITE_NOT_FOUND: 未登记题集 {args.suite}（可选："
                  f"{sorted(SUITES)}）", file=sys.stderr)
            return 2
        queries_path = REPO_ROOT / relative
    if not queries_path.is_file():
        print(f"QUERIES_NOT_FOUND: {queries_path}", file=sys.stderr)
        return 2
    try:
        queries = _load_queries(queries_path)
    except Exception as exc:  # noqa: BLE001 - 题集格式错误即拒绝运行
        print(f"QUERIES_INVALID: {queries_path}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    from app.models.database import session_factory
    from app.services.discipline_knowledge import corpus_index as index_svc
    from app.services.discipline_knowledge.corpus_index import CorpusIndexError

    with session_factory() as session:
        release_id = args.release_id or index_svc.read_head(session)["release_id"]
        if not release_id:
            print("NOT_READY: 无 release-id 且当前无已发布版本", file=sys.stderr)
            return 2
        try:
            view = index_svc.get_release(session, release_id)
        except CorpusIndexError as exc:
            print(f"{exc.error_code}: {exc}", file=sys.stderr)
            return 2
        fingerprint = str((view.get("counts") or {}).get(
            "model_fingerprint") or "")
        try:
            embed_client = _build_embed_client(environ, fingerprint)
        except Exception as exc:  # noqa: BLE001 - 配置了推理端但不可用即拒绝
            print(f"EMBED_CLIENT_UNAVAILABLE: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        retrieval = _run_retrieval(session, queries, release_id, args.top_k,
                                   embed_client)
        generation = None
        if args.with_generation:
            generation = _run_generation(
                environ, session, queries, release_id,
                args.max_generation_calls)

    report = {
        "verify_version": VERIFY_VERSION,
        "release_id": release_id,
        "suite": args.suite,
        "queries_path": str(queries_path),
        "top_k": args.top_k,
        "retrieval_only": not args.with_generation,
        "generation_called": bool(generation and generation["calls"]),
        "embed_client": "http" if environ.get("CORPUS_EMBEDDING_URL")
        else ("local" if environ.get("CORPUS_EMBEDDING_MODEL_PATH")
              else "none"),
        **retrieval,
        "generation": generation,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_out is not None:
        args.json_out.write_text(payload + "\n", encoding="utf-8")

    if retrieval["references"]["failed"] > 0:
        print(f"REFERENCE_UNRESOLVED: {retrieval['references']['failed']} 个"
              "返回引用不可解析", file=sys.stderr)
        return 1
    if generation and generation["citations_fabricated"] > 0:
        print(f"CITATION_FABRICATED: {generation['citations_fabricated']} 个"
              "引用越版本或伪造", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
