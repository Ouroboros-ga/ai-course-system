"""DK0 学科语料抽样清单工具（学科知识库自动化构建 V1）。

把一份**文档登记清单**（manifest，DK1 起由 ``discipline_document_versions``
表投影得到；DK0 阶段可用合成 fixture）按 ``source_kind`` 分层抽样，
产出 ``sample_manifest.json``：记录抽样种子、分层选择、文档族归属、
可处理数量与 token 粗估。

设计要点（见 ``knowledge_data/pipeline/README.md`` 与实施计划 DK0）：

- 五类来源：``textbook / zhwiki / enwiki / rfc / arxiv``。
- 按 ``family_id``（文档族，如同一词条各语言版本、同一 RFC 的修订版、
  同一教材的不同章节）划分示例集（example）与评估集（evaluation），
  两集合的族 ID 严格不交，防止示例/调参内容泄漏进评估。
- 确定性：相同输入（manifest 内容 + seed + per_source）两次执行产出
  完全相同的 ``chunk_ids``；排序键全部来自 ``sha256(seed + 各级 ID)``，
  与输入文档的排列顺序无关。增删一个文档只影响该文档自身条目及其
  指纹，不改变其他文档的相对顺序。
- token 为**容量粗估**（ASCII 约 4 字符/token，CJK 约 1.25 字符/token
  当量），只用于预算与吞吐估算，不作为计费依据；绝不用原始 GB
  直接推算概念数量。
- 本模块只用标准库，不访问服务器、不读生产数据、不调用模型。
  ``manifest`` 必须由调用方显式传入文件的字典或路径，不存在默认
  服务器地址。

Manifest 文档条目格式::

    {
      "documents": [
        {
          "document_id": "ostep-ch05",
          "source_kind": "textbook",
          "family_id": "ostep",
          "version": "v1",
          "chunks": ["c1", "c2", ...],   # 或 [{"chunk_id": ..., "text"/"chars": ...}]
          "char_count": 12345,            # 可选，用于分摊粗估
          "token_estimate": 3100,         # 可选，缺失时按 chunks 粗估
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SOURCE_KINDS = ("textbook", "zhwiki", "enwiki", "rfc", "arxiv")

SAMPLE_SCHEMA = "discipline-sample/1"

DEFAULT_SEED = 20260908

#: 示例集占每来源配额的比例（按族划分后，在族内按配额取数）。
EXAMPLE_FRACTION = 0.2

#: token 粗估公式的版本号（公式变化必须同步 bump，供预算对比时识别口径）。
TOKEN_ESTIMATE_VERSION = "tok-est/1"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def estimate_tokens(text: str) -> int:
    """粗估文本 token 数：ASCII 约 4 字符/token，CJK 字符另按 ~1 当量计入。

    公式：``len(text) // 4 + cjk_chars``（空文本返回 0）。
    与 ``backend/app/services/discipline_knowledge/identity.py`` 同口径；
    任一处修改必须同步另一处并 bump ``TOKEN_ESTIMATE_VERSION``。
    """
    text = str(text or "")
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    return max(1, len(text) // 4 + cjk_chars)


def _stable_rank(seed: Any, *parts: Any) -> str:
    """与输入顺序无关的确定性排序键。"""
    joined = "|".join([str(seed)] + [str(p) for p in parts])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _normalize_chunks(raw_chunks: Any, document_id: str) -> list[dict[str, Any]]:
    """把 chunks 归一为 [{"chunk_id": ...}]（保留 text/chars 供粗估）。"""
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError(
            f"SCHEMA_INVALID: document '{document_id}' has no chunks "
            "(expected non-empty list of chunk ids or {chunk_id,...} dicts)"
        )
    normalized: list[dict[str, Any]] = []
    for entry in raw_chunks:
        if isinstance(entry, str):
            if not entry:
                raise ValueError(
                    f"SCHEMA_INVALID: document '{document_id}' contains empty chunk id"
                )
            normalized.append({"chunk_id": entry})
        elif isinstance(entry, dict) and entry.get("chunk_id"):
            normalized.append(dict(entry))
        else:
            raise ValueError(
                f"SCHEMA_INVALID: document '{document_id}' has malformed chunk entry "
                f"{entry!r} (expected chunk id string or dict with 'chunk_id')"
            )
    return normalized


def _chunk_token_estimate(
    chunk: dict[str, Any], doc_char_count: int, doc_token_estimate: int, doc_chunks: int
) -> tuple[int, int]:
    """返回 (chars, tokens) 粗估：优先 chunk 自带 text/chars，否则按文档分摊。"""
    if chunk.get("text"):
        text = str(chunk["text"])
        return len(text), estimate_tokens(text)
    if chunk.get("chars") is not None:
        try:
            chars = max(0, int(chunk["chars"]))
        except (TypeError, ValueError):
            chars = 0
        return chars, estimate_tokens("x" * chars) if chars else (0, 0)
    if doc_char_count and doc_chunks:
        chars = doc_char_count // doc_chunks
        tokens = (doc_token_estimate // doc_chunks) if doc_token_estimate else estimate_tokens("x" * chars)
        return chars, tokens
    return 0, 0


def _load_manifest(manifest: Any) -> dict[str, Any]:
    """接受 manifest 字典或 JSON 文件路径，返回归一后的 {"documents": [...]}。"""
    if isinstance(manifest, (str, Path)):
        path = Path(manifest)
        if not path.is_file():
            raise FileNotFoundError(
                f"SOURCE_UNAVAILABLE: manifest file not found: {path}"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"SCHEMA_INVALID: manifest is not valid JSON: {exc}") from exc
    elif isinstance(manifest, dict):
        data = manifest
    else:
        raise ValueError(
            "SCHEMA_INVALID: manifest must be a dict or a JSON file path, "
            f"got {type(manifest).__name__}"
        )
    if isinstance(data, dict) and isinstance(data.get("documents"), list):
        documents = data["documents"]
    elif isinstance(data, list):
        documents = data
    else:
        raise ValueError(
            "SCHEMA_INVALID: manifest must contain a 'documents' list "
            "(DK1 起由 discipline_document_versions 投影得到；DK0 可用合成 fixture)"
        )
    if not documents:
        raise ValueError("SOURCE_UNAVAILABLE: manifest contains no documents")
    return {"documents": documents}


def _normalize_per_source(per_source: Any) -> dict[str, int]:
    """per_source 可为 int（每类同额）或 {source_kind: n} 字典。"""
    if isinstance(per_source, int):
        if per_source <= 0:
            raise ValueError("SCHEMA_INVALID: per_source must be a positive int")
        return {kind: per_source for kind in SOURCE_KINDS}
    if isinstance(per_source, dict):
        normalized: dict[str, int] = {}
        for key, value in per_source.items():
            if key not in SOURCE_KINDS:
                raise ValueError(
                    f"SCHEMA_INVALID: unknown source_kind '{key}' "
                    f"(expected one of {', '.join(SOURCE_KINDS)})"
                )
            if not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"SCHEMA_INVALID: per_source['{key}'] must be a non-negative int"
                )
            normalized[key] = value
        for kind in SOURCE_KINDS:
            normalized.setdefault(kind, 0)
        return normalized
    raise ValueError("SCHEMA_INVALID: per_source must be int or dict")


def prepare_sample(
    manifest: Any,
    seed: Any = DEFAULT_SEED,
    per_source: Any = 200,
    output_dir: Any = None,
) -> dict[str, Any]:
    """按来源分层抽样，产出可复现的样本清单。

    Args:
        manifest: 文档登记清单（字典或 JSON 路径），格式见模块 docstring。
        seed: 抽样种子；相同种子 + 相同内容必得相同 ``chunk_ids``。
        per_source: 每来源配额（int 或 {source_kind: n}）。
        output_dir: 非空时把 ``sample_manifest.json`` 写到该目录并返回同内容。

    Returns:
        样本清单字典，含 ``chunk_ids``、``selection``、示例/评估族集合、
        ``counts``、``chars_total``、``token_estimate_total`` 与 ``fingerprint``。
    """
    data = _load_manifest(manifest)
    quota = _normalize_per_source(per_source)

    # -- 校验并分组（未知 source_kind 直接拒绝，不静默丢弃） --
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in SOURCE_KINDS}
    for index, doc in enumerate(data["documents"]):
        if not isinstance(doc, dict):
            raise ValueError(f"SCHEMA_INVALID: documents[{index}] must be an object")
        document_id = str(doc.get("document_id") or "").strip()
        source_kind = str(doc.get("source_kind") or "").strip()
        if not document_id:
            raise ValueError(f"SCHEMA_INVALID: documents[{index}] missing 'document_id'")
        if source_kind not in SOURCE_KINDS:
            raise ValueError(
                f"SCHEMA_INVALID: documents[{index}] unknown source_kind "
                f"'{source_kind}' (expected one of {', '.join(SOURCE_KINDS)})"
            )
        family_id = str(doc.get("family_id") or document_id)
        chunks = _normalize_chunks(doc.get("chunks"), document_id)
        try:
            doc_char_count = max(0, int(doc.get("char_count") or 0))
        except (TypeError, ValueError):
            doc_char_count = 0
        try:
            doc_token_estimate = max(0, int(doc.get("token_estimate") or 0))
        except (TypeError, ValueError):
            doc_token_estimate = 0
        by_kind[source_kind].append({
            "document_id": document_id,
            "source_kind": source_kind,
            "family_id": family_id,
            "version": str(doc.get("version") or ""),
            "chunks": chunks,
            "char_count": doc_char_count,
            "token_estimate": doc_token_estimate,
        })

    selection: list[dict[str, Any]] = []
    example_families: set[str] = set()
    evaluation_families: set[str] = set()
    selected_per_kind: dict[str, int] = {kind: 0 for kind in SOURCE_KINDS}
    chars_total = 0
    token_total = 0

    for kind in SOURCE_KINDS:
        docs = by_kind[kind]
        if not docs or quota[kind] <= 0:
            continue
        families: dict[str, list[dict[str, Any]]] = {}
        for doc in docs:
            families.setdefault(doc["family_id"], []).append(doc)
        ordered_families = sorted(
            families, key=lambda fam: _stable_rank(seed, kind, "family", fam)
        )
        # 族级切分：单族时全部归评估（空示例集仍与评估不交）；多族时前 20%
        # （至少 1 族）作示例，其余作评估。
        if len(ordered_families) == 1:
            example_fams: list[str] = []
            eval_fams = ordered_families
        else:
            n_example = max(1, int(len(ordered_families) * EXAMPLE_FRACTION))
            example_fams = ordered_families[:n_example]
            eval_fams = ordered_families[n_example:]

        example_quota = min(quota[kind], max(1, int(quota[kind] * EXAMPLE_FRACTION)))
        eval_quota = quota[kind] - example_quota
        if not example_fams:
            eval_quota = quota[kind]
            example_quota = 0

        def _take(fams: list[str], limit: int, split: str) -> None:
            nonlocal chars_total, token_total
            if limit <= 0:
                return
            ordered_docs: list[dict[str, Any]] = []
            for fam in fams:
                ordered_docs.extend(sorted(
                    families[fam],
                    key=lambda d: _stable_rank(seed, kind, "doc", fam, d["document_id"]),
                ))
            taken = 0
            for doc in ordered_docs:
                if taken >= limit:
                    break
                for chunk in doc["chunks"]:
                    if taken >= limit:
                        break
                    chars, tokens = _chunk_token_estimate(
                        chunk, doc["char_count"], doc["token_estimate"], len(doc["chunks"])
                    )
                    selection.append({
                        "chunk_id": str(chunk["chunk_id"]),
                        "document_id": doc["document_id"],
                        "source_kind": kind,
                        "family_id": doc["family_id"],
                        "split": split,
                    })
                    selected_per_kind[kind] += 1
                    chars_total += chars
                    token_total += tokens
                    taken += 1

        _take(eval_fams, eval_quota, "evaluation")
        _take(example_fams, example_quota, "example")
        example_families.update(example_fams)
        evaluation_families.update(eval_fams)

    # -- 确定性排序：按来源固定顺序，评估在前、示例在后，同组内按选择顺序 --
    kind_order = {kind: i for i, kind in enumerate(SOURCE_KINDS)}
    selection.sort(key=lambda s: (kind_order[s["source_kind"]], 0 if s["split"] == "evaluation" else 1))

    fingerprint_payload = {
        "schema": SAMPLE_SCHEMA,
        "seed": str(seed),
        "per_source": {kind: quota[kind] for kind in SOURCE_KINDS},
        "items": sorted(
            [
                [s["document_id"], s["chunk_id"],
                 next(d["version"] for d in by_kind[s["source_kind"]]
                      if d["document_id"] == s["document_id"]), s["split"]]
                for s in selection
            ]
        ),
    }
    fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]

    result: dict[str, Any] = {
        "schema": SAMPLE_SCHEMA,
        "generator": "knowledge_data/corpus/prepare_knowledge_sample.py",
        "token_estimate_version": TOKEN_ESTIMATE_VERSION,
        "seed": seed if isinstance(seed, int) else str(seed),
        "per_source": {kind: quota[kind] for kind in SOURCE_KINDS},
        "fingerprint": fingerprint,
        "chunk_ids": [s["chunk_id"] for s in selection],
        "selection": selection,
        "example_document_families": sorted(example_families),
        "evaluation_document_families": sorted(evaluation_families),
        "counts": {
            "requested": {kind: quota[kind] for kind in SOURCE_KINDS},
            "selected": dict(selected_per_kind),
            "selected_total": len(selection),
            "selected_by_split": {
                "evaluation": sum(1 for s in selection if s["split"] == "evaluation"),
                "example": sum(1 for s in selection if s["split"] == "example"),
            },
            "documents": len({s["document_id"] for s in selection}),
            "families": len(set(example_families) | set(evaluation_families)),
        },
        "chars_total": chars_total,
        "token_estimate_total": token_total,
        "notes": [
            "评估集与示例集按 family_id 划分，两集合无共享族，防止泄漏。",
            "token_estimate_total 为容量粗估（tok-est/1），不作为计费依据；",
            "不用原始 GB 直接推算概念数量，实际产出以构建运行为准。",
        ],
    }

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "sample_manifest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="学科语料分层抽样（DK0）：产出可复现的样本清单")
    parser.add_argument("--manifest", required=True, help="文档登记清单 JSON 文件路径")
    parser.add_argument("--seed", default=DEFAULT_SEED, help="抽样种子（默认 20260908）")
    parser.add_argument(
        "--per-source",
        default="200",
        help="每来源配额：整数，或 JSON 字典如 '{\"textbook\": 200}'",
    )
    parser.add_argument("--output-dir", required=True, help="输出目录（写入 sample_manifest.json）")
    args = parser.parse_args()

    try:
        seed: Any = int(args.seed)
    except (TypeError, ValueError):
        seed = args.seed
    per_source: Any
    try:
        per_source = int(args.per_source)
    except (TypeError, ValueError):
        per_source = json.loads(args.per_source)

    result = prepare_sample(args.manifest, seed=seed, per_source=per_source, output_dir=args.output_dir)
    print(json.dumps({
        "fingerprint": result["fingerprint"],
        "counts": result["counts"],
        "token_estimate_total": result["token_estimate_total"],
        "output": str(Path(args.output_dir) / "sample_manifest.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
