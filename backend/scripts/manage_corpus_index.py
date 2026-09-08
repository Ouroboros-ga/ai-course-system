"""CR3 语料索引管理 CLI（操作员在获准目标库执行）。

用法（参数名按计划 §7.3）：

    python backend/scripts/manage_corpus_index.py create-build --scope cs-public \
        --model-fingerprint "$CORPUS_MODEL_FP" --dimension 384 --max-chunks 10000
    python backend/scripts/manage_corpus_index.py build --from-build "$CORPUS_BUILD_ID" \
        --model-fingerprint "$CORPUS_MODEL_FP" --dimension 384
    python backend/scripts/manage_corpus_index.py status --release-id "$CORPUS_RELEASE_ID"
    python backend/scripts/manage_corpus_index.py validate --release-id "$CORPUS_RELEASE_ID"
    python backend/scripts/manage_corpus_index.py activate --release-id "$CORPUS_RELEASE_ID" --expected-revision "$CORPUS_HEAD_REVISION"

- ``create-build``：按命名来源集/清单/版本清单登记文档并创建 ``corpus_rag``
  构建（``pipeline_kind=corpus_rag``），规划 embed 分片，输出
  ``build_id / planned_shards / document_version_ids``；向量化由
  ``run_discipline_worker.py --pipeline corpus_rag`` 消费（P0-1：此前无入口）。
- ``build``：组装 release（building）→ 构建 FTS；``--from-build`` 存在且未给
  范围参数时，从该构建的 scope 推导版本清单（避免手抄 version_id）。

- ``build``：按命名来源集（``rag/sources.json`` + ``DISCIPLINE_SOURCE_ROOT``，
  或 ``--manifest``/``--version-ids``）导入 → 组装 release（building）→
  构建 FTS。向量由 corpus 构建经 worker 持续写入，release 组装时按缓存
  解析（无缓存即 FTS-only，不伪装覆盖率）。
- ``validate`` 通过才 ready；``activate`` 经 CAS 切 head。
- ``--model-fingerprint/--dimension`` 必填（未冻结不得发布）。
- 路径参数来自受信任部署配置；运行需要部署环境变量
  （STATIC_KEY / JWT_SECRET_KEY / AI_COURSE_DATABASE_URL）。
- 默认不调用回答模型（verify 的生成问答属 CR6，保持关闭）。

退出码：0=成功；2=参数/范围/校验失败（activate 冲突同样 exit 2，
release_id 与 head 均原样返回，不覆盖）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent


def _resolve_scope_records(args) -> tuple[list[dict], list[dict] | None]:
    """按 --scope/--manifest/--version-ids 产出 ingest 记录（流式复用）。"""
    if args.version_ids:
        return ([{"__version_id__": vid} for vid in args.version_ids], None)
    if args.manifest is not None:
        data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        documents = data.get("documents") if isinstance(data, dict) else data
        return list(documents or []), None
    import importlib.util

    script = (REPO_ROOT / "backend" / "scripts"
              / "import_discipline_corpus.py")
    spec = importlib.util.spec_from_file_location(
        "import_discipline_corpus_cli", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    specs, root = module.load_source_set(args.scope, args.source_root, 0)
    records: list[dict] = []
    stats_all: list[dict] = []
    from app.services.discipline_knowledge.corpus_source import (
        iter_source_records,
    )

    for spec_item in specs:
        stats: dict = {}
        for record in iter_source_records(spec_item, source_root=root,
                                          stats=stats):
            records.append(record)
            if args.max_chunks > 0 and len(records) >= args.max_chunks * 4:
                break
        stats_all.append(stats)
        if args.max_chunks > 0 and len(records) >= args.max_chunks * 4:
            break
    return records, stats_all


def _ingest_scope_versions(args) -> list[str]:
    """按命名来源集/清单/版本清单登记文档，返回 version_id 清单（流式）。"""
    import importlib.util

    from app.models.database import session_factory
    from app.services.discipline_knowledge.corpus_source import iter_source_records
    from app.services.discipline_knowledge.ingest import (
        DisciplineIngestError,
        ingest_document,
    )

    if args.version_ids:
        return list(args.version_ids)
    if args.manifest is not None:
        data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        records = data.get("documents") if isinstance(data, dict) else data
    else:
        script = (REPO_ROOT / "backend" / "scripts"
                  / "import_discipline_corpus.py")
        spec = importlib.util.spec_from_file_location(
            "import_discipline_corpus_cli", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        specs, root = module.load_source_set(args.scope, args.source_root, 0)
        records = (record for spec_item in specs
                   for record in iter_source_records(spec_item,
                                                     source_root=root))

    version_ids: list[str] = []
    chunker_config = {
        "normalizer": "corpus-norm/2",
        "chunker": "corpus-chunk/1",
        "target_tokens": 320,
        "overlap_tokens": 32,
        "max_tokens": 512,
    }
    with session_factory() as session:
        for record in records:
            try:
                result = ingest_document(session, record,
                                         chunker_config=chunker_config)
            except DisciplineIngestError as exc:
                print(f"跳过坏记录：{exc}", file=sys.stderr)
                continue
            if result["version_id"] not in version_ids:
                version_ids.append(result["version_id"])
            if args.limit_docs > 0 and len(version_ids) >= args.limit_docs:
                break
    return version_ids


def _cmd_create_build(args) -> int:
    """创建 corpus_rag 构建（embed 分片由 worker 消费；P0-1）。"""
    from app.models.database import session_factory
    from app.services.discipline_knowledge import builds as build_svc

    version_ids: list[str] = []
    if args.manifest is not None:
        scope = {"manifest_path": str(args.manifest)}
    else:
        version_ids = _ingest_scope_versions(args)
        if not version_ids:
            print("SCHEMA_INVALID: 范围为空（没有可构建的文档）", file=sys.stderr)
            return 2
        scope = {"document_version_ids": version_ids}

    config: dict[str, Any] = {
        "model_fingerprint": args.model_fingerprint,
        "dimension": args.dimension,
    }
    if args.batch_size > 0:
        config["batch_size"] = args.batch_size
    budget: dict[str, Any] = {}
    if args.max_chunks > 0:
        budget["max_chunks"] = args.max_chunks
    if budget:
        config["budget"] = budget

    with session_factory() as session:
        try:
            created = build_svc.create_corpus_build(
                session, owner_user_id=args.owner_user_id, scope=scope,
                config=config)
        except build_svc.DisciplineBuildError as exc:
            print(f"{exc.error_code}: {exc}", file=sys.stderr)
            return 2
        if not version_ids:
            view = build_svc.get_build(session, created["build_id"])
            version_ids = list(
                (view.get("scope") or {}).get("document_version_ids") or [])
    print(json.dumps({
        **created,
        "document_version_ids": version_ids,
        "owner_user_id": args.owner_user_id,
        "max_chunks_budget": int(budget.get("max_chunks") or 0),
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_build(args) -> int:
    from app.models.database import session_factory
    from app.services.discipline_knowledge import corpus_index as index_svc
    from app.services.discipline_knowledge.ingest import (
        DisciplineIngestError,
        ingest_document,
    )

    if not (args.scope or args.manifest or args.version_ids):
        if not args.from_build:
            print("SCHEMA_INVALID: 需要 --scope/--manifest/--version-ids "
                  "或 --from-build", file=sys.stderr)
            return 2
        from app.services.discipline_knowledge import builds as build_svc

        with session_factory() as session:
            view = build_svc.get_build(session, args.from_build)
        args.version_ids = list(
            (view.get("scope") or {}).get("document_version_ids") or [])
        if not args.version_ids:
            print("SCHEMA_INVALID: 构建无 document_version_ids（先 create-build）",
                  file=sys.stderr)
            return 2

    records, source_stats = _resolve_scope_records(args)
    chunker_config = {
        "normalizer": "corpus-norm/2",
        "chunker": "corpus-chunk/1",
        "target_tokens": 320,
        "overlap_tokens": 32,
        "max_tokens": 512,
    }
    with session_factory() as session:
        chunk_ids: list[str] = []
        problems = 0
        if records and isinstance(records[0], dict) and "__version_id__" in records[0]:
            from sqlmodel import select

            from app.models.discipline_knowledge_model import DisciplineChunk

            for marker in records:
                rows = session.exec(
                    select(DisciplineChunk.chunk_id).where(
                        DisciplineChunk.version_id == marker["__version_id__"],
                        DisciplineChunk.chunker_version.like("corpus-chunk/1%"),
                    ).order_by(DisciplineChunk.chunk_no)).all()
                chunk_ids.extend(rows)
        else:
            for record in records:
                try:
                    result = ingest_document(
                        session, record, chunker_config=chunker_config)
                except DisciplineIngestError as exc:
                    problems += 1
                    print(f"跳过坏记录：{exc}", file=sys.stderr)
                    continue
                chunk_ids.extend(result["chunk_ids"])
                if args.max_chunks > 0 and len(chunk_ids) >= args.max_chunks:
                    chunk_ids = chunk_ids[:args.max_chunks]
                    break
        try:
            release = index_svc.create_release(
                session, chunk_ids=chunk_ids,
                model_fingerprint=args.model_fingerprint,
                dimension=args.dimension, build_id=args.from_build or "",
                title=args.title or "")
        except index_svc.CorpusIndexError as exc:
            print(f"{exc.error_code}: {exc}", file=sys.stderr)
            return 2
        try:
            fts = index_svc.build_fts(session, release["release_id"])
        except index_svc.CorpusIndexError as exc:
            print(f"{exc.error_code}: {exc}", file=sys.stderr)
            return 2
    print(json.dumps({
        "release_id": release["release_id"],
        "members": release["members"],
        "embedded": release["embedded"],
        "excluded_withdrawn": release["excluded_withdrawn"],
        "fts": fts,
        "source_stats": source_stats,
        "skipped_records": problems,
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_status(args) -> int:
    from app.models.database import session_factory
    from app.services.discipline_knowledge import builds as build_svc
    from app.services.discipline_knowledge import corpus_index as index_svc

    with session_factory() as session:
        if args.build_id:
            try:
                view = build_svc.get_build(session, args.build_id)
            except build_svc.DisciplineBuildError as exc:
                print(f"{exc.error_code}: {exc}", file=sys.stderr)
                return 2
            print(json.dumps(view, ensure_ascii=False, indent=2))
            return 0
        try:
            if args.release_id:
                view = index_svc.get_release(session, args.release_id)
            else:
                head = index_svc.read_head(session)
                if not head["release_id"]:
                    print(json.dumps({"head": head}, ensure_ascii=False))
                    return 0
                view = index_svc.get_release(session, head["release_id"])
                view["head"] = head
        except index_svc.CorpusIndexError as exc:
            print(f"{exc.error_code}: {exc}", file=sys.stderr)
            return 2
    print(json.dumps(view, ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args) -> int:
    from app.models.database import session_factory
    from app.services.discipline_knowledge import corpus_index as index_svc

    with session_factory() as session:
        try:
            report = index_svc.validate_index(session, args.release_id)
        except index_svc.CorpusIndexError as exc:
            print(f"{exc.error_code}: {exc}", file=sys.stderr)
            return 2
    print(json.dumps({"release_id": args.release_id, **report},
                     ensure_ascii=False, indent=2))
    return 0 if report.get("ready") else 2


def _cmd_activate(args) -> int:
    from app.models.database import session_factory
    from app.services.discipline_knowledge import corpus_index as index_svc

    with session_factory() as session:
        result = index_svc.activate_index(
            session, args.release_id, args.expected_revision)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error_code") else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CR3 语料索引管理")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser(
        "create-build", help="创建 corpus_rag 构建并规划 embed 分片（P0-1）")
    cgroup = create.add_mutually_exclusive_group(required=True)
    cgroup.add_argument("--scope", help="命名来源集（sources.json sets 键）")
    cgroup.add_argument("--manifest", type=Path, help="来源清单 JSON 路径")
    cgroup.add_argument("--version-ids", nargs="+", help="已登记版本 ID 清单")
    create.add_argument("--source-root", type=Path, default=None)
    create.add_argument("--model-fingerprint", required=True)
    create.add_argument("--dimension", type=int, required=True)
    create.add_argument("--batch-size", type=int, default=0,
                        help="embed 分片批大小（0=默认 16）")
    create.add_argument("--max-chunks", type=int, default=0,
                        help="向量化预算上限（0=不限；到顶暂停可恢复）")
    create.add_argument("--limit-docs", type=int, default=0,
                        help="导入文档上限（0=不限）")
    create.add_argument(
        "--owner-user-id", type=int,
        default=int(os.environ.get("DISCIPLINE_BUILD_OWNER_USER_ID") or 1),
        help="任务归属（审计用；create_task 只校验非空，无外键）")
    create.set_defaults(func=_cmd_create_build)

    build = sub.add_parser("build", help="导入并组装 release + 构建 FTS")
    group = build.add_mutually_exclusive_group(required=False)
    group.add_argument("--scope", help="命名来源集（sources.json sets 键）")
    group.add_argument("--manifest", type=Path, help="来源清单 JSON 路径")
    group.add_argument("--version-ids", nargs="+", help="已登记版本 ID 清单")
    build.add_argument("--source-root", type=Path, default=None)
    build.add_argument("--model-fingerprint", required=True)
    build.add_argument("--dimension", type=int, required=True)
    build.add_argument("--max-chunks", type=int, default=0)
    build.add_argument("--from-build", default="",
                       help="关联 corpus 构建（回填其 fts/validate 单件）")
    build.add_argument("--title", default="")
    build.set_defaults(func=_cmd_build)

    status = sub.add_parser("status", help="查看版本/指针/构建状态")
    status.add_argument("--release-id", default="")
    status.add_argument("--build-id", default="",
                        help="查看构建视图（分片进度，§7.3）")
    status.set_defaults(func=_cmd_status)

    validate = sub.add_parser("validate", help="发布前校验")
    validate.add_argument("--release-id", required=True)
    validate.set_defaults(func=_cmd_validate)

    activate = sub.add_parser("activate", help="CAS 激活发布指针")
    activate.add_argument("--release-id", required=True)
    activate.add_argument("--expected-revision", type=int, required=True)
    activate.set_defaults(func=_cmd_activate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
