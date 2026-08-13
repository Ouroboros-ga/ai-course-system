"""Batch media planning, confirmation and course playlist freezing."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlmodel import Session, func, select

from app.core.exceptions import reject_state_conflict, reject_validation_failed
from app.core.time_utils import utcnow_aware
from app.models.course_outline_model import CoursePptMapping, TeachingScriptNode, TeachingScriptVersion
from app.models.media_release_model import (
    MediaBuildBatch,
    MediaBuildBatchStatus,
    MediaGenerationJob,
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaRelease,
    MediaReleaseItem,
    MediaReleaseStatus,
)
from app.services.object_storage import get_object_storage
from app.services.platform_media_preset_service import (
    resolve_avatar_preset,
    resolve_voice_preset,
)
from app.services.tts_provider import TtsSynthesisRequest
from app.services.stage8_provider_runtime import get_stage8_tts_provider


def _script_hash(node: TeachingScriptNode) -> str:
    return node.content_hash or hashlib.sha256((node.content or "").encode("utf-8")).hexdigest()


def _latest_jobs(session: Session, course_id: int) -> dict[int, list[MediaGenerationJob]]:
    rows = session.exec(select(MediaGenerationJob).where(
        MediaGenerationJob.course_id == course_id,
        MediaGenerationJob.job_type == MediaGenerationJobType.TTS,
    ).order_by(MediaGenerationJob.created_at.desc())).all()
    result: dict[int, list[MediaGenerationJob]] = {}
    for row in rows:
        if row.node_id is not None:
            result.setdefault(row.node_id, []).append(row)
    return result


def _latest_release_items(session: Session, course_id: int) -> dict[int, list[MediaReleaseItem]]:
    """Return previous frozen media items by script node for build planning.

    This is deliberately metadata-only: planning must never download media or
    contact a Provider merely to decide what needs rebuilding.
    """
    rows = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
    ).order_by(MediaReleaseItem.updated_at.desc())).all()
    result: dict[int, list[MediaReleaseItem]] = {}
    for row in rows:
        result.setdefault(row.node_id, []).append(row)
    return result


def _server_provider(*, requested_key: str = "", requested_version: str = ""):
    """Resolve the only provider that a media batch is allowed to use.

    Provider choice, speaker and secret configuration are server-owned.  The
    UI may echo the health endpoint's provider identity solely to prevent a
    stale confirmation, but may not use the batch API as a provider selector.
    """
    try:
        provider = get_stage8_tts_provider()
    except Exception as exc:
        reject_validation_failed(str(exc))
    accepted_keys = {provider.provider_key}
    if provider.provider_key == "fake_tts":
        accepted_keys.update({"fake", "fake_tts"})
    elif provider.provider_key == "volcengine_doubao_tts":
        accepted_keys.update({"doubao", "doubao_tts", "volcengine_doubao_tts"})
    if requested_key and requested_key not in accepted_keys:
        reject_validation_failed("当前媒体批次只能使用服务器已配置的 TTS Provider")
    if requested_version and requested_version != provider.provider_version:
        reject_validation_failed("页面语音服务版本已变更，请重新核算批量计划")
    return provider


def _find_cached_job(
    jobs: list[MediaGenerationJob],
    *,
    cache_key: str,
    provider_key: str,
    provider_version: str,
):
    storage = get_object_storage()
    for job in jobs:
        if (
            job.status == MediaGenerationStatus.SUCCEEDED
            and job.input_hash == cache_key
            and job.provider_key == provider_key
            and job.provider_version == provider_version
            and job.output_object_key
            and storage.exists(job.output_object_key)
        ):
            return job
    return None


def enqueue_batch_cue(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    source_tts_job: MediaGenerationJob,
    created_by: int,
) -> tuple[MediaGenerationJob, str]:
    """Create the non-billable per-node cue task after a successful TTS job.

    This is deliberately separate from the paid synthesis job.  The cue worker
    only reads the persisted TTS output and never reconnects to the Provider.
    The job key makes it safe for a worker restart or cache reuse to invoke
    this helper more than once.
    """
    if source_tts_job.node_id is None:
        reject_validation_failed("批量媒体 TTS 任务缺少讲稿节点，无法冻结字幕与数字人时间轴")
    item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.release_id == release_id,
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.node_id == source_tts_job.node_id,
    )).first()
    if item is None:
        reject_state_conflict("批量媒体条目与 TTS 任务不匹配")
    from app.services.media_release_service import media_generation_job_service
    return media_generation_job_service.create_job(
        session,
        course_id=course_id,
        job_type=MediaGenerationJobType.TIMELINE_PUBLISH,
        created_by=created_by,
        provider_key="avatar-cues",
        provider_version="v1",
        node_id=source_tts_job.node_id,
        input_summary="批量媒体字幕与数字人时间轴冻结",
        input_payload={
            "course_id": course_id,
            "release_id": release_id,
            "source_tts_job_id": source_tts_job.job_id,
            "outline_node_id": item.outline_node_id,
        },
        idempotency_key=f"batch-cue:{release_id}:{source_tts_job.node_id}:{source_tts_job.input_hash}",
        media_release_id=release_id,
    )


def project_tts_result_to_batch_item(
    session: Session,
    *,
    job: MediaGenerationJob,
) -> MediaReleaseItem | None:
    """Copy a TTS terminal state into its batch item without running TTS again."""
    if not job.media_release_id or job.node_id is None:
        return None
    item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == job.course_id,
        MediaReleaseItem.release_id == job.media_release_id,
        MediaReleaseItem.node_id == job.node_id,
    )).first()
    if item is None:
        return None
    if job.status == MediaGenerationStatus.SUCCEEDED:
        item.status = "tts_succeeded"
        item.tts_job_id = job.job_id
        # Expose the completed audio to the draft-only preview before Cue
        # freezing finishes.  It remains a draft item, never learner-visible.
        metadata = job.output_metadata or {}
        item.audio_object_key = job.output_object_key
        item.audio_sha256 = str(metadata.get("audio_sha256") or "")
        item.duration_ms = int(metadata.get("duration_ms") or 0)
        item.error_code = ""
        item.error_message_safe = ""
    elif job.status in {MediaGenerationStatus.FAILED, MediaGenerationStatus.CANCELLED}:
        item.status = "failed"
        item.tts_job_id = job.job_id
        item.error_code = job.error_code or "TTS_NOT_SUCCEEDED"
        item.error_message_safe = job.error_message_safe or "TTS 未成功完成"
    else:
        return item
    item.updated_at = utcnow_aware()
    session.add(item)
    refresh_batch_status(session, course_id=job.course_id, release_id=job.media_release_id)
    return item


def project_cue_result_to_batch_item(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    source_tts_job: MediaGenerationJob,
    result: Any | None = None,
    error_code: str = "",
    error_message_safe: str = "",
) -> MediaReleaseItem | None:
    """Mark one frozen subtitle/avatar pair ready (or failed) in its batch."""
    if source_tts_job.node_id is None:
        return None
    item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
        MediaReleaseItem.node_id == source_tts_job.node_id,
    )).first()
    if item is None:
        return None
    item.tts_job_id = source_tts_job.job_id
    if result is None:
        item.status = "failed"
        item.error_code = error_code or "CUE_BUILD_FAILED"
        item.error_message_safe = error_message_safe or "字幕与数字人时间轴冻结失败"
    else:
        item.status = "ready"
        item.audio_object_key = result.audio_object_key
        item.audio_sha256 = result.audio_sha256
        item.duration_ms = result.duration_ms
        item.subtitle_manifest_object_key = result.subtitle_manifest_object_key
        item.avatar_cues_object_key = result.avatar_cues_object_key
        item.error_code = ""
        item.error_message_safe = ""
    item.updated_at = utcnow_aware()
    session.add(item)
    refresh_batch_status(session, course_id=course_id, release_id=release_id)
    return item


def refresh_batch_status(
    session: Session,
    *,
    course_id: int,
    release_id: str,
) -> MediaBuildBatch | None:
    """Project durable node state into the batch's user-facing status."""
    batch = session.exec(select(MediaBuildBatch).where(
        MediaBuildBatch.course_id == course_id,
        MediaBuildBatch.release_id == release_id,
    )).first()
    if batch is None:
        return None
    items = list(session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
    )).all())
    if not items:
        batch.status = MediaBuildBatchStatus.FAILED
        batch.error_code = "BATCH_ITEMS_MISSING"
        batch.error_message_safe = "批量媒体条目缺失"
    elif any(item.status in {"failed", "blocked"} for item in items):
        batch.status = MediaBuildBatchStatus.FAILED
        first = next(item for item in items if item.status in {"failed", "blocked"})
        batch.error_code = first.error_code or "MEDIA_ITEM_FAILED"
        batch.error_message_safe = first.error_message_safe or "存在未成功的知识点媒体"
    elif all(item.status == "ready" for item in items):
        batch.status = MediaBuildBatchStatus.READY
        batch.completed_at = utcnow_aware()
        batch.error_code = ""
        batch.error_message_safe = ""
    else:
        batch.status = MediaBuildBatchStatus.RUNNING
    batch.updated_at = utcnow_aware()
    session.add(batch)
    session.flush()
    return batch


def build_media_plan(session: Session, *, course_id: int, node_ids: list[int] | None = None,
                     provider_key: str = "", provider_version: str = "", voice_id: str = "default",
                     voice_preset_id: str = "", voice_preset_version: str = "",
                     avatar_preset_id: str = "", avatar_preset_version: str = "") -> dict[str, Any]:
    # The browser cannot choose an arbitrary provider voice.  ``default`` is
    # an opaque server-side alias for the configured platform voice; rejecting
    # other values keeps cache/price estimates and actual generation aligned.
    if voice_id and voice_id != "default":
        reject_validation_failed("批量媒体只能使用服务器配置的平台音色")
    stmt = select(TeachingScriptNode).where(TeachingScriptNode.course_id == course_id)
    if node_ids:
        stmt = stmt.where(TeachingScriptNode.id.in_(node_ids))
    nodes = list(session.exec(stmt).all())
    # ``TeachingScriptNode`` stores a durable outline ID but not the teaching
    # tree's display order.  Resolve that order explicitly, rather than
    # sorting opaque IDs lexicographically (for example 1.10 before 1.2).
    from app.models.course_outline_model import CourseOutlineNode
    outline_rows = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.course_id == course_id,
    )).all())
    # Use the same tree pre-order as the learner rail/publication gate. A
    # flat order_index is only unique within a parent and breaks multi-chapter
    # playlist ordering.
    from app.services.unified_learning_service import ordered_outline_nodes
    version_ids = {node.script_version_id for node in nodes}
    script_versions = {
        version.script_version_id: version
        for version in session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.script_version_id.in_(version_ids),
        )).all()
    } if version_ids else {}
    tree_ranks: dict[str, int] = {}
    for version in script_versions.values():
        ordered = ordered_outline_nodes(
            session,
            outline_version_id=version.outline_version_id,
            knowledge_points_only=True,
        )
        tree_ranks.update({node.outline_node_id: rank for rank, node in enumerate(ordered)})
    outline_order = {
        row.outline_node_id: (row.order_index, row.outline_node_id)
        for row in outline_rows
    }
    nodes.sort(key=lambda n: (
        tree_ranks.get(n.outline_node_id, 10**9),
        *outline_order.get(n.outline_node_id, (10**9, n.outline_node_id or "")),
        n.id or 0,
    ))
    if node_ids:
        missing = sorted(set(node_ids) - {int(n.id) for n in nodes if n.id})
        if missing:
            reject_validation_failed(f"讲稿节点不存在或不属于课程: {missing}")
    from app.core.config import settings
    max_nodes = max(1, int(getattr(settings, "MEDIA_BATCH_MAX_NODES", 20) or 20))
    max_chars = max(1, int(getattr(settings, "MEDIA_BATCH_MAX_BILLABLE_CHARS", 10_000) or 10_000))
    provider = _server_provider(requested_key=provider_key, requested_version=provider_version)
    provider_key = provider.provider_key
    provider_version = provider.provider_version
    voice_preset = resolve_voice_preset(
        session,
        preset_id=voice_preset_id,
        version=voice_preset_version,
        active_tts_provider_key=provider_key,
    )
    avatar_preset = resolve_avatar_preset(
        session,
        preset_id=avatar_preset_id,
        version=avatar_preset_version,
    )
    # Calls from the pre-P5.1 single-node/batch API may omit a preset.  Keep
    # their historical ``v1`` cache namespace readable so old immutable audio
    # can be reused without resynthesis.  The media builder always sends the
    # selected preset identity, so new batches use the strict preset-bound key.
    voice_resource_version = (
        f"preset:{voice_preset.preset_id}@{voice_preset.version}"
        if voice_preset_id
        else "v1"
    )
    latest = _latest_jobs(session, course_id)
    prior_items = _latest_release_items(session, course_id)
    items = []
    total_chars = 0
    cache_hits = 0
    for order, node in enumerate(nodes):
        text = node.content or ""
        char_count = len(text)
        total_chars += char_count
        req = TtsSynthesisRequest(script_text=text, voice_id="default", course_id=course_id,
                                  resource_version=voice_resource_version, idempotency_key=f"plan:{node.id}")
        cache_key = provider.cache_key(req)
        cached = _find_cached_job(
            latest.get(int(node.id), []) if node.id else [],
            cache_key=cache_key,
            provider_key=provider_key,
            provider_version=provider_version,
        )
        cache_hit = cached is not None
        cache_hits += int(cache_hit)
        mappings = list(session.exec(select(CoursePptMapping).where(
            CoursePptMapping.course_id == course_id,
            CoursePptMapping.outline_node_id == node.outline_node_id,
            CoursePptMapping.status.in_(["draft", "published"]),
        )).all())
        previous = prior_items.get(int(node.id), []) if node.id else []
        prior_success = any(job.status == MediaGenerationStatus.SUCCEEDED for job in latest.get(int(node.id), [])) if node.id else False
        ready_same_script = any(
            previous_item.status == "ready"
            and previous_item.script_hash == _script_hash(node)
            and previous_item.audio_object_key
            and previous_item.subtitle_manifest_object_key
            and previous_item.avatar_cues_object_key
            for previous_item in previous
        )
        change_reasons: list[str] = []
        if not cache_hit:
            change_reasons.append("讲稿或平台音色参数已变更" if prior_success else "尚未生成音频")
        if cache_hit and not ready_same_script:
            change_reasons.append("字幕与数字人时间轴尚未冻结")
        if not mappings:
            change_reasons.append("PPT 映射缺失")
        items.append({
            "node_id": node.id, "script_node_id": node.script_node_id,
            "outline_node_id": node.outline_node_id, "order_index": order,
            "title": node.outline_node_id, "script_hash": _script_hash(node),
            "char_count": char_count, "cache_hit": cache_hit,
            "needs_tts": not cache_hit, "ppt_mapped": bool(mappings),
            "ready_same_script": ready_same_script,
            "change_reasons": change_reasons,
            "ppt_mapping_snapshot": [{"mapping_id": m.mapping_id, "material_version_id": m.material_version_id,
                                       "page_start": m.page_start, "page_end": m.page_end,
                                       "page_refs": m.page_refs or [], "status": m.status} for m in mappings],
        })
    # Empty node_ids means "default candidates", not "all scripts".  A
    # teacher can still explicitly select any knowledge point in the UI.
    if not node_ids:
        items = [item for item in items if item["change_reasons"]]
        for order, item in enumerate(items):
            item["order_index"] = order
    if len(items) > max_nodes:
        reject_validation_failed(f"单批最多选择 {max_nodes} 个知识点")
    total_chars = sum(item["char_count"] for item in items)
    billable_chars = sum(i["char_count"] for i in items if i["needs_tts"])
    if billable_chars > max_chars:
        reject_validation_failed(f"单批预计计费字符数不能超过 {max_chars}")
    return {
        "course_id": course_id, "provider_key": provider_key, "provider_version": provider_version,
        "voice_id": "default", "voice_resource_version": voice_resource_version,
        "voice_preset": {
            "preset_id": voice_preset.preset_id,
            "version": voice_preset.version,
            "display_name": voice_preset.display_name,
            "provider_key": voice_preset.provider_key,
            "content_hash": voice_preset.content_hash,
        },
        "avatar_preset": {
            "preset_id": avatar_preset.preset_id,
            "version": avatar_preset.version,
            "display_name": avatar_preset.display_name,
            "provider_key": avatar_preset.provider_key,
            "content_hash": avatar_preset.content_hash,
        },
        "max_nodes": max_nodes, "max_chars": max_chars,
        "node_count": len(items), "total_chars": total_chars,
        "cache_hit_count": cache_hits, "billable_chars": billable_chars,
        "items": items, "can_confirm": bool(items),
        "default_node_ids": [item["node_id"] for item in items],
        "blocking_reasons": sorted({
            reason for item in items for reason in item["change_reasons"]
            if reason == "PPT 映射缺失"
        }),
        "can_generate_audio": bool(items),
        "can_freeze_playlist": bool(items) and all(item["ppt_mapped"] for item in items),
    }


def confirm_media_batch(session: Session, *, course_id: int, created_by: int, plan: dict[str, Any],
                        idempotency_key: str, label: str = "") -> tuple[MediaBuildBatch, MediaRelease, list[MediaGenerationJob]]:
    existing = session.exec(select(MediaBuildBatch).where(
        MediaBuildBatch.course_id == course_id, MediaBuildBatch.idempotency_key == idempotency_key,
    )).first()
    if existing:
        release = session.exec(select(MediaRelease).where(MediaRelease.release_id == existing.release_id)).first()
        jobs = list(session.exec(select(MediaGenerationJob).where(MediaGenerationJob.media_release_id == existing.release_id)).all())
        return existing, release, jobs
    if not plan.get("items"):
        reject_validation_failed("至少选择一个有讲稿的知识点")
    latest = _latest_jobs(session, course_id)
    max_version = session.exec(select(func.max(MediaRelease.version_number)).where(MediaRelease.course_id == course_id)).one() or 0
    voice_preset = dict(plan.get("voice_preset") or {})
    avatar_preset = dict(plan.get("avatar_preset") or {})
    if not voice_preset.get("preset_id") or not avatar_preset.get("preset_id"):
        reject_validation_failed("批量媒体计划缺少已解析的平台音色或数字人角色")
    release = MediaRelease(course_id=course_id, version_number=int(max_version) + 1,
                            label=label or "批量媒体草稿", status=MediaReleaseStatus.DRAFT,
                            notes="批量媒体建设草稿",
                            created_by=created_by,
                            release_metadata={"audio_playlist_mode": True, "audio_playlist_schema": "audio-playlist/v1"})
    # Freeze the concrete preset/version selected in this server-recomputed
    # plan.  Do not seed a legacy avatar id here: doing so would make a batch
    # appear bound to a role before its registry snapshot is validated.
    release.voice_preset_id = str(voice_preset["preset_id"])
    release.voice_preset_version = str(voice_preset["version"])
    release.avatar_preset_id = str(avatar_preset["preset_id"])
    release.avatar_preset_version = str(avatar_preset["version"])
    release.release_metadata = {
        **(release.release_metadata or {}),
        "voice_preset": voice_preset,
        "avatar_preset": avatar_preset,
    }
    session.add(release); session.flush()
    batch = MediaBuildBatch(course_id=course_id, release_id=release.release_id, created_by=created_by,
                            status=MediaBuildBatchStatus.CONFIRMED, idempotency_key=idempotency_key,
                            node_ids=[i["node_id"] for i in plan["items"]], node_snapshot=plan["items"],
                            estimate={k: plan.get(k) for k in ("node_count", "total_chars", "cache_hit_count", "billable_chars")},
                             voice_config={"voice_id": "default", "provider_key": plan.get("provider_key"), "provider_version": plan.get("provider_version")},
                             confirmed_at=utcnow_aware())
    batch.voice_preset_id = str(voice_preset["preset_id"])
    batch.voice_preset_version = str(voice_preset["version"])
    batch.avatar_preset_id = str(avatar_preset["preset_id"])
    batch.avatar_preset_version = str(avatar_preset["version"])
    batch.voice_config = {
        **(batch.voice_config or {}),
        "resource_version": plan.get("voice_resource_version"),
    }
    session.add(batch); session.flush()
    release.release_metadata = {
        **(release.release_metadata or {}),
        "media_build_batch_id": batch.batch_id,
    }
    session.add(release)
    jobs = []
    from app.services.media_release_service import media_generation_job_service
    for item in plan["items"]:
        release_item = MediaReleaseItem(release_id=release.release_id, course_id=course_id, node_id=item["node_id"],
                                        outline_node_id=item["outline_node_id"], order_index=item["order_index"],
                                        script_hash=item["script_hash"], status="cached" if item["cache_hit"] else "pending",
                                        ppt_mapping_snapshot={"mappings": item["ppt_mapping_snapshot"]})
        session.add(release_item)
        if item["cache_hit"]:
            request = TtsSynthesisRequest(
                script_text=(session.get(TeachingScriptNode, item["node_id"]).content or ""),
                voice_id="default", course_id=course_id,
                resource_version=str(plan.get("voice_resource_version") or "v1"),
                idempotency_key=f"batch:{batch.batch_id}:{item['node_id']}",
            )
            provider = _server_provider(
                requested_key=str(plan.get("provider_key") or ""),
                requested_version=str(plan.get("provider_version") or ""),
            )
            cached = _find_cached_job(
                latest.get(item["node_id"], []), cache_key=provider.cache_key(request),
                provider_key=provider.provider_key, provider_version=provider.provider_version,
            )
            if cached is None:
                # The plan is a quote, not a capability grant.  If the cache
                # changed before confirmation, create a normal pending job so
                # it is charged only after this explicit confirmation.
                release_item.status = "pending"
                session.add(release_item)
                node = session.get(TeachingScriptNode, item["node_id"])
                job, _ = media_generation_job_service.create_job(session, course_id=course_id, job_type=MediaGenerationJobType.TTS,
                    created_by=created_by, provider_key=plan["provider_key"], provider_version=plan["provider_version"],
                    node_id=item["node_id"], input_summary="批量媒体 TTS", input_payload={"script_node_id": node.script_node_id},
                    idempotency_key=f"batch:{batch.batch_id}:{item['node_id']}", media_release_id=release.release_id)
                jobs.append(job)
                continue
            cached_metadata = dict(cached.output_metadata or {}) if cached else {}
            cached_job, _ = media_generation_job_service.create_job(session, course_id=course_id, job_type=MediaGenerationJobType.TTS,
                created_by=created_by, provider_key=plan["provider_key"], provider_version=plan["provider_version"],
                node_id=item["node_id"], input_summary="批量媒体 TTS（缓存复用）", input_payload={"cache_source_job_id": cached.job_id if cached else None},
                input_hash=cached.input_hash,
                idempotency_key=f"batch:{batch.batch_id}:{item['node_id']}", media_release_id=release.release_id)
            # TaskService has a deliberate pending -> running -> succeeded
            # transition graph.  Cached output skips only the Provider call,
            # never the durable state-transition audit trail.
            media_generation_job_service.mark_running(
                session, course_id=course_id, job_id=cached_job.job_id,
                stage="cache_reuse",
            )
            media_generation_job_service.mark_succeeded(session, course_id=course_id, job_id=cached_job.job_id,
                output_object_key=cached.output_object_key or "", output_metadata={**cached_metadata, "cache_hit": True, "cache_source_job_id": cached.job_id})
            project_tts_result_to_batch_item(session, job=cached_job)
            jobs.append(cached_job)
            continue
        node = session.get(TeachingScriptNode, item["node_id"])
        job, _ = media_generation_job_service.create_job(session, course_id=course_id, job_type=MediaGenerationJobType.TTS,
            created_by=created_by, provider_key=plan["provider_key"], provider_version=plan["provider_version"],
            node_id=item["node_id"], input_summary="批量媒体 TTS", input_payload={"script_node_id": node.script_node_id, "script_updated_at": node.updated_at.isoformat() if node.updated_at else None},
            idempotency_key=f"batch:{batch.batch_id}:{item['node_id']}", media_release_id=release.release_id)
        jobs.append(job)
    session.flush()
    refresh_batch_status(session, course_id=course_id, release_id=release.release_id)
    return batch, release, jobs


def freeze_playlist(session: Session, *, course_id: int, release_id: str) -> dict[str, Any]:
    release = session.exec(select(MediaRelease).where(MediaRelease.course_id == course_id, MediaRelease.release_id == release_id)).first()
    if not release:
        reject_validation_failed("媒体草稿不存在")
    if release.status != MediaReleaseStatus.DRAFT:
        reject_state_conflict("仅未激活的媒体草稿可冻结课程播放清单")
    items = list(session.exec(select(MediaReleaseItem).where(MediaReleaseItem.release_id == release_id)).all())
    if not items:
        reject_state_conflict("媒体草稿没有知识点条目")
    # order_index is only sibling-unique; freeze in canonical outline
    # pre-order, shared with planning/publication/learner playback.
    from app.models.course_outline_model import TeachingScriptNode, TeachingScriptVersion
    from app.services.unified_learning_service import ordered_outline_nodes
    script_node_ids = [item.node_id for item in items]
    script_nodes = list(session.exec(select(TeachingScriptNode).where(
        TeachingScriptNode.id.in_(script_node_ids),
    )).all()) if script_node_ids else []
    version_ids = {node.script_version_id for node in script_nodes}
    versions = list(session.exec(select(TeachingScriptVersion).where(
        TeachingScriptVersion.script_version_id.in_(version_ids),
    )).all()) if version_ids else []
    tree_ranks = {}
    for version in versions:
        tree_ranks.update({node.outline_node_id: rank for rank, node in enumerate(
            ordered_outline_nodes(session, outline_version_id=version.outline_version_id, knowledge_points_only=True)
        )})
    items.sort(key=lambda item: (tree_ranks.get(item.outline_node_id, 10**9), item.order_index, item.id or 0))
    for rank, item in enumerate(items):
        item.order_index = rank
        session.add(item)

    if not release.ppt_manifest_object_key:
        reject_state_conflict("课程 PPT manifest 尚未冻结")
    if release.audio_playlist_object_key:
        storage = get_object_storage()
        if not storage.exists(release.audio_playlist_object_key):
            reject_state_conflict("已冻结的课程播放清单对象不可用，不能静默重新生成")
        return {
            "schema": "audio-playlist/v1",
            "object_key": release.audio_playlist_object_key,
            "sha256": release.audio_playlist_sha256,
            "duration_ms": int((release.release_metadata or {}).get("audio_playlist_duration_ms") or 0),
            "items": [],
        }
    storage = get_object_storage()
    try:
        ppt_manifest = json.loads(storage.get(release.ppt_manifest_object_key).decode("utf-8"))
        primary_pages = {int(page.get("page") or 0) for page in (ppt_manifest.get("pages") or [])}
        deck_pages = {
            str(deck.get("material_version_id")): {int(page.get("page") or 0) for page in (deck.get("pages") or [])}
            for deck in (ppt_manifest.get("decks") or []) if deck.get("material_version_id")
        }
    except Exception:
        reject_state_conflict("课程 PPT manifest 对象不可读取，无法冻结播放清单")
    for item in items:
        if not (item.ppt_mapping_snapshot or {}).get("mappings"):
            item.status = "blocked"
            item.error_code = "PPT_MAPPING_REQUIRED"
            item.error_message_safe = "该知识点尚未完成 PPT 映射"
            continue
        mappings_are_current = True
        for mapping in (item.ppt_mapping_snapshot or {}).get("mappings") or []:
            pages = {int(page) for page in (mapping.get("page_refs") or []) if str(page).isdigit()}
            if not pages:
                pages = set(range(int(mapping.get("page_start") or 1), int(mapping.get("page_end") or 1) + 1))
            material_version_id = str(mapping.get("material_version_id") or "")
            available_pages = deck_pages.get(material_version_id) if material_version_id else primary_pages
            if not available_pages or not pages.issubset(available_pages):
                mappings_are_current = False
                break
        if not mappings_are_current:
            item.status = "blocked"
            item.error_code = "PPT_MAPPING_STALE"
            item.error_message_safe = "冻结的 PPT 映射与当前 PPT 页图不一致"
            continue
        # Cue freezing is a durable non-billable worker task submitted after
        # each successful TTS.  This endpoint must *only* validate/freeze the
        # completed artifacts: clicking it never creates hidden work or calls
        # the Provider again.
        if item.status != "ready":
            # Keep a running item distinguishable from a terminal failure;
            # otherwise merely checking the publish gate would poison a batch
            # and make the normal worker completion path look like a retry.
            if item.status not in {"pending", "tts_succeeded", "cached"}:
                item.status = "pending"
    refresh_batch_status(session, course_id=course_id, release_id=release_id)
    session.flush()
    if any(i.status != "ready" for i in items):
        reject_state_conflict("仍有知识点媒体未成功或 PPT 映射未冻结", details={"items": [{"node_id": i.node_id, "status": i.status, "error_code": i.error_code} for i in items]})
    timeline = []; offset = 0
    for item in items:
        timeline.append({"item_id": item.item_id, "node_id": item.node_id, "outline_node_id": item.outline_node_id, "order_index": item.order_index,
                         "offset_ms": offset, "duration_ms": item.duration_ms, "audio_object_key": item.audio_object_key,
                         "audio_sha256": item.audio_sha256, "subtitle_manifest_object_key": item.subtitle_manifest_object_key,
                         "avatar_cues_object_key": item.avatar_cues_object_key, "ppt_mapping_snapshot": item.ppt_mapping_snapshot})
        offset += item.duration_ms
    manifest = {"schema": "audio-playlist/v1", "course_id": course_id, "release_id": release_id, "duration_ms": offset, "items": timeline}
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest(); key = f"audio-playlist/course{course_id}/{release_id}/playlist-{sha[:16]}.json"
    if not storage.exists(key): storage.put(key, raw, mime_type="application/json")
    release.audio_playlist_object_key = key; release.audio_playlist_sha256 = sha
    release.release_metadata = {**(release.release_metadata or {}), "audio_playlist_schema": "audio-playlist/v1", "audio_playlist_duration_ms": offset}
    session.add(release); session.flush()
    return {"schema": "audio-playlist/v1", "object_key": key, "sha256": sha, "duration_ms": offset, "items": timeline}
