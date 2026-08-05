"""Create immutable, provider-neutral ``avatar-cues/v1`` release assets.

The browser must never consume a provider's raw WebSocket response.  This
service converts the persisted, safe subset of a successful TTS job into two
release-scoped objects:

* ``subtitle-manifest/v1`` for the learner's readable transcript;
* ``avatar-cues/v1`` for a future 2D renderer's mouth activity / visemes.

The two manifests carry the exact audio object key and SHA256.  Therefore a
cue result cannot silently be reused after a script, voice, or audio asset is
changed.  When a provider has no phoneme timings, we intentionally emit only
word/subtitle-derived ``mouth_activity`` and label it as an estimate; it is
not treated as precise lip-sync data.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from app.models.course_build_model import SourceMaterial, SourceMaterialVersion
from app.models.course_outline_model import CoursePptMapping
from app.models.media_release_model import (
    MediaGenerationJob,
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaRelease,
    MediaReleaseStatus,
)
from app.models.media_timeline_model import MediaAsset, StorageBackend
from app.services.object_storage import ObjectStorageProvider, get_object_storage


AVATAR_CUES_SCHEMA = "avatar-cues/v1"
SUBTITLE_MANIFEST_SCHEMA = "subtitle-manifest/v1"
SUPPORTED_VISEMES = ("sil", "a", "e", "i", "o", "u", "fv", "mbp")


class AvatarCueBuildError(RuntimeError):
    """A safe, user-actionable error while freezing a cue asset."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.safe_message = message


@dataclass(frozen=True)
class AvatarCueBuildResult:
    avatar_cues_object_key: str
    subtitle_manifest_object_key: str
    audio_object_key: str
    audio_sha256: str
    duration_ms: int
    cue_count: int
    viseme_count: int
    timing_source: str
    content_hash: str
    warnings: list[str]


def load_avatar_cue_manifest(
    storage: ObjectStorageProvider,
    object_key: str,
) -> dict[str, Any]:
    """Load and minimally validate a persisted ``avatar-cues/v1`` object."""
    try:
        payload = json.loads(storage.get(object_key).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise AvatarCueBuildError("AVATAR_CUES_UNAVAILABLE", "数字人时间轴资产不可读取") from exc
    if payload.get("schema") != AVATAR_CUES_SCHEMA:
        raise AvatarCueBuildError("AVATAR_CUES_SCHEMA_INVALID", "数字人时间轴版本不受支持")
    audio = payload.get("audio")
    if not isinstance(audio, dict) or not audio.get("object_key") or not audio.get("sha256"):
        raise AvatarCueBuildError("AVATAR_CUES_AUDIO_BINDING_INVALID", "数字人时间轴缺少音频绑定")
    if not isinstance(payload.get("mouth_activity"), list) or not isinstance(payload.get("visemes"), list):
        raise AvatarCueBuildError("AVATAR_CUES_SCHEMA_INVALID", "数字人时间轴内容不完整")
    return payload


def build_avatar_cues_from_tts_job(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    tts_job_id: str,
    outline_node_id: Optional[str] = None,
    storage: Optional[ObjectStorageProvider] = None,
) -> AvatarCueBuildResult:
    """Freeze one successful TTS result into a draft media release.

    A single P2 job corresponds to one media audio track.  The source job must
    carry a legacy ``script_nodes.id`` because ``MediaReleaseCue`` still uses
    that durable identity for learner navigation.  The optional modern
    ``outline_node_id`` only selects the teacher-reviewed PPT page mapping and
    is copied into release metadata; it never remains a mutable lookup at
    playback time.
    """
    release = session.exec(select(MediaRelease).where(
        MediaRelease.course_id == course_id,
        MediaRelease.release_id == release_id,
    )).first()
    if release is None:
        raise AvatarCueBuildError("MEDIA_RELEASE_NOT_FOUND", "媒体发布版本不存在")
    if release.status != MediaReleaseStatus.DRAFT:
        raise AvatarCueBuildError("MEDIA_RELEASE_IMMUTABLE", "仅从未激活的媒体草稿可冻结时间轴")

    job = session.exec(select(MediaGenerationJob).where(
        MediaGenerationJob.course_id == course_id,
        MediaGenerationJob.job_id == tts_job_id,
    )).first()
    if job is None:
        raise AvatarCueBuildError("TTS_JOB_NOT_FOUND", "TTS 任务不存在")
    if job.job_type != MediaGenerationJobType.TTS or job.status != MediaGenerationStatus.SUCCEEDED:
        raise AvatarCueBuildError("TTS_JOB_NOT_READY", "仅成功的 TTS 任务可生成数字人时间轴")
    if job.node_id is None:
        raise AvatarCueBuildError("TTS_JOB_NODE_REQUIRED", "TTS 任务必须绑定讲稿节点后才能冻结播放时间轴")
    if job.media_release_id and job.media_release_id != release_id:
        raise AvatarCueBuildError("TTS_JOB_RELEASE_MISMATCH", "TTS 任务不属于该媒体发布版本")

    metadata = dict(job.output_metadata or {})
    audio_object_key = str(job.output_object_key or metadata.get("audio_object_key") or "")
    audio_sha256 = str(metadata.get("audio_sha256") or "")
    duration_ms = _non_negative_int(metadata.get("duration_ms"))
    if not audio_object_key or not audio_sha256 or duration_ms <= 0:
        raise AvatarCueBuildError("TTS_OUTPUT_INCOMPLETE", "TTS 成功记录缺少音频 SHA 或有效时长")
    playlist_mode = bool((release.release_metadata or {}).get("audio_playlist_mode"))
    if release.audio_object_key and release.audio_object_key != audio_object_key and not playlist_mode:
        raise AvatarCueBuildError("RELEASE_AUDIO_MISMATCH", "发布草稿已绑定另一份音频，不能混用时间轴")

    storage = storage or get_object_storage()
    if not storage.exists(audio_object_key):
        raise AvatarCueBuildError("TTS_AUDIO_UNAVAILABLE", "TTS 音频对象不存在，无法冻结时间轴")

    warnings = list(metadata.get("warnings") or [])
    subtitles = _normalise_subtitles(metadata.get("subtitle_segments"), duration_ms, warnings)
    if not subtitles:
        raise AvatarCueBuildError("TTS_SUBTITLES_UNAVAILABLE", "TTS 未返回可用字幕时序，无法冻结学生播放清单")
    word_timings = _normalise_timed_entries(metadata.get("timing_metadata", {}).get("word_timings"), duration_ms)
    phoneme_timings = _normalise_timed_entries(metadata.get("timing_metadata", {}).get("phonemes"), duration_ms)

    timing_metadata = metadata.get("timing_metadata") or {}
    timing_source = str(timing_metadata.get("timing_source") or "subtitle_segments")
    if phoneme_timings:
        precision = "phoneme"
    elif word_timings:
        precision = "word"
        warnings.append("avatar-cues: no phoneme timing; mouth activity follows word timing and is not precise lip-sync")
    else:
        precision = "subtitle"
        warnings.append("avatar-cues: no phoneme or word timing; mouth activity follows subtitle segments and is estimated")

    mapping_snapshot, playback_slides = _freeze_ppt_mapping_snapshot(
        session,
        course_id=course_id,
        outline_node_id=outline_node_id,
    )
    release_cues = _release_cue_rows(
        subtitles,
        node_id=job.node_id,
        audio_object_key=audio_object_key,
        tts_job_id=job.job_id,
        timing_source=timing_source,
        playback_slides=playback_slides,
        outline_node_id=outline_node_id,
        material_version_id=mapping_snapshot.get("material_version_id"),
    )

    mouth_activity = _with_silence(
        word_timings or subtitles,
        duration_ms=duration_ms,
        source="phoneme_timing" if phoneme_timings else ("word_timing" if word_timings else "subtitle_timing"),
    )
    visemes = _build_visemes(phoneme_timings)
    if not visemes:
        warnings.append("avatar-cues: exact viseme timeline unavailable; browser must use speaking/rest fallback")

    audio_binding = {
        "object_key": audio_object_key,
        "sha256": audio_sha256,
        "duration_ms": duration_ms,
        "provider_key": str(metadata.get("provider_key") or job.provider_key or ""),
        "provider_version": str(metadata.get("provider_version") or job.provider_version or ""),
    }
    subtitle_manifest = {
        "schema": SUBTITLE_MANIFEST_SCHEMA,
        "course_id": course_id,
        "release_id": release_id,
        "source_tts_job_id": job.job_id,
        "audio": audio_binding,
        "segments": [
            {
                "node_id": row["node_id"],
                "cue_index": row["cue_index"],
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
                "text": row["subtitle_text"],
                "ppt_page": row["ppt_page"],
                "material_version_id": (row.get("cue_metadata") or {}).get("material_version_id"),
                "script_reference": row["script_reference"],
            }
            for row in release_cues
        ],
        "ppt_mapping_snapshot": mapping_snapshot,
    }
    subtitle_hash = _attach_content_hash(subtitle_manifest)

    avatar_manifest = {
        "schema": AVATAR_CUES_SCHEMA,
        "course_id": course_id,
        "release_id": release_id,
        "source_tts_job_id": job.job_id,
        "audio": audio_binding,
        "timing": {
            "source": timing_source,
            "precision": precision,
            "timing_error_ms": timing_metadata.get("timing_error_ms"),
            "phoneme_count": len(phoneme_timings),
            "word_count": len(word_timings),
        },
        "supported_visemes": list(SUPPORTED_VISEMES),
        "mouth_activity": mouth_activity,
        "visemes": visemes,
        "warnings": _unique_warnings(warnings),
    }
    avatar_hash = _attach_content_hash(avatar_manifest)

    subtitle_key = (
        f"subtitle-manifest/course{course_id}/{release_id}/"
        f"subtitles-{audio_sha256[:16]}-{subtitle_hash[:16]}.json"
    )
    avatar_key = (
        f"avatar-cues/course{course_id}/{release_id}/"
        f"cues-{audio_sha256[:16]}-{avatar_hash[:16]}.json"
    )
    subtitle_bytes = _canonical_json_bytes(subtitle_manifest)
    avatar_bytes = _canonical_json_bytes(avatar_manifest)
    if not storage.exists(subtitle_key):
        storage.put(subtitle_key, subtitle_bytes, mime_type="application/json")
    if not storage.exists(avatar_key):
        storage.put(avatar_key, avatar_bytes, mime_type="application/json")
    _register_asset(
        session,
        storage=storage,
        course_id=course_id,
        object_key=subtitle_key,
        asset_type="subtitle_manifest",
        size_bytes=len(subtitle_bytes),
        content_hash=subtitle_hash,
    )
    _register_asset(
        session,
        storage=storage,
        course_id=course_id,
        object_key=avatar_key,
        asset_type="avatar_cues",
        size_bytes=len(avatar_bytes),
        content_hash=avatar_hash,
    )

    # Keep release cue persistence in the release service so its mutability
    # rule and content fingerprint stay the single source of truth.
    from app.services.media_release_service import media_release_service

    if not playlist_mode:
        media_release_service.freeze_cue_snapshot(
            session,
            course_id=course_id,
            release_id=release_id,
            cue_rows=release_cues,
        )
        release.audio_object_key = audio_object_key
        release.subtitle_manifest_object_key = subtitle_key
        release.avatar_cues_object_key = avatar_key
    release.release_metadata = {
        **(release.release_metadata or {}),
        "audio_sha256": audio_sha256,
        "audio_duration_ms": duration_ms,
        "audio_source_tts_job_id": job.job_id,
        "subtitle_manifest_schema": SUBTITLE_MANIFEST_SCHEMA,
        "subtitle_manifest_sha256": subtitle_hash,
        "avatar_cues_schema": AVATAR_CUES_SCHEMA,
        "avatar_cues_sha256": avatar_hash,
        "avatar_cues_timing_source": timing_source,
        "avatar_cues_precision": precision,
        "ppt_mapping_snapshot": mapping_snapshot,
    }
    session.add(release)
    session.flush()
    return AvatarCueBuildResult(
        avatar_cues_object_key=avatar_key,
        subtitle_manifest_object_key=subtitle_key,
        audio_object_key=audio_object_key,
        audio_sha256=audio_sha256,
        duration_ms=duration_ms,
        cue_count=len(release_cues),
        viseme_count=len(visemes),
        timing_source=timing_source,
        content_hash=avatar_hash,
        warnings=_unique_warnings(warnings),
    )


def _normalise_subtitles(raw: Any, duration_ms: int, warnings: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        start_ms = _non_negative_int(item.get("start_ms", item.get("startTime")))
        end_ms = _non_negative_int(item.get("end_ms", item.get("endTime")))
        if not text or end_ms <= start_ms:
            continue
        if start_ms >= duration_ms:
            warnings.append("avatar-cues: ignored subtitle outside audio duration")
            continue
        if end_ms > duration_ms:
            end_ms = duration_ms
            warnings.append("avatar-cues: clipped subtitle timing to audio duration")
        if end_ms <= start_ms:
            continue
        result.append({
            "index": index,
            "text": text,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "sentence_index": item.get("sentence_index"),
        })
    result.sort(key=lambda item: (item["start_ms"], item["end_ms"], item["index"]))
    return result


def _normalise_timed_entries(raw: Any, duration_ms: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start_ms = _non_negative_int(item.get("start_ms", item.get("startTime", item.get("start"))))
        end_ms = _non_negative_int(item.get("end_ms", item.get("endTime", item.get("end"))))
        if end_ms <= start_ms or start_ms >= duration_ms:
            continue
        result.append({
            "text": str(item.get("text") or item.get("word") or item.get("phoneme") or ""),
            "start_ms": start_ms,
            "end_ms": min(end_ms, duration_ms),
        })
    return sorted((item for item in result if item["end_ms"] > item["start_ms"]), key=lambda item: (item["start_ms"], item["end_ms"]))


def _release_cue_rows(
    subtitles: list[dict[str, Any]],
    *,
    node_id: int,
    audio_object_key: str,
    tts_job_id: str,
    timing_source: str,
    playback_slides: list[dict[str, Any]] | None = None,
    page_refs: list[int] | None = None,
    outline_node_id: Optional[str] = None,
    material_version_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(subtitles)
    # ``playback_slides`` is the release-time flattened sequence.  The legacy
    # page_refs/material_version_id arguments remain for callers that only
    # have a single-deck mapping or an old timeline.
    slides = list(playback_slides or [])
    if not slides and page_refs:
        slides = [
            {"page": page, "material_version_id": material_version_id}
            for page in page_refs
        ]
    for cue_index, segment in enumerate(subtitles):
        ppt_page: Optional[int] = None
        cue_material_version_id = material_version_id
        ppt_timing_source = "unmapped"
        if slides:
            page_position = min((cue_index * len(slides)) // total, len(slides) - 1)
            slide = slides[page_position]
            ppt_page = _non_negative_int(slide.get("page")) or None
            cue_material_version_id = str(
                slide.get("material_version_id") or cue_material_version_id or ""
            ) or None
            ppt_timing_source = "teacher_mapping_single_page" if len(slides) == 1 else "mapping_sequence_estimate"
        rows.append({
            "node_id": node_id,
            "cue_index": cue_index,
            "start_time": segment["start_ms"] / 1000,
            "end_time": segment["end_ms"] / 1000,
            "cue_type": "narration",
            "ppt_page": ppt_page,
            "subtitle_text": segment["text"],
            "script_reference": f"tts_job:{tts_job_id}:subtitle:{segment['index']}",
            "audio_object_key": audio_object_key,
            "video_object_key": None,
            "cue_metadata": {
                "timing_source": timing_source,
                "ppt_timing_source": ppt_timing_source,
                "outline_node_id": outline_node_id,
                "material_version_id": cue_material_version_id,
                "source_tts_job_id": tts_job_id,
                "sentence_index": segment.get("sentence_index"),
            },
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
        })
    return rows


def _freeze_ppt_mapping_snapshot(
    session: Session,
    *,
    course_id: int,
    outline_node_id: Optional[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not outline_node_id:
        return {"status": "unmapped", "outline_node_id": None, "page_refs": [], "playback_slides": []}, []
    mappings = list(session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course_id,
        CoursePptMapping.outline_node_id == outline_node_id,
        CoursePptMapping.status.in_(["draft", "published"]),
    )).all())
    if not mappings:
        return {"status": "unmapped", "outline_node_id": outline_node_id, "page_refs": [], "playback_slides": []}, []

    # Match the release manifest's deck order: primary courseware first, then
    # teacher-upload order. Page order is always ascending inside one deck.
    version_ids = {mapping.material_version_id for mapping in mappings if mapping.material_version_id}
    versions = list(session.exec(select(SourceMaterialVersion).where(
        SourceMaterialVersion.course_id == course_id,
        SourceMaterialVersion.version_id.in_(version_ids or {""}),
    )).all())
    version_by_id = {version.version_id: version for version in versions}
    material_ids = {version.material_id for version in versions}
    materials = list(session.exec(select(SourceMaterial).where(
        SourceMaterial.course_id == course_id,
        SourceMaterial.material_id.in_(material_ids or {""}),
    )).all())
    material_by_id = {material.material_id: material for material in materials}

    def deck_key(mapping: CoursePptMapping) -> tuple[Any, ...]:
        version = version_by_id.get(mapping.material_version_id or "")
        material = material_by_id.get(version.material_id) if version else None
        from app.services.ppt_manifest_service import material_deck_sort_key
        return material_deck_sort_key(
            material,
            version,
            fallback_id=mapping.material_version_id or str(mapping.id or ""),
        )

    mappings.sort(key=deck_key)
    playback_slides: list[dict[str, Any]] = []
    mapping_views: list[dict[str, Any]] = []
    seen_slides: set[tuple[Optional[str], int]] = set()
    for mapping in mappings:
        page_refs = sorted({int(page) for page in (mapping.page_refs or []) if _valid_page(page)})
        if not page_refs:
            page_refs = list(range(max(1, mapping.page_start), max(1, mapping.page_end) + 1))
        mapping_views.append({
            "mapping_id": mapping.mapping_id,
            "material_version_id": mapping.material_version_id,
            "page_refs": page_refs,
            "confidence": mapping.confidence,
            "teacher_locked": mapping.teacher_locked,
            "mapping_status_at_freeze": mapping.status,
        })
        for page in page_refs:
            key = (mapping.material_version_id, page)
            if key in seen_slides:
                continue
            seen_slides.add(key)
            playback_slides.append({
                "material_version_id": mapping.material_version_id,
                "page": page,
                "mapping_id": mapping.mapping_id,
            })

    page_refs = [int(slide["page"]) for slide in playback_slides]
    primary_mapping = mappings[0]
    snapshot = {
        "status": "frozen",
        "mapping_id": primary_mapping.mapping_id,
        "outline_node_id": primary_mapping.outline_node_id,
        # Retain the legacy scalar fields for old readers. New readers use the
        # ordered playback_slides list, which can span multiple PPT decks.
        "material_version_id": primary_mapping.material_version_id,
        "page_refs": page_refs,
        "confidence": min((mapping.confidence for mapping in mappings), default=0.0),
        "teacher_locked": all(mapping.teacher_locked for mapping in mappings),
        "mapping_status_at_freeze": primary_mapping.status,
        "mappings": mapping_views,
        "playback_slides": playback_slides,
    }
    return snapshot, playback_slides


def _with_silence(entries: Iterable[dict[str, Any]], *, duration_ms: int, source: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    cursor = 0
    for entry in entries:
        start_ms = max(cursor, _non_negative_int(entry.get("start_ms")))
        end_ms = min(duration_ms, _non_negative_int(entry.get("end_ms")))
        if end_ms <= start_ms:
            continue
        if start_ms > cursor:
            result.append({"start_ms": cursor, "end_ms": start_ms, "state": "silence", "source": source})
        result.append({"start_ms": start_ms, "end_ms": end_ms, "state": "speaking", "source": source})
        cursor = end_ms
    if cursor < duration_ms:
        result.append({"start_ms": cursor, "end_ms": duration_ms, "state": "silence", "source": source})
    return result


def _build_visemes(phonemes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for phoneme in phonemes:
        viseme = _phoneme_to_viseme(phoneme.get("text", ""))
        if viseme is None:
            continue
        result.append({
            "start_ms": phoneme["start_ms"],
            "end_ms": phoneme["end_ms"],
            "viseme": viseme,
        })
    return result


def _phoneme_to_viseme(value: str) -> Optional[str]:
    token = value.strip().lower().replace(" ", "")
    if not token:
        return None
    if token in {"sil", "sp", "pau", "silence"}:
        return "sil"
    if token.startswith(("m", "b", "p")):
        return "mbp"
    if token.startswith(("f", "v")):
        return "fv"
    if token.startswith(("u", "w", "uw")):
        return "u"
    if token.startswith(("o", "ao", "ow")):
        return "o"
    if token.startswith(("i", "y", "iy")):
        return "i"
    if token.startswith(("e", "eh", "er")):
        return "e"
    return "a"


def _register_asset(
    session: Session,
    *,
    storage: ObjectStorageProvider,
    course_id: int,
    object_key: str,
    asset_type: str,
    size_bytes: int,
    content_hash: str,
) -> None:
    existing = session.exec(select(MediaAsset).where(MediaAsset.object_key == object_key)).first()
    if existing is not None:
        return
    backend = StorageBackend.LOCAL if getattr(storage, "backend_name", "local") == "local" else StorageBackend.OSS
    session.add(MediaAsset(
        course_id=course_id,
        object_key=object_key,
        asset_type=asset_type,
        backend=backend,
        mime_type="application/json",
        size_bytes=size_bytes,
        content_hash=content_hash,
        resource_version=AVATAR_CUES_SCHEMA,
    ))


def _attach_content_hash(payload: dict[str, Any]) -> str:
    content_hash = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    payload["content_sha256"] = content_hash
    return content_hash


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return 0


def _valid_page(value: Any) -> bool:
    try:
        return int(value) >= 1
    except (TypeError, ValueError):
        return False


def _unique_warnings(warnings: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(item)[:500] for item in warnings if str(item).strip()))
