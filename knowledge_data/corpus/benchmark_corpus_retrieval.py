"""CR0 语料盘点与检索基准 harness（CS 语料向量化与 RAG 上线）。

只用标准库；不访问网络、不调用模型。真实 embedding 通过 ``encode``
可调用对象注入（``benchmark_model(config, passages, queries, encode)``），
pytest 只用 fake encoder；真实模型评测走独立命令，不在自动测试中执行。

- ``inventory_sources(source_root, source_specs)``：流式扫描 JSONL，
  登记格式/文档身份/正文非空/许可元数据/重复比例。只记录异常行的
  来源 ID 与原因，不写全段日志；不按磁盘大小推算段落数。
- ``benchmark_model(...)``：给定 passages/queries 与 encoder，
  报告 Hit@k/MRR（中英分别）与无答案可分性；不宣称专家真值。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

SOURCE_KINDS = ("textbook", "zhwiki", "enwiki", "rfc", "arxiv")

#: 每个文件最多保留的异常行记录；超出只计数，不写全段日志。
MAX_ERROR_ROWS_PER_FILE = 50


def _is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def inventory_sources(source_root: Any, source_specs: list[dict]) -> dict[str, Any]:
    """流式盘点语料源，返回登记报告（不抛错，逐文件记录问题）。"""
    root = Path(source_root) if source_root is not None else None
    files: list[dict[str, Any]] = []
    total_documents = 0
    for spec in source_specs or []:
        kind = str((spec or {}).get("source_kind") or "")
        filename = str((spec or {}).get("file") or "")
        entry: dict[str, Any] = {
            "source_kind": kind,
            "file": filename,
            "lines": 0,
            "documents": 0,
            "bytes": 0,
            "chars": 0,
            "errors": [],
            "error_count": 0,
            "duplicate_ids": [],
            "missing_license": 0,
        }
        if kind not in SOURCE_KINDS or not filename:
            entry["errors"].append({
                "line_no": 0, "doc_id": "",
                "reason": "unknown_source_spec",
            })
            entry["error_count"] += 1
            files.append(entry)
            continue
        path = (root / filename) if root is not None else Path(filename)
        try:
            fh = path.open("rb")
        except OSError:
            entry["errors"].append({
                "line_no": 0, "doc_id": "", "reason": "file_unavailable",
            })
            entry["error_count"] += 1
            files.append(entry)
            continue
        seen: set[str] = set()
        duplicates: list[str] = []
        with fh:
            for line_no, raw in enumerate(fh, 1):
                entry["lines"] += 1
                entry["bytes"] += len(raw)
                try:
                    text_line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    _record(entry, line_no, "", "bad_encoding")
                    continue
                if not text_line.strip():
                    continue
                try:
                    doc = json.loads(text_line)
                except json.JSONDecodeError:
                    _record(entry, line_no, "", "bad_json")
                    continue
                if not isinstance(doc, dict):
                    _record(entry, line_no, "", "bad_record")
                    continue
                doc_id = str(doc.get("id") or "")
                if not doc_id:
                    _record(entry, line_no, "", "missing_id")
                    continue
                if doc_id in seen:
                    if doc_id not in duplicates:
                        duplicates.append(doc_id)
                    _record(entry, line_no, doc_id, "duplicate_id")
                    continue
                seen.add(doc_id)
                body = doc.get("text")
                if not _is_nonempty_text(body):
                    _record(entry, line_no, doc_id, "empty_text")
                    continue
                if not doc.get("license"):
                    entry["missing_license"] += 1
                entry["documents"] += 1
                entry["chars"] += len(str(body))
        entry["duplicate_ids"] = duplicates
        total_documents += entry["documents"]
        files.append(entry)

    if total_documents == 0:
        status = "empty"
    elif any(f["error_count"] for f in files):
        status = "partial"
    else:
        status = "ok"
    return {"status": status, "document_count": total_documents, "files": files}


def _record(entry: dict, line_no: int, doc_id: str, reason: str) -> None:
    entry["error_count"] += 1
    if len(entry["errors"]) < MAX_ERROR_ROWS_PER_FILE:
        entry["errors"].append({
            "line_no": line_no, "doc_id": doc_id, "reason": reason})


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def benchmark_model(
    config: dict,
    passages: list[dict],
    queries: list[dict],
    encode: Callable[[list[str], str], list[list[float]]],
    top_k: int = 10,
) -> dict[str, Any]:
    """用注入的 encoder 评测检索：Hit@k/MRR 分语言报告，无答案只报可分性。

    - 有答案题：已知 relevant_passage_ids，计 hit@k 与 MRR；
    - 无答案题（kind=no_answer）：不设阈值判对错，只报其最高相似度
      相对有答案题 top-1 最小值的可分率（no_answer_separable_rate），
      即“能否用一个统一阈值将其与有答案题分开”。
    """
    model_id = str((config or {}).get("model", {}).get("id") or "unknown")
    passage_ids = [str(p.get("passage_id") or "") for p in passages]
    passage_texts = [str(p.get("text") or "") for p in passages]
    passage_vectors = encode(passage_texts, "passage")
    if len(passage_vectors) != len(passages):
        raise ValueError("SCHEMA_INVALID: encoder 返回数量与 passages 不一致")

    per_lang: dict[str, dict[str, Any]] = {}
    answerable_top1: list[float] = []
    no_answer_best: list[float] = []

    def _bucket(lang: str) -> dict[str, Any]:
        return per_lang.setdefault(
            lang, {"queries": 0, "hits": 0, "reciprocal_ranks": []})

    for query in queries or []:
        kind = str(query.get("kind") or "")
        text = str(query.get("text") or "")
        relevant = [str(x) for x in (query.get("relevant_passage_ids") or [])]
        if not text:
            continue
        vector = encode([text], "query")[0]
        ranked = sorted(
            range(len(passages)),
            key=lambda i: _cosine(vector, passage_vectors[i]),
            reverse=True,
        )
        best = _cosine(vector, passage_vectors[ranked[0]]) if ranked else 0.0
        if kind == "no_answer":
            no_answer_best.append(best)
            continue
        if not relevant:
            continue
        bucket = _bucket(kind or "unknown")
        bucket["queries"] += 1
        rank = None
        for position in range(min(top_k, len(ranked))):
            if passage_ids[ranked[position]] in relevant:
                rank = position + 1
                break
        if rank is not None:
            bucket["hits"] += 1
            bucket["reciprocal_ranks"].append(1.0 / rank)
        answerable_top1.append(best)

    report: dict[str, Any] = {
        "model": model_id,
        f"hit_at_{top_k}": 0.0,
        "mrr": 0.0,
        "query_count": 0,
        "by_kind": {},
        "no_answer_count": len(no_answer_best),
        "no_answer_separable_rate": 0.0,
        "no_answer_empty_rate": 0.0,
    }
    total_hits = 0
    total_rr = 0.0
    total_q = 0
    for lang, bucket in sorted(per_lang.items()):
        queries_n = bucket["queries"]
        hit_rate = bucket["hits"] / queries_n if queries_n else 0.0
        mrr = (sum(bucket["reciprocal_ranks"]) / queries_n) if queries_n else 0.0
        report["by_kind"][lang] = {
            "queries": queries_n,
            f"hit_at_{top_k}": hit_rate,
            "mrr": mrr,
        }
        total_hits += bucket["hits"]
        total_rr += sum(bucket["reciprocal_ranks"])
        total_q += queries_n
    if total_q:
        report[f"hit_at_{top_k}"] = total_hits / total_q
        report["mrr"] = total_rr / total_q
        report["query_count"] = total_q
    if no_answer_best and answerable_top1:
        floor = min(answerable_top1)
        separable = sum(1 for s in no_answer_best if s < floor)
        report["no_answer_separable_rate"] = separable / len(no_answer_best)
        report["no_answer_empty_rate"] = report["no_answer_separable_rate"]
    elif no_answer_best:
        report["no_answer_separable_rate"] = 1.0
        report["no_answer_empty_rate"] = 1.0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="CR0 语料盘点（流式，不加载全文件）")
    parser.add_argument("--source-root", required=True, help="JSONL 语料目录")
    parser.add_argument("--specs", required=True,
                        help="来源规格 JSON 文件（[{source_kind,file,format}]）")
    parser.add_argument("--output", default="",
                        help="报告输出路径（默认 stdout）")
    args = parser.parse_args()
    specs = json.loads(Path(args.specs).read_text(encoding="utf-8"))
    report = inventory_sources(args.source_root, specs)
    body = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
    else:
        print(body)


if __name__ == "__main__":
    main()
