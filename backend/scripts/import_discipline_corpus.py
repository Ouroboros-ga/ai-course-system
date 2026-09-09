"""学科语料导入 CLI（CR1：manifest 清单 + 来源集两种模式）。

用法::

    python backend/scripts/import_discipline_corpus.py --manifest <清单> --limit-docs 100 --dry-run
    python backend/scripts/import_discipline_corpus.py --source-set cs-public --limit-docs 200
    python backend/scripts/import_discipline_corpus.py --source-set cs-public --chunker corpus --limit-docs 200

- ``--dry-run`` 只验证并列出范围（无库写入、无存储写入）；
- 省略 ``--dry-run`` 才执行导入（幂等：重复导入不新增行；正文先写
  对象存储、读回验 hash 通过才登记）；
- ``--manifest`` 为本地 JSON（``{"documents": [...]}`` 或裸数组）；
- ``--source-set`` 解析 ``knowledge_data/corpus/rag/sources.json`` 的
  命名集合（如 cs-public），来源根目录取 ``--source-root`` 或
  ``DISCIPLINE_SOURCE_ROOT``；流式读取，不一次载入；
- ``--chunker legacy|corpus``：旧口径（默认，兼容）或新分块
  （corpus-norm/2 + corpus-chunk/1 + 字符回退计数；CR2 接 E5 tokenizer）；
- 路径参数来自受信任部署配置；公开 API 不接收任意本机路径；
- 运行需要部署环境变量（含 STATIC_KEY / JWT_SECRET_KEY /
  AI_COURSE_DATABASE_URL，与其他 backend/scripts 一致）。

退出码：0=成功；2=清单校验失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.discipline_knowledge.ingest import (  # noqa: E402
    DisciplineIngestError,
    ingest_document,
    preview_document,
)

REPO_ROOT = BACKEND_ROOT.parent

DEFAULT_CHUNKER_CONFIGS = {
    "legacy": None,
    "corpus": {
        "normalizer": "corpus-norm/2",
        "chunker": "corpus-chunk/1",
        "target_tokens": 320,
        "overlap_tokens": 32,
        "max_tokens": 512,
    },
}


class _HfTokenizerAdapter:
    """HF tokenizer → 分块器接口（.count/.name）；名称进入 chunker 身份。"""

    def __init__(self, tokenizer, name: str) -> None:
        self._tokenizer = tokenizer
        self.name = name

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(str(text or ""), truncation=False))


def _load_chunker_tokenizer() -> "_HfTokenizerAdapter | None":
    """按 CORPUS_EMBEDDING_MODEL_PATH 离线加载真实 tokenizer（失败退回字符回退）。

    字符回退（``CharFallbackTokenizer``，len//4+cjk）会低估英文 token，导致
    分块超过模型 max_length——2026-09-09 cs-textbooks 首批导入实测 142/160
    分片 INPUT_TOO_LONG。真实 tokenizer 让分块与模型口径一致。
    """
    from app.core.config import settings

    path = str(getattr(settings, "CORPUS_EMBEDDING_MODEL_PATH", "") or "")
    if not path:
        return None
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            path, local_files_only=True, trust_remote_code=False)
    except Exception as exc:  # noqa: BLE001 - 加载失败如实告警并退回
        print(f"WARN: tokenizer 离线加载失败，退回字符回退计数：{exc}",
              file=sys.stderr)
        return None
    model_id = str(getattr(settings, "CORPUS_EMBEDDING_MODEL_ID", "") or "tokenizer")
    return _HfTokenizerAdapter(tokenizer, f"{model_id.split('/')[-1]}/1")


def load_manifest(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"SOURCE_UNAVAILABLE: manifest not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"SCHEMA_INVALID: manifest is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if isinstance(data, dict) and isinstance(data.get("documents"), list):
        return data["documents"]
    if isinstance(data, list):
        return data
    print("SCHEMA_INVALID: manifest must contain a 'documents' list", file=sys.stderr)
    raise SystemExit(2)


def load_source_set(name: str, source_root, limit: int):
    """按命名集合流式产出 ingest 记录（{records iterator, specs}）。"""
    from app.services.discipline_knowledge.corpus_source import (
        iter_source_records,
        resolve_source_root,
    )

    rag_sources = REPO_ROOT / "knowledge_data" / "corpus" / "rag" / "sources.json"
    try:
        registry = json.loads(rag_sources.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"SOURCE_UNAVAILABLE: sources.json 不可读：{exc}", file=sys.stderr)
        raise SystemExit(2)
    wanted = (registry.get("sets") or {}).get(name)
    if not wanted:
        print(f"SCHEMA_INVALID: 未知 source-set '{name}'", file=sys.stderr)
        raise SystemExit(2)
    by_file = {s.get("file"): s for s in registry.get("sources", [])}
    root = source_root or resolve_source_root()
    specs = []
    for filename in wanted:
        spec = dict(by_file.get(filename, {}))
        spec.setdefault("file", filename)
        specs.append(spec)
    return specs, root


def stream_source_records(specs, root, limit: int):
    from app.services.discipline_knowledge.corpus_source import (
        iter_source_records,
    )

    yielded = 0
    stats_all: list[dict] = []
    for spec in specs:
        stats: dict = {}
        for record in iter_source_records(spec, source_root=root, stats=stats):
            if yielded >= limit:
                break
            yielded += 1
            yield record
        stats_all.append(stats)
        if yielded >= limit:
            break
    yield ("__stats__", stats_all)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="学科语料导入（幂等，CR1）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--manifest", type=Path, help="已登记来源清单 JSON 路径")
    group.add_argument("--source-set", help="命名来源集合（如 cs-public）")
    parser.add_argument("--source-root", type=Path, default=None,
                        help="JSONL 来源根目录（默认 DISCIPLINE_SOURCE_ROOT）")
    parser.add_argument("--chunker", choices=["legacy", "corpus"], default="legacy",
                        help="分块口径（默认 legacy 兼容；corpus 走新分块）")
    parser.add_argument("--limit-docs", type=int, default=100, help="最多处理文档数（默认 100）")
    parser.add_argument("--dry-run", action="store_true", help="只验证并列出范围，不写库")
    args = parser.parse_args(argv)

    chunker_config = DEFAULT_CHUNKER_CONFIGS[args.chunker]
    if chunker_config is not None:
        # 分块口径与 embedding 模型一致：有模型目录时注入真实 tokenizer，
        # 否则保持字符回退（名称进身份，两种口径的块不混用）。
        chunker_config = dict(chunker_config)
        tokenizer = _load_chunker_tokenizer()
        if tokenizer is not None:
            chunker_config["tokenizer"] = tokenizer
    if args.manifest is not None:
        documents = load_manifest(args.manifest)[: max(0, args.limit_docs)]
        source_stats: list[dict] | None = None
    else:
        specs, root = load_source_set(args.source_set, args.source_root,
                                      max(0, args.limit_docs))
        streamed = stream_source_records(specs, root, max(0, args.limit_docs))
        documents = []
        source_stats = []
        for item in streamed:
            if isinstance(item, tuple) and item[0] == "__stats__":
                source_stats = item[1]
            else:
                documents.append(item)

    if args.dry_run:
        per_source: dict[str, int] = {}
        total_chunks = 0
        total_tokens = 0
        problems: list[dict] = []
        for index, record in enumerate(documents):
            try:
                preview = preview_document(record, chunker_config)
            except DisciplineIngestError as exc:
                problems.append({"index": index, "error": str(exc)[:300]})
                continue
            per_source[preview["source_kind"]] = per_source.get(preview["source_kind"], 0) + 1
            total_chunks += len(preview["chunks"])
            total_tokens += preview["token_estimate"]
        print(json.dumps({
            "dry_run": True,
            "manifest": str(args.manifest) if args.manifest else None,
            "source_set": args.source_set,
            "chunker": args.chunker,
            "documents_seen": len(documents),
            "valid_documents": sum(per_source.values()),
            "invalid_documents": len(problems),
            "per_source": per_source,
            "estimated_chunks": total_chunks,
            "estimated_tokens": total_tokens,
            "source_stats": source_stats,
            "problems": problems,
        }, ensure_ascii=False, indent=2))
        return 2 if problems else 0

    from app.models.database import session_factory
    from app.services.discipline_knowledge.corpus_text import CorpusTextError

    imported = 0
    reused = 0
    problems = []
    with session_factory() as session:
        for index, record in enumerate(documents):
            try:
                result = ingest_document(session, record,
                                         chunker_config=chunker_config)
            except (DisciplineIngestError, CorpusTextError) as exc:
                problems.append({"index": index, "error": str(exc)[:300]})
                continue
            if result["created"]:
                imported += 1
            else:
                reused += 1
    print(json.dumps({
        "dry_run": False,
        "manifest": str(args.manifest) if args.manifest else None,
        "source_set": args.source_set,
        "chunker": args.chunker,
        "documents_seen": len(documents),
        "imported": imported,
        "reused_idempotent": reused,
        "invalid_documents": len(problems),
        "source_stats": source_stats,
        "problems": problems,
    }, ensure_ascii=False, indent=2))
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
