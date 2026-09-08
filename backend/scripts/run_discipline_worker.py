"""学科构建独立 Worker 进程（DK4 + CR2 corpus_rag 管线 + CR3 索引接线）。

默认消费 ``corpus_rag`` 管线（``--pipeline corpus_rag``）；旧
``legacy_extraction`` 任务不再默认认领，需显式
``--pipeline legacy_extraction``：

    python backend/scripts/run_discipline_worker.py --once
    python backend/scripts/run_discipline_worker.py --max-items 50 --autostart
    python backend/scripts/run_discipline_worker.py --pipeline legacy_extraction --once

- corpus 构建经 ``discipline_knowledge.builds.create_corpus_build`` 创建；
  embed 分片按批读原文、调 loopback embedding 服务（或本地模型直调）、
  写入向量缓存并在短事务内提交；取消/旧 owner 产物写入拒绝；
- release 经 ``manage_corpus_index.py``（或服务）创建并回填 fts/validate
  单件后，worker 认领执行 FTS 构建与索引验收（CR3 接线）；
- 预算到顶暂停（可恢复），不伪成功。
- 租约默认 180 秒；推理在事务外执行，推理后用独立短连接续租一次，
  失败即放弃写入（不断点续跑语义由重认领保证）。

运行需要部署环境变量（含 STATIC_KEY / JWT_SECRET_KEY /
AI_COURSE_DATABASE_URL，与其他 backend/scripts 一致）。
退出码：0=处理/空闲/预算暂停；1=工作项崩溃已释放；2=参数或构建错误。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logger = logging.getLogger("discipline_worker")


def load_scope_texts(session, scope: dict) -> dict[str, str]:
    """按构建 scope 重建 chunk_id → 原文映射（与 ingest 同一口径 recompute）。"""
    from app.services.discipline_knowledge.identity import (
        chunk_id_for,
        chunk_spans,
        content_hash_for,
        normalize_text,
    )
    from app.services.discipline_knowledge.ingest import (
        ingest_document,
        preview_document,
    )

    manifest_path = (scope or {}).get("manifest_path")
    if not manifest_path:
        return {}
    try:
        data = json.loads(Path(str(manifest_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("构建 manifest 不可读（%s），verify 阶段将报 TEXT_UNAVAILABLE", exc)
        return {}
    documents = data.get("documents") if isinstance(data, dict) else data
    texts: dict[str, str] = {}
    for record in documents or []:
        preview = preview_document(record)
        ingest_document(session, record)  # 幂等，确保版本行存在
        normalized = normalize_text(record.get("text") or "",
                                    preview["normalizer_version"])
        for chunk_no, start, end, piece in chunk_spans(normalized):
            content_hash = content_hash_for(piece)
            locator = f"p{chunk_no}:{start}-{end}"
            texts[chunk_id_for(preview["version_id"], preview["chunker_version"],
                               locator, content_hash)] = piece
    return texts


def process_one(session_factory, worker_id: str, lease_seconds: int,
                pipeline: str = "corpus_rag", embed_client=None) -> str:
    """认领并执行一个工作项。返回 idle|done|failed|paused|deferred。"""
    from app.core.time_utils import utcnow_aware
    from app.services.discipline_knowledge import builds as build_svc
    from app.services.discipline_knowledge import work_items as item_svc
    from app.services.task_service import TaskService

    now = utcnow_aware()
    with session_factory() as session:
        build_svc_reaped = item_svc.reap_expired_leases(session, now)
        if build_svc_reaped["requeued"] or build_svc_reaped["cancelled"]:
            logger.info("回收过期租约：%s", build_svc_reaped)
    if pipeline == "corpus_rag":
        return _process_one_corpus(session_factory, worker_id, lease_seconds,
                                   embed_client)
    with session_factory() as session:
        claimed = item_svc.claim_item(session, worker_id, utcnow_aware(),
                                      lease_seconds,
                                      pipeline_kind="legacy_extraction")
    if claimed is None:
        return "idle"

    with session_factory() as session:
        build = build_svc.get_build(session, claimed["build_id"])
    budget = build["budget"]
    max_chunks = int(budget.get("max_chunks") or 0)
    done_count = int(build["items_by_status"].get("succeeded", 0))
    role = item_svc.STAGE_ROLE.get(claimed["stage"], "?")

    def _release_to_pending(error_code: str) -> str:
        with session_factory() as session:
            status = item_svc.fail_item(
                session, claimed["item_id"], claimed["lease_token"],
                error_code, retryable=True,
                max_retries=int(budget.get("retries") or 0))
        if error_code == "BUDGET_EXCEEDED" and status == "pending":
            return "paused"
        return "failed"

    if max_chunks > 0 and done_count >= max_chunks:
        logger.info("构建 %s 达到 max_chunks=%s，暂停（可恢复）",
                    claimed["build_id"], max_chunks)
        return _release_to_pending("BUDGET_EXCEEDED")

    with session_factory() as session:
        ok = build_svc.reserve_budget(session, claimed["build_id"], role, 0, 0)
    if not ok:
        logger.info("构建 %s 角色 %s 预算不足，暂停（可恢复）",
                    claimed["build_id"], role)
        return _release_to_pending("BUDGET_EXCEEDED")

    try:
        with session_factory() as session:
            build = build_svc.get_build(session, claimed["build_id"])
            texts = load_scope_texts(session, dict(build.get("scope") or {}))
        with session_factory() as session:
            summary = item_svc.run_item(session, claimed, texts)
        result_ref = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        with session_factory() as session:
            committed = item_svc.complete_item(
                session, claimed["item_id"], claimed["lease_token"], result_ref)
            build_svc.settle_budget(session, claimed["build_id"], role, 0, 0, 0, 0)
            try:
                view = build_svc.get_build(session, claimed["build_id"])
                total = max(1, view["items_total"])
                done = view["items_by_status"].get("succeeded", 0)
                if view["task_id"]:
                    TaskService().mark_progress(
                        session, view["task_id"],
                        progress=min(99, done * 100 // total),
                        stage=claimed["stage"],
                        message=f"{claimed['stage']} {claimed['chunk_id'][:16]}",
                    )
            except Exception:  # noqa: BLE001 - 进度投影失败不影响产物提交
                logger.exception("任务进度投影失败（产物已提交）")
        return "done" if committed else "failed"
    except item_svc.DisciplineWorkError as exc:
        logger.info("工作项 %s 失败：%s", claimed["item_id"], exc)
        with session_factory() as session:
            item_svc.fail_item(session, claimed["item_id"], claimed["lease_token"],
                               exc.error_code, retryable=exc.retryable,
                               max_retries=int(budget.get("retries") or 0))
            build_svc.settle_budget(session, claimed["build_id"], role, 0, 0, 0, 0)
        return "deferred" if exc.error_code == "STAGE_DEFERRED" else "failed"
    except Exception:  # noqa: BLE001 - 未知崩溃必须释放租约
        logger.exception("工作项 %s 崩溃，已释放回 pending", claimed["item_id"])
        with session_factory() as session:
            item_svc.fail_item(session, claimed["item_id"], claimed["lease_token"],
                               "WORKER_CRASH", retryable=True,
                               max_retries=int(budget.get("retries") or 0))
        return "failed"


def _process_one_corpus(session_factory, worker_id: str, lease_seconds: int,
                        embed_client=None) -> str:
    """corpus_rag 管线：只认领 embed 分片，预算按向量化口径检查。"""
    from app.core.time_utils import utcnow_aware
    from app.services.discipline_knowledge import builds as build_svc
    from app.services.discipline_knowledge import work_items as item_svc

    with session_factory() as session:
        claimed = item_svc.claim_item(session, worker_id, utcnow_aware(),
                                      lease_seconds,
                                      pipeline_kind="corpus_rag",
                                      stages=["embed", "fts", "validate"])
    if claimed is None:
        return "idle"
    with session_factory() as session:
        build = build_svc.get_build(session, claimed["build_id"])
    budget = build["budget"]
    retries = int(budget.get("retries") or 0)

    def _pause(error_code: str) -> str:
        """预算暂停：以 fail_item 实际落库状态为准，不把失配/失败伪装成 paused。"""
        with session_factory() as session:
            status = item_svc.fail_item(
                session, claimed["item_id"], claimed["lease_token"],
                error_code, retryable=True, max_retries=retries)
        return "paused" if status == "pending" else "failed"

    # -- 预算门（仅 embed 分片；到顶暂停可恢复，不伪成功） --
    if claimed["stage"] == "embed":
        with session_factory() as session:
            embedded = build_svc.embedded_chunks(session, claimed["build_id"])
        max_chunks = int(budget.get("max_chunks") or 0)
        if max_chunks > 0 and len(embedded) >= max_chunks:
            logger.info("构建 %s 唯一已向量化片段达 max_chunks=%s，暂停",
                        claimed["build_id"], max_chunks)
            return _pause("BUDGET_EXCEEDED")
    max_time = int(budget.get("max_time_seconds") or 0)
    if max_time > 0:
        # SQLite 读回的 datetime 是 naive，PG 是 aware：统一转 aware 再比较，
        # 否则 SQLite 部署会在预算门直接 TypeError（2026-09-08 补测发现）。
        from app.core.time_utils import to_aware, utcnow_aware as _now

        with session_factory() as session:
            from sqlmodel import select as _select

            from app.models.discipline_knowledge_model import (
                DisciplineBuild as _Build,
            )

            row = session.exec(_select(_Build).where(
                _Build.build_id == claimed["build_id"])).first()
            started = row.started_at if row is not None else None
        if started is not None and (
                _now() - to_aware(started)).total_seconds() > max_time:
            logger.info("构建 %s 超 max_time_seconds=%s，暂停",
                        claimed["build_id"], max_time)
            return _pause("BUDGET_EXCEEDED")
    max_disk = int(budget.get("max_disk_bytes") or 0)
    if max_disk > 0:
        batch_len = len(_batch_chunk_ids(claimed))
        projected = build_svc.corpus_disk_estimate_bytes(
            int(budget.get("dimension") or 0), len(embedded) + batch_len)
        if projected > max_disk:
            logger.info("构建 %s 磁盘预估超 max_disk_bytes，暂停",
                        claimed["build_id"])
            return _pause("BUDGET_EXCEEDED")

    if embed_client is None and claimed["stage"] == "embed":
        try:
            embed_client = make_embed_client()
        except RuntimeError as exc:
            logger.error("embedding 未配置，无法处理分片：%s", exc)
            return "failed"
    try:
        if claimed["stage"] == "embed":
            summary = item_svc.run_corpus_batch(
                session_factory, claimed, embed_client)
        else:
            # fts / validate：build 级单件经 CR3 服务函数真实执行
            with session_factory() as session:
                summary = item_svc.run_item(session, claimed, {})
                committed = item_svc.complete_item(
                    session, claimed["item_id"], claimed["lease_token"],
                    json.dumps(summary, ensure_ascii=False)[:512])
            summary = {"outcome": "done" if committed else "failed",
                       **summary}
    except item_svc.DisciplineWorkError as exc:
        logger.info("分片 %s 失败：%s", claimed["item_id"], exc)
        if exc.error_code == "BUDGET_EXCEEDED":
            return _pause(exc.error_code)
        with session_factory() as session:
            item_svc.fail_item(session, claimed["item_id"],
                               claimed["lease_token"], exc.error_code,
                               retryable=exc.retryable, max_retries=retries)
        return "deferred" if exc.error_code == "STAGE_DEFERRED" else "failed"
    except Exception:  # noqa: BLE001 - 未知崩溃必须释放租约
        logger.exception("分片 %s 崩溃，已释放回 pending", claimed["item_id"])
        with session_factory() as session:
            item_svc.fail_item(session, claimed["item_id"],
                               claimed["lease_token"], "WORKER_CRASH",
                               retryable=True, max_retries=retries)
        return "failed"
    outcome = summary.get("outcome")
    if outcome == "done":
        return "done"
    # lease-lost / cancelled-race：不碰工作项（token 已不属于我），等回收器处理
    logger.info("分片 %s 未提交（%s），等待租约回收", claimed["item_id"], outcome)
    return "failed"


def _batch_chunk_ids(claimed: dict) -> list[str]:
    try:
        payload = json.loads(claimed.get("payload_ref") or "{}")
    except (TypeError, ValueError):
        return []
    chunk_ids = payload.get("chunk_ids") or []
    return [c for c in chunk_ids if isinstance(c, str)]


def make_embed_client():
    """按部署配置构造推理客户端：URL 优先（loopback 服务），否则本地直调。"""
    from app.core.config import settings
    from app.platform.knowledge.corpus_embedding import (
        E5Provider,
        HttpEmbedClient,
    )

    url = str(getattr(settings, "CORPUS_EMBEDDING_URL", "") or "").strip()
    if url:
        return HttpEmbedClient(base_url=url)
    model_path = str(getattr(settings, "CORPUS_EMBEDDING_MODEL_PATH", "") or "")
    if not model_path:
        raise RuntimeError(
            "CORPUS_EMBEDDING_URL 与 CORPUS_EMBEDDING_MODEL_PATH 均未配置")
    provider = E5Provider.load(model_path, {
        "model_id": settings.CORPUS_EMBEDDING_MODEL_ID,
        "revision": settings.CORPUS_EMBEDDING_MODEL_REVISION,
        "files_hash": settings.CORPUS_EMBEDDING_FILES_HASH,
        "tokenizer": settings.CORPUS_EMBEDDING_TOKENIZER,
        "pooling": "attention-mask mean",
        "prefixes": {"query": "query: ", "passage": "passage: "},
        "dimension": settings.CORPUS_EMBEDDING_DIMENSION,
        "max_length": settings.CORPUS_EMBEDDING_MAX_LENGTH,
    })

    class _LocalAdapter:
        def embed(self, texts, kind="passage"):
            vectors = provider.encode(list(texts), kind)
            counts = [len(provider._tokenizer.encode(
                t, truncation=False)) for t in texts]
            return {"vectors": vectors, "token_counts": counts,
                    "model_fingerprint": provider.model_fingerprint}

    return _LocalAdapter()


def autostart_oldest_queued(session_factory, pipeline: str = "corpus_rag") -> str:
    """启动最早的 queued 构建（按管线过滤）；无则返回 idle。"""
    from sqlmodel import select

    from app.models.discipline_knowledge_model import DisciplineBuild
    from app.services.discipline_knowledge import builds as build_svc

    with session_factory() as session:
        query = (
            select(DisciplineBuild)
            .where(DisciplineBuild.status == "queued")
            .order_by(DisciplineBuild.id)
        )
        if pipeline:
            query = query.where(DisciplineBuild.pipeline_kind == pipeline)
        build = session.exec(query).first()
        if build is None:
            return "idle"
        build_id = build.build_id
    with session_factory() as session:
        try:
            build_svc.start_build(session, build_id)
        except build_svc.DisciplineBuildError as exc:
            logger.warning("构建 %s 启动失败：%s", build_id, exc)
            return "failed"
    logger.info("已启动构建 %s", build_id)
    return "done"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DK4 学科构建 Worker（独立进程）")
    parser.add_argument("--worker-id", default=f"worker-{os.getpid()}",
                        help="工作进程标识（默认 worker-<pid>）")
    parser.add_argument("--once", action="store_true", help="只处理一个工作项后退出")
    parser.add_argument("--max-items", "--max-batches", dest="max_items",
                        type=int, default=0,
                        help="最多处理 N 项（0=直到无项可领；"
                             "--max-batches 为 §7.3 兼容别名）")
    parser.add_argument("--lease-seconds", type=int, default=0,
                        help="租约秒数（0=读 DISCIPLINE_WORKER_LEASE_SECONDS）")
    parser.add_argument("--autostart", action="store_true",
                        help="每次循环先启动最早的 queued 构建")
    parser.add_argument("--pipeline", default="corpus_rag",
                        choices=["corpus_rag", "legacy_extraction"],
                        help="消费管线（默认 corpus_rag，不再默认认领旧抽取任务）")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.core.config import settings
    from app.models.database import session_factory

    lease_seconds = args.lease_seconds or int(settings.DISCIPLINE_WORKER_LEASE_SECONDS)
    embed_client = None
    if args.pipeline == "corpus_rag" and not args.once:
        try:
            embed_client = make_embed_client()
        except RuntimeError as exc:
            logger.warning("embedding 客户端未配置（%s），首个分片时重试", exc)
    handled = 0
    while True:
        if args.autostart:
            autostart_oldest_queued(session_factory, args.pipeline)
        outcome = process_one(session_factory, args.worker_id, lease_seconds,
                              args.pipeline, embed_client)
        if outcome in ("done", "failed", "deferred"):
            handled += 1
        if args.once or outcome == "idle" or outcome == "paused":
            break
        if args.max_items > 0 and handled >= args.max_items:
            break
    logger.info("worker 退出：outcome=%s handled=%s", outcome, handled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
