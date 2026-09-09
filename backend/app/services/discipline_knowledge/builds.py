"""DK4 构建批次：创建/启动/取消/重试、增量规划与预算。

- 一个批次映射一条 ``TaskRecord``（``task_type="discipline.build"``，
  ``course_id`` 为空——全局任务不伪造课程归属），细粒度状态只放
  ``discipline_work_items``；
- 同 (stage, fingerprint) 重跑复用结果；新增文档只创建它及关联聚合的
  工作项（``plan_delta`` 幂等创建，返回受影响 chunk 清单）；
- 文档修改/撤回按版本状态处理：撤回版本不再建项、其 pending 项取消，
  零来源内容的排除语义由 DK5 发布侧执行；
- 预算：调用前原子预留、结束按实际结算（含重试消耗）；到顶可恢复，
  不伪成功。费用按选定供应商实际定价配置估算，V1 确定性处理器
  usage 记 0（basis=deterministic），超时无 usage 记 unknown。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.discipline_knowledge_model import (
    DisciplineBuild,
    DisciplineChunk,
    DisciplineDocumentVersion,
    DisciplineWorkItem,
)
from app.models.task_model import IdempotencyKeyRecord
from app.services.discipline_knowledge.identity import sha16
from app.services.discipline_knowledge.ingest import ingest_document
from app.services.discipline_knowledge.work_items import fingerprint_for

TASK_TYPE = "discipline.build"

DEFAULT_STAGES = ["resolve", "verify", "adjudicate"]

SUPPORTED_STAGES = frozenset(DEFAULT_STAGES)

#: 构建管线种类（``discipline_builds.pipeline_kind``）。
PIPELINE_LEGACY = "legacy_extraction"
PIPELINE_CORPUS = "corpus_rag"

#: corpus_rag 管线阶段：embed（按分片批量向量化）→ fts（CR3 建 FTS）→
#: validate（CR3 索引验收）。fts/validate 为 build 级单件，有显式前置依赖。
CORPUS_STAGES = ["embed", "fts", "validate"]

CORPUS_SUPPORTED_STAGES = frozenset(CORPUS_STAGES)

#: 阶段前置依赖（同 build 内）：fts 需全部 embed 终态成功；
#: validate 需 fts 成功。CR2 的 worker 只认领 embed，fts/validate 由 CR3 接线。
STAGE_DEPENDENCIES = {"fts": ["embed"], "validate": ["fts"]}

#: embed 分片默认批量（文档批初始 16，见计划 §3.4）。
CORPUS_DEFAULT_BATCH_SIZE = 16


class DisciplineBuildError(ValueError):
    """携带错误码的构建失败（STAGE_DEFERRED / BUILD_STATE / ...）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code


def _defaults() -> dict[str, Any]:
    try:
        from app.core.config import settings

        return {
            "max_chunks": int(settings.DISCIPLINE_BUILD_MAX_CHUNKS or 0),
            "max_input_tokens": int(settings.DISCIPLINE_BUILD_MAX_INPUT_TOKENS or 0),
            "max_output_tokens": int(settings.DISCIPLINE_BUILD_MAX_OUTPUT_TOKENS or 0),
            "timeout_seconds": int(settings.DISCIPLINE_BUILD_TIMEOUT_SECONDS or 0),
            "retries": int(settings.DISCIPLINE_BUILD_MAX_RETRIES or 0),
        }
    except Exception:  # noqa: BLE001 - 无配置环境回退为显式零预算（调用方覆写）
        return {
            "max_chunks": 0,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "timeout_seconds": 0,
            "retries": 0,
        }


def _corpus_defaults() -> dict[str, Any]:
    """corpus_rag 预算默认：embedding token/片段/时间/磁盘限额。

    不沿用 A/B/C/D 调用预算口径（§2.2-6）：此处 input = embedding 输入
    tokens，output 恒 0；max_chunks 按**唯一已向量化片段数**计，
    不按成功工作项数。
    """
    base = _defaults()
    try:
        from app.core.config import settings

        base.update({
            "max_time_seconds": int(
                getattr(settings, "DISCIPLINE_BUILD_MAX_TIME_SECONDS", 0) or 0),
            "max_disk_bytes": int(
                getattr(settings, "DISCIPLINE_BUILD_MAX_DISK_BYTES", 0) or 0),
        })
    except Exception:  # noqa: BLE001 - 无配置环境回退为显式零预算
        base.update({"max_time_seconds": 0, "max_disk_bytes": 0})
    return base


def _new_build_id() -> str:
    return "dkb_" + uuid.uuid4().hex[:12]


def config_hash_for(
    scope_key: str,
    stages: list[str],
    budget: dict[str, Any],
    versions: dict[str, str],
) -> str:
    """配置指纹：Prompt/模型/schema/ontology/预算任一变化即新指纹，不复用旧结果。"""
    payload = {
        "extractor": "deterministic/1",
        "model": "none-deterministic",
        "schema": "discipline-knowledge/1",
        "ontology": "discipline-ontology/1",
        "normalizer": "norm/1",
        "chunker": "chunk/1",
        "scope": scope_key,
        "stages": sorted(stages),
        "budget": {k: budget.get(k) for k in sorted(budget)},
        "versions": versions,
    }
    return "cfg_" + sha16(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def validate_build_scope(config: dict) -> dict[str, Any]:
    """离线校验构建范围（无库操作；DK8 preflight 复用本函数再叠加运行态检查）。

    Returns:
        ``{source_manifest_valid, error_code?, document_count,
        estimated_chunks, estimated_tokens}``；不做任何变更。
    """
    if not isinstance(config, dict):
        return {"source_manifest_valid": False, "error_code": "SCHEMA_INVALID",
                "document_count": 0, "estimated_chunks": 0, "estimated_tokens": 0}
    from pathlib import Path

    from app.services.discipline_knowledge.ingest import preview_document

    manifest_path = config.get("manifest_path")
    max_chunks = config.get("max_chunks", 0)
    if manifest_path is None:
        return {"source_manifest_valid": False, "error_code": "SCHEMA_INVALID",
                "document_count": 0, "estimated_chunks": 0, "estimated_tokens": 0,
                "detail": "需要 manifest_path（受信任部署配置）或 document_version_ids"}
    path = Path(str(manifest_path))
    if not path.is_file():
        return {"source_manifest_valid": False, "error_code": "SOURCE_UNAVAILABLE",
                "document_count": 0, "estimated_chunks": 0, "estimated_tokens": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"source_manifest_valid": False, "error_code": "SCHEMA_INVALID",
                "document_count": 0, "estimated_chunks": 0, "estimated_tokens": 0}
    documents = data.get("documents") if isinstance(data, dict) else data
    if not isinstance(documents, list) or not documents:
        return {"source_manifest_valid": False, "error_code": "SCHEMA_INVALID",
                "document_count": 0, "estimated_chunks": 0, "estimated_tokens": 0}
    try:
        limit = max(0, int(max_chunks or 0)) or len(documents)
    except (TypeError, ValueError):
        limit = len(documents)
    chunks = 0
    tokens = 0
    for record in documents[:limit]:
        try:
            preview = preview_document(record)
        except Exception:  # noqa: BLE001 - 单条坏记录只影响计数，不中断校验
            return {"source_manifest_valid": False, "error_code": "SCHEMA_INVALID",
                    "document_count": 0, "estimated_chunks": 0, "estimated_tokens": 0}
        chunks += len(preview["chunks"])
        tokens += preview["token_estimate"]
    return {"source_manifest_valid": True, "error_code": "",
            "document_count": min(limit, len(documents)),
            "estimated_chunks": chunks, "estimated_tokens": tokens}


def _load_build(session: Session, build_id: str) -> DisciplineBuild:
    build = session.exec(
        select(DisciplineBuild).where(DisciplineBuild.build_id == build_id)
    ).first()
    if build is None:
        raise DisciplineBuildError("BUILD_NOT_FOUND", f"构建 '{build_id}' 不存在")
    return build


def _build_counters() -> dict[str, Any]:
    return {"reserved": {"input": 0, "output": 0},
            "used": {"input": 0, "output": 0},
            "unknown": 0, "cached": 0, "roles": {}}


def create_build(
    session: Session,
    *,
    owner_user_id: int,
    scope: dict[str, Any],
    stages: Optional[list[str]] = None,
    budget: Optional[dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    pipeline_kind: str = PIPELINE_LEGACY,
    chunker_config: Any = None,
    chunker_version: str = "",
) -> dict[str, Any]:
    """创建有限范围构建：一条 TaskRecord + DisciplineBuild + 初始工作项。

    scope 为 ``{manifest_path}``（受信任清单，worker 按需 ingest 并取文本）
    或 ``{document_version_ids}``（已登记版本，文本走对象存储——DK5 接线，
    DK4 中 verify 阶段会诚实报 TEXT_UNAVAILABLE）。

    ``pipeline_kind`` 仅决定阶段词表与认领过滤（CR2 新增
    ``corpus_rag``；默认 legacy 保持旧行为）。corpus 管线默认走新分块
    （``chunker_config=None`` 即 corpus 默认；显式传参可覆盖）。
    """
    from app.services.task_service import TaskCreateRequest, TaskService

    stages = list(stages or DEFAULT_STAGES)
    allowed = CORPUS_SUPPORTED_STAGES if pipeline_kind == PIPELINE_CORPUS \
        else SUPPORTED_STAGES
    unsupported = [s for s in stages if s not in allowed]
    if unsupported:
        raise DisciplineBuildError(
            "STAGE_DEFERRED",
            f"阶段 {unsupported} 不在管线 {pipeline_kind} 词表内",
        )
    merged = _defaults()
    merged.update(budget or {})
    scope = dict(scope or {})
    manifest_path = scope.get("manifest_path")
    version_ids = list(scope.get("document_version_ids") or [])
    if manifest_path is None and not version_ids:
        raise DisciplineBuildError(
            "SCHEMA_INVALID", "scope 需要 manifest_path 或 document_version_ids"
        )
    scope_key = str(manifest_path or "") or ("versions:" + ",".join(sorted(version_ids)))

    # 幂等键含冻结分块口径：换 chunker_version 是另一个构建，不得复用旧构建。
    key = idempotency_key or (
        "discipline-build:" + sha16(
            scope_key, ",".join(sorted(stages)),
            json.dumps(merged, sort_keys=True),
            str(chunker_version or "")))
    existing_link = session.exec(
        select(IdempotencyKeyRecord).where(
            IdempotencyKeyRecord.user_id == owner_user_id,
            IdempotencyKeyRecord.idempotency_key == key,
        )
    ).first()
    if existing_link is not None:
        from app.models.task_model import TaskRecord as _TaskRecord

        task = session.exec(
            select(_TaskRecord).where(_TaskRecord.task_id == existing_link.task_id)
        ).first()
        if task is not None:
            try:
                payload = json.loads(task.input_payload or "{}")
            except (TypeError, ValueError):
                payload = {}
            if payload.get("build_id"):
                build = session.exec(
                    select(DisciplineBuild).where(
                        DisciplineBuild.build_id == payload["build_id"])
                ).first()
                if build is not None:
                    return {"build_id": build.build_id, "task_id": task.task_id,
                            "created": False, "status": build.status}

    report = validate_build_scope(
        {"manifest_path": manifest_path, "max_chunks": merged.get("max_chunks") or 0}
    ) if manifest_path else {"source_manifest_valid": True, "error_code": ""}
    if not report.get("source_manifest_valid"):
        raise DisciplineBuildError(
            report.get("error_code") or "SOURCE_UNAVAILABLE",
            "构建范围校验失败",
        )

    # manifest 范围：幂等 ingest，保证版本行存在（文本解析见 worker）。
    # corpus 管线默认新分块口径；legacy 保持旧口径（兼容）。
    if pipeline_kind == PIPELINE_CORPUS and chunker_config is None:
        chunker_config = {
            "normalizer": "corpus-norm/2",
            "chunker": "corpus-chunk/1",
            "target_tokens": 320,
            "overlap_tokens": 32,
            "max_tokens": 512,
        }
    ensured_versions: list[str] = []
    ensured_chunks: list[str] = []
    if manifest_path:
        from pathlib import Path

        data = json.loads(Path(str(manifest_path)).read_text(encoding="utf-8"))
        documents = data.get("documents") if isinstance(data, dict) else data
        for record in documents or []:
            result = ingest_document(session, record, chunker_config=chunker_config)
            ensured_versions.append(result["version_id"])
            ensured_chunks.extend(result["chunk_ids"])

    build_id = _new_build_id()
    now = utcnow_aware()
    task_service = TaskService()
    view = task_service.create_task(
        session,
        TaskCreateRequest(
            task_type=TASK_TYPE,
            owner_user_id=owner_user_id,
            course_id=None,
            input_summary=f"学科构建 {build_id}（{len(ensured_versions or version_ids)} 文档）",
            input_payload={"build_id": build_id, "scope_key": scope_key,
                           "stages": stages},
            resource_links=[{"resource_kind": "discipline_build",
                             "resource_id": build_id, "relation": "output"}],
            idempotency_key=key,
        ),
    )
    build = DisciplineBuild(
        build_id=build_id,
        task_id=view.task_id,
        pipeline_kind=pipeline_kind,
        scope_manifest_key=str(manifest_path or ""),
        scope={"manifest_path": str(manifest_path or ""),
               # manifest 范围 ingest 后回填实际版本清单，供分片规划使用
               "document_version_ids": version_ids,
               # 冻结分块口径（可选）：同版本多套分块时只索引这一套
               "chunker_version": str(chunker_version or "")},
        stages=stages,
        extractor_version="deterministic/1",
        model_version="none-deterministic",
        prompt_version="n/a",
        schema_version="discipline-knowledge/1",
        config_hash=config_hash_for(scope_key, stages, merged, versions={}),
        budget=merged,
        counters=_build_counters(),
        status="queued",
        created_at=now,
    )
    session.add(build)
    session.commit()

    if manifest_path and ensured_versions:
        build.scope = {"manifest_path": str(manifest_path or ""),
                       "document_version_ids": ensured_versions,
                       "chunker_version": str(chunker_version or "")}
        session.add(build)
        session.commit()

    planned = 0
    if pipeline_kind == PIPELINE_CORPUS:
        planned = 0  # corpus 分片由 create_corpus_build 规划
    else:
        for version_id in ensured_versions or version_ids:
            planned += len(plan_delta(session, version_id, build_id))
    return {"build_id": build_id, "task_id": view.task_id, "created": True,
            "status": "queued", "planned_chunks": planned,
            "pipeline_kind": pipeline_kind}


def start_build(session: Session, build_id: str) -> dict[str, Any]:
    """queued → running（任务同步 mark_running）。"""
    from app.services.task_service import TaskService

    build = _load_build(session, build_id)
    if build.status != "queued":
        raise DisciplineBuildError(
            "BUILD_STATE", f"构建 {build_id} 状态为 {build.status}，不能启动")
    build.status = "running"
    build.started_at = utcnow_aware()
    session.add(build)
    session.commit()
    if build.task_id:
        TaskService().mark_running(session, build.task_id, stage="build")
    return {"build_id": build_id, "status": "running"}


def get_build(session: Session, build_id: str) -> dict[str, Any]:
    """构建视图：预算计数 + 工作项状态直方图（行查询为真源）。"""
    build = _load_build(session, build_id)
    items = session.exec(
        select(DisciplineWorkItem).where(DisciplineWorkItem.build_id == build_id)
    ).all()
    histogram: dict[str, int] = {}
    by_stage: dict[str, dict[str, int]] = {}
    for item in items:
        histogram[item.status] = histogram.get(item.status, 0) + 1
        stage_hist = by_stage.setdefault(item.stage, {})
        stage_hist[item.status] = stage_hist.get(item.status, 0) + 1
    return {"build_id": build.build_id, "task_id": build.task_id,
            "status": build.status, "stages": list(build.stages or []),
            "pipeline_kind": build.pipeline_kind,
            "model_version": build.model_version,
            "scope": dict(build.scope or {}),
            "scope_manifest_key": build.scope_manifest_key,
            "config_hash": build.config_hash, "budget": dict(build.budget or {}),
            "counters": dict(build.counters or {}),
            "items_total": len(items), "items_by_status": histogram,
            "items_by_stage": by_stage, "error_code": build.error_code}


def cancel_build(
    session: Session, build_id: str, *, reason: str = ""
) -> dict[str, Any]:
    """取消构建：停止新认领，已完成产物保留。

    pending 工作项直接取消；running 的由租约回收器在过期后取消
    （过期前完成的产物保留，cancelled build 永不自动发布由 DK5 保证）。
    """
    from app.services.task_service import TaskService

    build = _load_build(session, build_id)
    if build.status not in ("queued", "running"):
        raise DisciplineBuildError(
            "BUILD_STATE", f"构建 {build_id} 状态为 {build.status}，不能取消")
    pending = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == build_id,
            DisciplineWorkItem.status == "pending",
        )
    ).all()
    now = utcnow_aware()
    for item in pending:
        item.status = "cancelled"
        item.updated_at = now
        session.add(item)
    build.status = "cancelled"
    build.finished_at = now
    session.add(build)
    session.commit()
    task_cancelled = False
    if build.task_id:
        try:
            TaskService().cancel(session, build.task_id,
                                 reason=reason or "学科构建已取消")
            task_cancelled = True
        except Exception:  # noqa: BLE001 - 任务已终态时只记构建取消
            pass
    return {"build_id": build_id, "status": "cancelled",
            "cancelled_items": len(pending), "task_cancelled": task_cancelled}


def retry_build(session: Session, build_id: str) -> dict[str, Any]:
    """重试构建：复用已完成产物，只重置 failed/cancelled 工作项。"""
    from app.services.task_service import TaskService

    build = _load_build(session, build_id)
    if build.status not in ("failed", "cancelled", "partial_success", "queued"):
        raise DisciplineBuildError(
            "BUILD_STATE", f"构建 {build_id} 状态为 {build.status}，不能重试")
    resettable = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == build_id,
            DisciplineWorkItem.status.in_(["failed", "cancelled"]),
        )
    ).all()
    now = utcnow_aware()
    for item in resettable:
        item.status = "pending"
        item.lease_token = ""
        item.lease_until = None
        item.error_code = ""
        item.updated_at = now
        session.add(item)
    build.status = "queued"
    build.finished_at = None
    session.add(build)
    session.commit()
    task_retried = False
    if build.task_id:
        try:
            TaskService().retry(session, build.task_id)
            task_retried = True
        except Exception:  # noqa: BLE001 - 任务已终态外时只重置构建侧
            pass
    return {"build_id": build_id, "status": "queued",
            "reset_items": len(resettable), "task_retried": task_retried}


def plan_delta(
    session: Session, document_version_id: str, build_id: str
) -> list[str]:
    """为单个文档版本规划增量工作项（幂等），返回新增覆盖的 chunk_id 清单。

    - 版本撤回（withdrawn）：不再建项，其 pending 项取消，返回 []；
    - 同 (stage, fingerprint) 已存在即复用，只为缺失的 (chunk, stage) 建项。
    """
    build = _load_build(session, build_id)
    if build.status == "cancelled":
        return []
    version = session.exec(
        select(DisciplineDocumentVersion).where(
            DisciplineDocumentVersion.version_id == document_version_id
        )
    ).first()
    if version is None:
        raise DisciplineBuildError(
            "VERSION_NOT_FOUND", f"文档版本 '{document_version_id}' 不存在")
    chunks = session.exec(
        select(DisciplineChunk)
        .where(DisciplineChunk.version_id == document_version_id)
        .order_by(DisciplineChunk.chunk_no)
    ).all()
    if version.status == "withdrawn":
        now = utcnow_aware()
        for chunk in chunks:
            pending = session.exec(
                select(DisciplineWorkItem).where(
                    DisciplineWorkItem.build_id == build_id,
                    DisciplineWorkItem.chunk_id == chunk.chunk_id,
                    DisciplineWorkItem.status == "pending",
                )
            ).all()
            for item in pending:
                item.status = "cancelled"
                item.updated_at = now
                session.add(item)
        if chunks:
            session.commit()
        return []

    stages = list(build.stages or DEFAULT_STAGES)
    now = utcnow_aware()
    covered: list[str] = []
    for chunk in chunks:
        touched = False
        for stage in stages:
            fingerprint = fingerprint_for(stage, chunk.chunk_id, build.config_hash)
            exists = session.exec(
                select(DisciplineWorkItem).where(
                    DisciplineWorkItem.stage == stage,
                    DisciplineWorkItem.fingerprint == fingerprint,
                )
            ).first()
            if exists is not None:
                touched = True
                continue
            session.add(DisciplineWorkItem(
                item_id="dki_" + uuid.uuid4().hex[:12],
                build_id=build_id,
                chunk_id=chunk.chunk_id,
                stage=stage,
                fingerprint=fingerprint,
                status="pending",
                created_at=now,
                updated_at=now,
            ))
            touched = True
        if touched:
            covered.append(chunk.chunk_id)
    session.commit()
    return covered


# ---------------------------------------------------------------------------
# corpus_rag 管线：创建、分片规划与向量化预算口径
# ---------------------------------------------------------------------------


def create_corpus_build(
    session: Session,
    *,
    owner_user_id: int,
    scope: dict[str, Any],
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """创建语料向量化构建（``pipeline_kind=corpus_rag``）。

    Args:
        scope: ``{manifest_path}`` 或 ``{document_version_ids}``。
        config: ``{model_fingerprint（必填）, dimension（必填）,
          batch_size?, budget?, chunker_config?, stages?}``。
          stages 固定 ``[embed, fts, validate]``（CR2 只执行 embed，
          fts/validate 由 CR3 接线， worker 不认领）。

    Returns:
        ``{build_id, task_id, created, status, planned_chunks,
        planned_shards, model_fingerprint}``。
    """
    from app.services.discipline_knowledge.work_items import fingerprint_for

    config = dict(config or {})
    model_fingerprint = str(config.get("model_fingerprint") or "")
    if not model_fingerprint:
        raise DisciplineBuildError(
            "SCHEMA_INVALID", "config.model_fingerprint 必填（冻结指纹，未冻结不得构建）")
    try:
        dimension = int(config.get("dimension") or 0)
    except (TypeError, ValueError):
        dimension = 0
    if dimension <= 0:
        raise DisciplineBuildError(
            "SCHEMA_INVALID", "config.dimension 必填（须与冻结配置一致）")
    batch_size = max(1, int(config.get("batch_size") or CORPUS_DEFAULT_BATCH_SIZE))
    budget = _corpus_defaults()
    budget.update(config.get("budget") or {})
    budget["dimension"] = dimension
    # 冻结分块口径（可选）：同版本存在多套 chunker_version 块时只索引这一套。
    pinned_chunker = str(config.get("chunker_version") or "").strip()

    created = create_build(
        session,
        owner_user_id=owner_user_id,
        scope=scope,
        stages=list(CORPUS_STAGES),
        budget=budget,
        pipeline_kind=PIPELINE_CORPUS,
        chunker_config=config.get("chunker_config"),
        chunker_version=pinned_chunker,
        idempotency_key=config.get("idempotency_key"),
    )
    if not created["created"]:
        return {**created, "planned_shards": 0,
                "model_fingerprint": model_fingerprint}
    build = _load_build(session, created["build_id"])
    build.model_version = model_fingerprint
    build.config_hash = config_hash_for(
        build.scope_manifest_key or ",".join(sorted(
            (build.scope or {}).get("document_version_ids") or [])),
        CORPUS_STAGES, budget,
        versions={"model_fingerprint": model_fingerprint,
                  "normalizer": "corpus-norm/2", "chunker": "corpus-chunk/1"})
    session.add(build)
    session.commit()

    chunk_ids = _corpus_chunk_ids(session, created["build_id"])
    shards = plan_corpus_shards(
        session, created["build_id"], chunk_ids, batch_size,
        model_fingerprint=model_fingerprint)
    return {**created, "planned_chunks": len(chunk_ids),
            "planned_shards": shards["embed_items"],
            "model_fingerprint": model_fingerprint}


def _corpus_chunk_ids(session: Session, build_id: str) -> list[str]:
    """本构建 scope 内 corpus 口径的 chunk 清单（去重保序）。

    ``create_build`` 在 manifest ingest 后已把实际版本清单回填进
    ``scope.document_version_ids``，此处只读本构建范围，不扫全库。
    """
    build = _load_build(session, build_id)
    scope = dict(build.scope or {})
    version_ids = list(scope.get("document_version_ids") or [])
    # 构建冻结分块口径：同一版本可能同时存在多套 chunker_version 的块
    # （换分块器重导入），只取本构建声明的那一套，避免混块。
    pinned_chunker = str(scope.get("chunker_version") or "")
    seen: list[str] = []
    seen_set: set[str] = set()
    for version_id in version_ids:
        query = select(DisciplineChunk.chunk_id).where(
            DisciplineChunk.version_id == version_id)
        if pinned_chunker:
            query = query.where(
                DisciplineChunk.chunker_version == pinned_chunker)
        else:
            query = query.where(
                DisciplineChunk.chunker_version.like("corpus-chunk/1%"))
        rows = session.exec(query.order_by(DisciplineChunk.chunk_no)).all()
        for chunk_id in rows:
            if chunk_id not in seen_set:
                seen_set.add(chunk_id)
                seen.append(chunk_id)
    return seen


def plan_corpus_shards(
    session: Session,
    build_id: str,
    chunk_ids: list[str],
    batch_size: int,
    *,
    model_fingerprint: str = "",
) -> dict[str, int]:
    """规划 corpus 分片工作项（幂等）：embed shards + fts/validate 单件。

    - embed 项：``unit_kind=shard``，``payload_ref`` 为 chunk 清单 JSON，
      fingerprint 含 build_id（每批次自有身份）；
    - fts/validate：``unit_kind=build`` 单件（``chunk_id=""``），CR2 不执行，
      由 CR3 接线；此处仅占位并表达依赖。
    """
    from app.services.discipline_knowledge.work_items import fingerprint_for

    build = _load_build(session, build_id)
    if build.pipeline_kind != PIPELINE_CORPUS:
        raise DisciplineBuildError(
            "BUILD_STATE", f"构建 {build_id} 非 corpus_rag 管线")
    if build.status == "cancelled":
        return {"embed_items": 0, "build_items": 0}
    batch_size = max(1, int(batch_size or CORPUS_DEFAULT_BATCH_SIZE))
    now = utcnow_aware()
    embed_count = 0
    for index in range(0, len(chunk_ids), batch_size):
        batch = chunk_ids[index:index + batch_size]
        unit_key = f"shard-{index // batch_size:04d}"
        payload = json.dumps({"chunk_ids": batch}, ensure_ascii=False)
        fingerprint = fingerprint_for(
            "embed", unit_key + ":" + ",".join(batch),
            build.config_hash, build_id=build_id)
        exists = session.exec(
            select(DisciplineWorkItem).where(
                DisciplineWorkItem.build_id == build_id,
                DisciplineWorkItem.stage == "embed",
                DisciplineWorkItem.fingerprint == fingerprint,
            )
        ).first()
        if exists is not None:
            continue
        session.add(DisciplineWorkItem(
            item_id="dki_" + uuid.uuid4().hex[:12],
            build_id=build_id,
            chunk_id="",
            stage="embed",
            unit_kind="shard",
            unit_key=unit_key,
            payload_ref=payload[:512],
            fingerprint=fingerprint,
            status="pending",
            created_at=now,
            updated_at=now,
        ))
        embed_count += 1
    build_count = 0
    for stage in ("fts", "validate"):
        fingerprint = fingerprint_for(
            stage, "build-singleton", build.config_hash, build_id=build_id)
        exists = session.exec(
            select(DisciplineWorkItem).where(
                DisciplineWorkItem.build_id == build_id,
                DisciplineWorkItem.stage == stage,
                DisciplineWorkItem.fingerprint == fingerprint,
            )
        ).first()
        if exists is not None:
            continue
        session.add(DisciplineWorkItem(
            item_id="dki_" + uuid.uuid4().hex[:12],
            build_id=build_id,
            chunk_id="",
            stage=stage,
            unit_kind="build",
            unit_key=stage,
            payload_ref="",
            fingerprint=fingerprint,
            status="pending",
            created_at=now,
            updated_at=now,
        ))
        build_count += 1
    session.commit()
    return {"embed_items": embed_count, "build_items": build_count}


def embedded_chunks(session: Session, build_id: str) -> set[str]:
    """本构建已向量化的唯一 chunk 集合（成功 embed 项 result_ref 累加去重）。

    预算 ``max_chunks`` 按此计数，不按成功工作项数（§2.2-6）。
    """
    rows = session.exec(
        select(DisciplineWorkItem).where(
            DisciplineWorkItem.build_id == build_id,
            DisciplineWorkItem.stage == "embed",
            DisciplineWorkItem.status == "succeeded",
        )
    ).all()
    chunks: set[str] = set()
    for row in rows:
        try:
            summary = json.loads(row.result_ref or "{}")
        except (TypeError, ValueError):
            continue
        for chunk_id in summary.get("chunk_ids") or []:
            chunks.add(chunk_id)
    return chunks


def corpus_disk_estimate_bytes(dimension: int, chunk_count: int) -> int:
    """向量本体大小估算 ``N×(4d+8)``（表/HNSW/WAL/备份另计，见 §3.4）。"""
    return max(0, chunk_count) * (4 * max(0, dimension) + 8)


def apply_settle_counters(
    counters: dict[str, Any],
    role: str,
    reserved_input: int,
    reserved_output: int,
    actual_input: int,
    actual_output: int,
    *,
    cached_tokens: int = 0,
    unknown_tokens: int = 0,
) -> dict[str, Any]:
    """纯函数版结算（供批量提交在同一事务内复用，不提交）。"""
    counters = json.loads(json.dumps(counters or _build_counters()))
    counters["reserved"]["input"] = max(
        0, counters["reserved"]["input"] - reserved_input)
    counters["reserved"]["output"] = max(
        0, counters["reserved"]["output"] - reserved_output)
    counters["used"]["input"] += max(0, actual_input)
    counters["used"]["output"] += max(0, actual_output)
    counters["cached"] += max(0, cached_tokens)
    counters["unknown"] += max(0, unknown_tokens)
    role_view = _role_view(counters, role)
    role_view["reserved_in"] = max(0, role_view["reserved_in"] - reserved_input)
    role_view["reserved_out"] = max(0, role_view["reserved_out"] - reserved_output)
    role_view["used_in"] += max(0, actual_input)
    role_view["used_out"] += max(0, actual_output)
    return counters


# ---------------------------------------------------------------------------
# 预算：原子预留与结算
# ---------------------------------------------------------------------------


def _role_view(counters: dict, role: str) -> dict[str, int]:
    roles = counters.setdefault("roles", {})
    return roles.setdefault(role, {"reserved_in": 0, "reserved_out": 0,
                                   "used_in": 0, "used_out": 0, "calls": 0})


def reserve_budget(
    session: Session,
    build_id: str,
    role: str,
    estimate_input: int,
    estimate_output: int,
) -> bool:
    """原子预留：任一上限（总量/角色）会被击穿即拒绝，不记账。"""
    build = _load_build(session, build_id)
    budget = dict(build.budget or {})
    counters = json.loads(json.dumps(build.counters or _build_counters()))
    max_in = int(budget.get("max_input_tokens") or 0)
    max_out = int(budget.get("max_output_tokens") or 0)
    role_budget = (budget.get("role_budgets") or {}).get(role) or {}

    def _over(used: int, reserved: int, est: int, cap: int) -> bool:
        return cap > 0 and used + reserved + est > cap

    if _over(counters["used"]["input"], counters["reserved"]["input"],
             estimate_input, max_in):
        return False
    if _over(counters["used"]["output"], counters["reserved"]["output"],
             estimate_output, max_out):
        return False
    role_view = _role_view(counters, role)
    if _over(role_view["used_in"], role_view["reserved_in"], estimate_input,
             int(role_budget.get("max_input_tokens") or 0)):
        return False
    if _over(role_view["used_out"], role_view["reserved_out"], estimate_output,
             int(role_budget.get("max_output_tokens") or 0)):
        return False
    counters["reserved"]["input"] += estimate_input
    counters["reserved"]["output"] += estimate_output
    role_view["reserved_in"] += estimate_input
    role_view["reserved_out"] += estimate_output
    role_view["calls"] += 1
    build.counters = counters
    session.add(build)
    session.commit()
    return True


def settle_budget(
    session: Session,
    build_id: str,
    role: str,
    reserved_input: int,
    reserved_output: int,
    actual_input: int,
    actual_output: int,
    *,
    cached_tokens: int = 0,
    unknown_tokens: int = 0,
) -> dict[str, Any]:
    """按实际 usage 结算：释放预留、累加已用；无 usage 的超时记 unknown。

    网络超时可能已计费但未返回结果：此时以 unknown_tokens 记录预留额，
    不承诺外部调用 exactly-once。
    """
    build = _load_build(session, build_id)
    build.counters = apply_settle_counters(
        build.counters, role, reserved_input, reserved_output,
        actual_input, actual_output,
        cached_tokens=cached_tokens, unknown_tokens=unknown_tokens)
    session.add(build)
    session.commit()
    return {"build_id": build_id, "counters": dict(build.counters or {})}
