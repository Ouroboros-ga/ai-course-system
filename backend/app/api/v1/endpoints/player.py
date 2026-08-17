"""
分屏视频播放器API接口
提供学生端分屏播放所需的数据接口，包括：
- 播放器初始化数据（课程信息、节点列表、视频URL等）
- 知识点导航数据
- 学习进度保存与恢复
"""

import logging
from typing import Optional, List
from app.core.time_utils import utcnow_aware

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlmodel import Session, select, func
from pydantic import BaseModel, Field
from pathlib import Path

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.course_model import Course, CourseScript, ScriptNode, ScriptNodeType
from app.models.course_outline_model import CourseOutlineNode, CourseOutlineVersion, OutlineLifecycleStatus, OutlineNodeType, TeachingScriptNode, TeachingScriptVersion
from app.models.access_control_model import CourseRole
from app.services.course_build_service import course_release_service
from app.services.unified_learning_service import ordered_outline_nodes
from app.models.video_generation_model import VideoGenerationTask, GenerationStatus
from app.models.progress_model import LearningProgress, LearningStatus, NodeProgress
from app.models.mapping_model import KnowledgePageMap
from app.models.unified_learning_model import StudentLearningProjection, ExposureStatus
from app.core.config import settings
from app.services.course_access_service import CourseAccessContext, course_permission, require_course_permission

router = APIRouter(tags=["分屏播放器"])

logger = logging.getLogger(__name__)


def _learner_outline_nodes(
    nodes: list[CourseOutlineNode],
    *,
    release_id: Optional[str],
    content_status: str = "ready",
) -> list[CourseOutlineNode]:
    """Return the node sequence exposed to a learner player.

    Frozen releases use knowledge points as the only progress-bearing units.
    Draft preview passes ``content_status="preview"`` and keeps the complete
    outline so teachers can inspect hierarchy and auxiliary suggestions.
    """
    if content_status == "preview":
        return list(nodes)
    return [node for node in nodes if node.node_type == OutlineNodeType.KNOWLEDGE_POINT]


def _release_node_durations(
    session: Session,
    *,
    course_id: int,
    release_id: str,
    script_by_outline: dict,
) -> dict[str, float]:
    """Return ``outline_node_id`` -> 期望讲解时长(秒) for a frozen course release.

    时长来源优先级（都来自真实冻结/活跃媒体数据，不估算）：
    1. ``MediaReleaseItem.duration_ms``（发布版本冻结的节点音频时长）；
    2. ``MediaReleaseCue`` 按 script node 聚合的最大 ``end_time``；
    3. 活跃 ``MediaTimelineCue`` 按 script node 聚合的最大 ``end_time``
       （未冻结媒体版本的兜底）。

    无任何时长数据的节点不进入返回字典，调用方保持 timestamp=0，
    仅可通过显式完成达成 COMPLETED（与旧行为一致）。
    """
    from app.models.course_build_model import CourseRelease
    from app.models.media_release_model import MediaReleaseCue, MediaReleaseItem
    from app.models.media_timeline_model import MediaTimelineCue

    durations: dict[str, float] = {}

    def _set(outline_node_id: object, seconds: float) -> None:
        key = str(outline_node_id)
        if key and seconds and seconds > 0:
            durations.setdefault(key, seconds)

    release_row = session.exec(
        select(CourseRelease).where(
            CourseRelease.course_id == course_id,
            CourseRelease.release_id == release_id,
        )
    ).first()
    media_release_id = (
        (release_row.media_snapshot or {}).get("media_release_id")
        if release_row is not None
        else None
    )

    if media_release_id:
        items = session.exec(
            select(MediaReleaseItem).where(
                MediaReleaseItem.course_id == course_id,
                MediaReleaseItem.release_id == media_release_id,
            )
        ).all()
        for item in items:
            _set(item.outline_node_id, (item.duration_ms or 0) / 1000.0)
        cue_durations: dict[int, float] = {}
        cues = session.exec(
            select(MediaReleaseCue).where(
                MediaReleaseCue.course_id == course_id,
                MediaReleaseCue.release_id == media_release_id,
            )
        ).all()
        for cue in cues:
            cue_durations[cue.node_id] = max(
                cue_durations.get(cue.node_id, 0.0), float(cue.end_time or 0.0)
            )
        _apply_script_node_durations(
            durations, cue_durations, script_by_outline, _set
        )

    # 活跃时间轴兜底：冻结数据缺失的节点仍可用真实 cue 时长。
    active_cue_durations: dict[int, float] = {}
    active_cues = session.exec(
        select(MediaTimelineCue).where(
            MediaTimelineCue.course_id == course_id,
            MediaTimelineCue.is_active == True,  # noqa: E712
        )
    ).all()
    for cue in active_cues:
        active_cue_durations[cue.node_id] = max(
            active_cue_durations.get(cue.node_id, 0.0), float(cue.end_time or 0.0)
        )
    _apply_script_node_durations(
        durations, active_cue_durations, script_by_outline, _set
    )
    return durations


def _apply_script_node_durations(
    durations: dict[str, float],
    by_script_node_id: dict[int, float],
    script_by_outline: dict,
    setter,
) -> None:
    """Merge per-script-node durations into the outline-node-id keyed map."""
    outline_by_script_node: dict[int, str] = {}
    for outline_node_id, script_node in script_by_outline.items():
        if script_node is not None and getattr(script_node, "id", None) is not None:
            outline_by_script_node[int(script_node.id)] = str(outline_node_id)
    for script_node_id, seconds in by_script_node_id.items():
        outline_node_id = outline_by_script_node.get(int(script_node_id))
        if outline_node_id is not None:
            setter(outline_node_id, seconds)


class PlayerInitData(BaseModel):
    """播放器初始化数据响应模型"""
    course_id: int
    release_id: Optional[str] = None
    course_title: str
    script_id: int
    total_duration: float = Field(description="总时长(秒)")
    total_nodes: int = Field(description="总节点数")
    nodes: List[dict] = Field(description="脚本节点列表")
    video_base_url: str = Field(description="视频基础URL")
    ppt_pages: Optional[List[dict]] = Field(default=None, description="PPT逐页内容（用于右侧显示）")
    slide_images: Optional[List[dict]] = Field(default=None, description="PPT逐页图片URL列表")
    saved_progress: Optional[dict] = Field(default=None, description="已保存的学习进度")
    # A course can be accessible before its learning artefacts are ready.  That
    # is a normal course state, not a missing HTTP resource.  Keep this in the
    # player payload so clients can render an honest empty state without
    # treating it as a transport failure.
    content_status: str = Field(default="ready", description="学习内容状态：ready、preview 或 unavailable")
    content_message: Optional[str] = Field(default=None, description="学习内容暂不可用时的说明")


class KnowledgePoint(BaseModel):
    """知识点导航项"""
    node_id: int
    chapter_id: Optional[str] = None
    title: str
    timestamp_start: float
    timestamp_end: float
    node_index: int
    is_completed: bool = False


class ProgressSaveRequest(BaseModel):
    """进度保存请求体"""
    course_id: int = Field(..., description="课程ID")
    current_node_id: Optional[int] = Field(None, description="当前节点ID")
    current_timestamp: float = Field(..., description="当前播放时间(秒)")
    current_page: int = Field(1, description="当前PPT页码")
    completed_nodes: List[int] = Field(default=[], description="已完成节点ID列表")
    # 听课时长埋点：本次保存周期内新增的听课秒数（仅 playing 时累计）。
    # 后端累加到 NodeProgress.time_spent，供认知引擎 evidence_confidence 佐证使用。
    # 上限 60 秒，避免后台标签页长时间未保存造成的一次性跳变。
    time_spent_delta: float = Field(default=0.0, ge=0.0, le=60.0, description="本次保存周期新增听课时长(秒)")


def _unavailable_player_data(course: Course, message: str) -> PlayerInitData:
    """Return an explicit, non-fabricated empty learning payload.

    Course membership and the ``course.learn`` permission have already been
    checked by the caller.  This is intentionally used only for a real course
    with no learner-facing content yet; a missing course must remain a 404 and
    an unauthorized request must still fail closed in the access dependency.
    """
    return PlayerInitData(
        course_id=course.id,
        course_title=course.title,
        script_id=0,
        total_duration=0,
        total_nodes=0,
        nodes=[],
        video_base_url="/api/v1/video/stream/",
        ppt_pages=None,
        slide_images=None,
        saved_progress=None,
        content_status="unavailable",
        content_message=message,
    )


def _versioned_player_data(
    session: Session,
    *,
    course: Course,
    user_id: int,
    outline: CourseOutlineVersion,
    script: Optional[TeachingScriptVersion],
    page_mappings_snapshot: Optional[dict] = None,
    content_status: str = "ready",
    content_message: Optional[str] = None,
    release_id: Optional[str] = None,
) -> PlayerInitData:
    """Build learner data from an immutable release or an authorized draft.

    ``script`` is optional for a teacher preview: a teacher can inspect a
    partially prepared outline before the matching lecture draft exists.  No
    synthetic lesson text is created in that case.
    """
    outline_nodes = ordered_outline_nodes(
        session,
        outline_version_id=outline.outline_version_id,
    )
    # The unified learner contract is knowledge-point based.  A frozen release
    # may still contain chapter/section/example/practice-suggestion nodes for
    # authoring and navigation, but those nodes are not learner facts and must
    # not be emitted to the student player (otherwise its index-based UI can
    # diverge from ``learning-context.items`` and the 14-point denominator).
    # Teacher draft preview intentionally keeps the complete outline so authors
    # can inspect hierarchy before publication; legacy direct-publication paths
    # are handled outside this function and retain their historical payload.
    outline_nodes = _learner_outline_nodes(
        outline_nodes,
        release_id=release_id,
        content_status=content_status,
    )
    if release_id or content_status != "preview":
        if not outline_nodes:
            return _unavailable_player_data(
                course,
                "当前发布版本尚未包含可学习的知识点。",
            )
    if not outline_nodes:
        return _unavailable_player_data(
            course,
            "当前版本尚未包含可学习的课程节点。",
        )

    script_nodes = session.exec(
        select(TeachingScriptNode)
        .where(TeachingScriptNode.script_version_id == script.script_version_id)
    ).all() if script else []
    script_by_outline = {item.outline_node_id: item for item in script_nodes}
    mapping_by_outline = {
        item.get("outline_node_id"): item
        for item in (page_mappings_snapshot or {}).get("items", [])
    }
    nodes_data = []
    for index, outline_node in enumerate(outline_nodes):
        script_node = script_by_outline.get(outline_node.outline_node_id)
        mapping = mapping_by_outline.get(outline_node.outline_node_id, {})
        page_range = outline_node.page_range or "1"
        page_start = page_range.split("-")[0]
        page_end = page_range.split("-")[-1]
        nodes_data.append({
            "id": outline_node.outline_node_id,
            "outline_node_id": outline_node.outline_node_id,
            "node_index": index,
            "node_type": outline_node.node_type.value,
            "title": outline_node.title,
            "content": (script_node.content if script_node else "")[:200],
            "chapter_id": outline_node.parent_node_id,
            # Stable knowledge-graph concept id shared across outline versions;
            # the draft-preview bridge uses it to match released playlist items.
            "knowledge_graph_node_id": outline_node.knowledge_graph_node_id,
            "timestamp_start": 0,
            "timestamp_end": 0,
            "duration": 0,
            "page_start": mapping.get("page_start") or (int(page_start) if page_start.isdigit() else 1),
            "page_end": mapping.get("page_end") or (int(page_end) if page_end.isdigit() else 1),
            "is_key_point": outline_node.node_type.value == "knowledge_point",
            "video_url": None,
            "status": "preview" if content_status == "preview" else "published",
        })

    # Released courses: fill per-node play durations from frozen media data so
    # the learner page can derive media_progress ratios (80% threshold rule).
    # Nodes without any media duration stay at 0 and require explicit completion.
    total_duration = 0.0
    if release_id:
        node_durations = _release_node_durations(
            session,
            course_id=course.id,
            release_id=release_id,
            script_by_outline=script_by_outline,
        )
        cursor = 0.0
        for node_data in nodes_data:
            duration = node_durations.get(str(node_data["outline_node_id"]), 0.0)
            if duration > 0:
                node_data["timestamp_start"] = round(cursor, 2)
                cursor += duration
                node_data["timestamp_end"] = round(cursor, 2)
                node_data["duration"] = round(duration, 2)
            else:
                node_data["timestamp_start"] = 0.0
                node_data["timestamp_end"] = 0.0
                node_data["duration"] = 0.0
        total_duration = round(cursor, 2)

    # A released learner page restores its anchor only from the canonical
    # release-scoped projection.  The legacy LearningProgress row is kept for
    # the old direct-publication/teacher-preview path, but must not influence a
    # new release's learner state.
    progress = None
    latest_projection = None
    if release_id:
        latest_projection = session.exec(
            select(StudentLearningProjection)
            .where(
                StudentLearningProjection.student_id == user_id,
                StudentLearningProjection.course_id == course.id,
                StudentLearningProjection.release_id == release_id,
                StudentLearningProjection.last_accessed_at.is_not(None),
            )
            .order_by(StudentLearningProjection.last_accessed_at.desc())
        ).first()
    else:
        progress = session.exec(select(LearningProgress).where(LearningProgress.user_id == user_id, LearningProgress.course_id == course.id)).first()
    completed_nodes: list[str] = []
    if release_id:
        rows = session.exec(select(StudentLearningProjection).where(
            StudentLearningProjection.student_id == user_id,
            StudentLearningProjection.course_id == course.id,
            StudentLearningProjection.release_id == release_id,
            StudentLearningProjection.exposure_status == ExposureStatus.COMPLETED,
        )).all()
        completed_nodes = [row.outline_node_id for row in rows]
    saved_progress = {
        "current_node_id": None,
        "current_node_index": 0,
        "current_timestamp": 0.0,
        "current_page": 1,
        "completion_rate": 0.0,
        "completed_node_ids": completed_nodes,
        "last_accessed_at": None,
    }
    if latest_projection is not None:
        current_index = next((i for i, item in enumerate(nodes_data) if item["outline_node_id"] == latest_projection.outline_node_id), 0)
        saved_progress = {
            "current_node_id": latest_projection.outline_node_id,
            "current_node_index": current_index,
            "current_timestamp": latest_projection.current_timestamp,
            "current_page": latest_projection.current_page,
            "completion_rate": 0.0,
            "last_accessed_at": latest_projection.last_accessed_at.isoformat() if latest_projection.last_accessed_at else None,
            "completed_node_ids": completed_nodes,
        }
    elif progress:
        saved_progress = {
            "current_node_id": progress.current_node_id,
            "current_node_index": progress.current_node_index,
            "current_timestamp": progress.current_timestamp,
            "current_page": progress.current_page,
            "completion_rate": progress.completion_rate,
            "last_accessed_at": progress.last_accessed_at.isoformat() if progress.last_accessed_at else None,
            "completed_node_ids": completed_nodes,
        }
    return PlayerInitData(
        course_id=course.id,
        release_id=release_id,
        course_title=course.title,
        script_id=script.id if script and script.id else 0,
        total_duration=total_duration,
        total_nodes=len(nodes_data),
        nodes=nodes_data,
        video_base_url="/api/v1/video/stream/",
        ppt_pages=None,
        slide_images=None,
        saved_progress=saved_progress,
        content_status=content_status,
        content_message=content_message,
    )


@router.get("/init/{course_id}", response_model=PlayerInitData)
async def get_player_init_data(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.learn")),
):
    """
    获取分屏播放器初始化数据

    返回播放器所需的全部数据：
    - 课程基本信息
    - 脚本节点列表（包含时间戳、页码、知识点ID）
    - 各节点的数字人视频URL
    - 已保存的学习进度（用于断点续播）

    前端收到此数据后即可渲染完整的分屏播放界面
    """
    try:
        user_id = access.user_id

        # 1. 查询课程信息
        course = session.get(Course, course_id)
        if not course:
            raise HTTPException(status_code=404, detail="课程不存在")

        # Staff may preview the latest editable outline before it is released.
        # This selection is deliberately role-scoped: students continue to see
        # only the frozen release / legacy published path below.
        can_preview_draft = access.role in {
            CourseRole.OWNER,
            CourseRole.TEACHER,
            CourseRole.TEACHING_ASSISTANT,
        }
        if can_preview_draft:
            draft_outline = session.exec(
                select(CourseOutlineVersion)
                .where(
                    CourseOutlineVersion.course_id == course_id,
                    CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
                )
                .order_by(CourseOutlineVersion.version.desc())
            ).first()
            if draft_outline is not None:
                draft_script = session.exec(
                    select(TeachingScriptVersion)
                    .where(
                        TeachingScriptVersion.course_id == course_id,
                        TeachingScriptVersion.outline_version_id == draft_outline.outline_version_id,
                        TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.DRAFT,
                    )
                    .order_by(TeachingScriptVersion.version.desc())
                ).first()
                return _versioned_player_data(
                    session,
                    course=course,
                    user_id=user_id,
                    outline=draft_outline,
                    script=draft_script,
                    content_status="preview",
                    release_id=None,
                    content_message="教师预览：正在使用未发布的课程草稿。",
                )

        # 2. P4 path: an active CourseRelease is the sole learner-facing
        # content selector.  Do not select whichever outline/script happened
        # to be published most recently after the course release was made.
        frozen_release = course_release_service.get_active_release(
            session, course_id=course_id,
        )
        if frozen_release is not None:
            frozen_outline = session.exec(
                select(CourseOutlineVersion).where(
                    CourseOutlineVersion.course_id == course_id,
                    CourseOutlineVersion.outline_version_id == frozen_release.outline_version_id,
                )
            ).first()
            frozen_script = session.exec(
                select(TeachingScriptVersion).where(
                    TeachingScriptVersion.course_id == course_id,
                    TeachingScriptVersion.script_version_id == frozen_release.script_version_id,
                )
            ).first()
            if frozen_outline is None or frozen_script is None:
                raise HTTPException(status_code=409, detail="发布版本缺少冻结的课程结构或讲稿")
            return _versioned_player_data(
                session,
                course=course,
                user_id=user_id,
                outline=frozen_outline,
                script=frozen_script,
                page_mappings_snapshot=frozen_release.page_mappings_snapshot,
                release_id=frozen_release.release_id,
            )

        # Legacy direct-publication compatibility path. New courses always
        # take the frozen CourseRelease branch above.
        active_script = session.exec(
            select(CourseScript)
            .where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
            .order_by(CourseScript.version.desc())
        ).first()

        published_outline = session.exec(
            select(CourseOutlineVersion)
            .where(
                CourseOutlineVersion.course_id == course_id,
                CourseOutlineVersion.lifecycle_status == OutlineLifecycleStatus.PUBLISHED,
            )
            .order_by(CourseOutlineVersion.version.desc())
        ).first()

        # New course-build releases use immutable outline/script versions. Keep
        # the legacy CourseScript path for old courses, but prefer the new
        # published content when no legacy script exists.
        published_script = None
        if published_outline:
            published_script = session.exec(
                select(TeachingScriptVersion)
                .where(
                    TeachingScriptVersion.course_id == course_id,
                    TeachingScriptVersion.outline_version_id == published_outline.outline_version_id,
                    TeachingScriptVersion.lifecycle_status == OutlineLifecycleStatus.PUBLISHED,
                )
                .order_by(TeachingScriptVersion.version.desc())
            ).first()

        if published_script or not active_script:
            if not published_outline:
                return _unavailable_player_data(course, "课程内容尚未发布，暂时无法开始学习。")
            if not published_script:
                return _unavailable_player_data(course, "课程讲稿尚未发布，暂时无法开始学习。")
            return _versioned_player_data(
                session,
                course=course,
                user_id=user_id,
                outline=published_outline,
                script=published_script,
                release_id=None,
            )

        # 3. 查询所有脚本节点（按node_index排序）
        nodes = session.exec(
            select(ScriptNode)
            .where(ScriptNode.script_id == active_script.id)
            .order_by(ScriptNode.node_index.asc())
        ).all()

        if not nodes:
            return _unavailable_player_data(course, "课程脚本尚未生成学习节点。")

        # 4. 批量查询各节点的视频生成任务
        node_ids = [node.id for node in nodes]
        video_tasks = {}
        if node_ids:
            tasks = session.exec(
                select(VideoGenerationTask)
                .where(
                    VideoGenerationTask.node_id.in_(node_ids),
                    VideoGenerationTask.status == GenerationStatus.COMPLETED,
                )
            ).all()
            video_tasks = {task.node_id: task for task in tasks}

        # 5. 查询页码映射表（优先使用F5映射引擎的精确数据）
        page_maps = session.exec(
            select(KnowledgePageMap)
            .where(KnowledgePageMap.course_id == course_id)
        ).all()
        page_map_dict = {m.node_id: m for m in page_maps}

        # 6. 构建节点数据列表
        nodes_data = []
        for node in nodes:
            task = video_tasks.get(node.id)
            video_url = None
            if task and task.dh_video_path:
                import os
                filename = os.path.basename(task.dh_video_path)
                video_url = f"/api/v1/video/stream/{filename}"

            # 优先使用KnowledgePageMap的页码（F5映射引擎数据）
            mapping = page_map_dict.get(node.id)
            if mapping:
                page_start = mapping.page_start
                page_end = mapping.page_end
            else:
                page_start = node.page_start
                page_end = node.page_end

            node_dict = {
                "id": node.id,
                "node_index": node.node_index,
                "node_type": node.node_type.value,
                "title": node.title or f"知识点 {node.node_index}",
                "content": node.content[:200] + "..." if len(node.content) > 200 else node.content,
                "chapter_id": node.chapter_id,
                "timestamp_start": node.timestamp_start,
                "timestamp_end": node.timestamp_end,
                "duration": node.duration,
                "page_start": page_start,
                "page_end": page_end,
                "is_key_point": node.is_key_point,
                "video_url": video_url,
                "status": "completed" if task else "pending",
            }
            nodes_data.append(node_dict)

        # 7. 查询已保存的学习进度
        saved_progress = None
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if progress:
            saved_progress = {
                "current_node_id": progress.current_node_id,
                "current_node_index": progress.current_node_index,
                "current_timestamp": progress.current_timestamp,
                "current_page": progress.current_page,
                "completion_rate": progress.completion_rate,
                "total_learning_time": progress.total_learning_time,
                "last_accessed_at": progress.last_accessed_at.isoformat() if progress.last_accessed_at else None,
            }

        # 7. 获取PPT逐页内容（用于右侧PPT显示）
        ppt_pages = []
        try:
            from app.services.mapping_service import MappingService
            ppt_pages = MappingService.get_page_texts(session, course_id)
        except Exception as e:
            logger.warning(f"[Player] 获取PPT页面内容失败: {e}")

        # 8. 构建PPT逐页图片URL列表
        slide_images = None
        if course.pdf_file_path or course.source_file_path:
            from app.common.slide_converter import is_pdf_file, get_or_create_pdf
            source_path = course.source_file_path
            pdf_path = course.pdf_file_path

            if pdf_path and Path(pdf_path).exists():
                effective_pdf = pdf_path
            elif source_path and Path(source_path).exists():
                if is_pdf_file(source_path):
                    effective_pdf = source_path
                else:
                    effective_pdf = get_or_create_pdf(source_path)
                    if effective_pdf:
                        course.pdf_file_path = effective_pdf
                        session.add(course)
                        session.commit()
            else:
                effective_pdf = None

            if effective_pdf:
                try:
                    import fitz
                    doc = fitz.open(str(effective_pdf))
                    total_slide_pages = len(doc)
                    doc.close()

                    slide_images = []
                    for i in range(total_slide_pages):
                        slide_images.append({
                            "page": i + 1,
                            "url": f"/api/v1/document/course/{course_id}/slide/{i + 1}",
                        })
                    logger.info(f"[Player] 课程 {course_id} 共 {total_slide_pages} 页PPT图片")
                except Exception as e:
                    logger.warning(f"[Player] 获取PDF页数失败: {e}")

        # 9. 返回完整数据
        return PlayerInitData(
            course_id=course_id,
            course_title=course.title,
            script_id=active_script.id,
            total_duration=active_script.audio_duration or sum(n.duration for n in nodes),
            total_nodes=len(nodes),
            nodes=nodes_data,
            video_base_url="/api/v1/video/stream/",
            ppt_pages=ppt_pages if ppt_pages else None,
            slide_images=slide_images,
            saved_progress=saved_progress,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取播放器数据失败: {str(e)}")


@router.get("/knowledge-points/{course_id}")
async def get_knowledge_points(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("knowledge.view")),
):
    """
    获取知识点导航条数据

    返回所有知识点的简要信息用于底部导航条显示：
    - 知识点标题
    - 时间范围
    - 完成状态
    """
    try:
        frozen_release = course_release_service.get_active_release(
            session, course_id=course_id,
        )
        if frozen_release is not None:
            frozen_outline = session.exec(select(CourseOutlineVersion).where(
                CourseOutlineVersion.course_id == course_id,
                CourseOutlineVersion.outline_version_id == frozen_release.outline_version_id,
            )).first()
            if frozen_outline is None:
                raise HTTPException(status_code=409, detail="发布版本缺少冻结的课程结构")
            nodes = session.exec(select(CourseOutlineNode).where(
                CourseOutlineNode.outline_version_id == frozen_outline.outline_version_id,
            ).order_by(CourseOutlineNode.order_index.asc())).all()
            progress = session.exec(select(LearningProgress).where(
                LearningProgress.user_id == access.user_id,
                LearningProgress.course_id == course_id,
            )).first()
            completed_nodes = []
            if progress:
                from app.models.progress_model import NodeProgress
                completed_nodes = [item.node_id for item in session.exec(
                    select(NodeProgress).where(
                        NodeProgress.progress_id == progress.id,
                        NodeProgress.is_completed == True,
                    )
                ).all()]
            knowledge_points = [
                KnowledgePoint(
                    node_id=index + 1,
                    chapter_id=node.parent_node_id,
                    title=node.title or f"知识点{index + 1}",
                    timestamp_start=0,
                    timestamp_end=0,
                    node_index=index,
                    is_completed=(index + 1) in completed_nodes,
                ).dict()
                for index, node in enumerate(nodes)
                if node.node_type.value == "knowledge_point"
            ]
            return unified_response(200, "获取成功", {
                "release_id": frozen_release.release_id,
                "knowledge_points": knowledge_points,
                "total_count": len(knowledge_points),
                "completed_count": len(completed_nodes),
            })

        # Legacy direct-publication compatibility path; new releases cannot
        # fall through to CourseScript's mutable active pointer.
        # 查询激活脚本
        active_script = session.exec(
            select(CourseScript)
            .where(
                CourseScript.course_id == course_id,
                CourseScript.is_active == True,
            )
        ).first()

        if not active_script:
            return unified_response(404, "课程暂无脚本", None)

        # 查询所有节点
        nodes = session.exec(
            select(ScriptNode)
            .where(ScriptNode.script_id == active_script.id)
            .order_by(ScriptNode.node_index.asc())
        ).all()

        # 查询学习进度（获取已完成节点）
        user_id = access.user_id
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        completed_nodes = []
        if progress:
            # 可以从NodeProgress表查询更详细的完成状态
            from app.models.progress_model import NodeProgress
            node_progress_list = session.exec(
                select(NodeProgress)
                .where(
                    NodeProgress.progress_id == progress.id,
                    NodeProgress.is_completed == True,
                )
            ).all()
            completed_nodes = [np.node_id for np in node_progress_list]

        # 构建知识点列表
        knowledge_points = []
        for node in nodes:
            kp = KnowledgePoint(
                node_id=node.id,
                chapter_id=node.chapter_id,
                title=node.title or f"知识点{node.node_index}",
                timestamp_start=node.timestamp_start,
                timestamp_end=node.timestamp_end,
                node_index=node.node_index,
                is_completed=node.id in completed_nodes,
            )
            knowledge_points.append(kp.dict())

        return unified_response(200, "获取成功", {
            "knowledge_points": knowledge_points,
            "total_count": len(knowledge_points),
            "completed_count": len(completed_nodes),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(500, f"获取失败: {str(e)}", None)


@router.post("/progress/save")
async def save_player_progress(
    request: ProgressSaveRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    保存播放器学习进度

    用于断点续播功能：
    - 定期自动保存（建议每5秒或暂停时）
    - 记录当前播放位置、当前节点、已完成节点列表
    """
    try:
        access = require_course_permission(session, current_user, request.course_id, "course.progress.read_self")
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation can write learning progress")
        user_id = access.user_id

        # 查询或创建学习进度记录
        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == request.course_id,
            )
        ).first()

        if not progress:
            # 创建新记录
            course = session.get(Course, request.course_id)
            if not course:
                return unified_response(404, "课程不存在", None)

            progress = LearningProgress(
                user_id=user_id,
                course_id=request.course_id,
                status=LearningStatus.IN_PROGRESS,
                started_at=utcnow_aware(),
            )
            session.add(progress)

        # 更新进度数据
        progress.current_node_id = request.current_node_id
        progress.current_timestamp = request.current_timestamp
        progress.current_page = request.current_page

        # 计算完成率
        if request.completed_nodes:
            progress.completed_nodes = len(request.completed_nodes)

            # 获取总节点数
            active_script = session.exec(
                select(CourseScript)
                .where(
                    CourseScript.course_id == request.course_id,
                    CourseScript.is_active == True,
                )
            ).first()
            if active_script:
                total_nodes = session.exec(
                    select(func.count(ScriptNode.id))
                    .where(ScriptNode.script_id == active_script.id)
                ).one()
                progress.total_nodes = total_nodes
                progress.completion_rate = len(request.completed_nodes) / max(total_nodes, 1)

        progress.status = LearningStatus.IN_PROGRESS
        progress.last_accessed_at = utcnow_aware()
        progress.updated_at = utcnow_aware()

        # 听课时长埋点：把本次保存周期新增的听课秒数累加到当前节点的 NodeProgress.time_spent。
        # 认知引擎 _node_watch_seconds 读取该字段作为 evidence_confidence 的佐证。
        # current_node_id 为空或 delta 为 0 时跳过，避免空写。
        if request.current_node_id is not None and request.time_spent_delta > 0:
            node_progress = session.exec(
                select(NodeProgress).where(
                    NodeProgress.progress_id == progress.id,
                    NodeProgress.node_id == request.current_node_id,
                )
            ).first()
            if node_progress is None:
                # node_index 取节点序号；无法解析时回退 0，仅用于排序展示
                script_node = session.get(ScriptNode, request.current_node_id)
                node_progress = NodeProgress(
                    progress_id=progress.id,
                    node_id=request.current_node_id,
                    node_index=script_node.node_index if script_node else 0,
                    first_accessed_at=utcnow_aware(),
                )
                session.add(node_progress)
            node_progress.time_spent = int(node_progress.time_spent or 0) + int(round(request.time_spent_delta))
            node_progress.last_timestamp = request.current_timestamp
            node_progress.last_accessed_at = utcnow_aware()

        session.commit()
        session.refresh(progress)

        # M8：学习路径规划——当前节点完成后推荐下一学习节点（薄弱优先）。
        # 路径规划失败不阻塞进度保存（降级为空数组）。
        next_nodes: list[dict] = []
        try:
            current_key: Optional[str] = None
            if request.current_node_id is not None:
                script_node = session.get(TeachingScriptNode, request.current_node_id)
                if script_node is not None and script_node.outline_node_id:
                    current_key = script_node.outline_node_id
            from app.services.learning_path_service import plan_next_nodes

            next_nodes = plan_next_nodes(
                session,
                student_id=user_id,
                course_id=request.course_id,
                current_node_key=current_key,
                max_next=3,
            )
        except Exception:  # noqa: BLE001 -- 路径规划为增强能力，失败不阻塞保存
            next_nodes = []

        return unified_response(200, "进度保存成功", {
            "progress_id": progress.id,
            "saved_timestamp": request.current_timestamp,
            "completion_rate": progress.completion_rate,
            "next_nodes": next_nodes,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(500, f"保存失败: {str(e)}", None)


@router.get("/progress/{course_id}")
async def get_player_progress(
    course_id: int,
    session: Session = Depends(get_session),
    access: CourseAccessContext = Depends(course_permission("course.progress.read_self")),
):
    """
    获取播放器学习进度

    用于断点续播：进入播放器页面时调用此接口恢复上次的播放位置
    """
    try:
        if not access.analytics_eligible:
            raise HTTPException(status_code=403, detail="Only learner participation has personal progress")
        user_id = access.user_id

        progress = session.exec(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        ).first()

        if not progress:
            return unified_response(200, "暂无学习记录", {
                "has_progress": False,
                "current_timestamp": 0.0,
                "current_page": 1,
                "current_node_index": 0,
            })

        return unified_response(200, "获取成功", {
            "has_progress": True,
            "progress_id": progress.id,
            "current_node_id": progress.current_node_id,
            "current_node_index": progress.current_node_index,
            "current_timestamp": progress.current_timestamp,
            "current_page": progress.current_page,
            "completion_rate": progress.completion_rate,
            "total_learning_time": progress.total_learning_time,
            "status": progress.value if hasattr(progress, 'value') else progress.status,
            "last_accessed_at": progress.last_accessed_at.isoformat() if progress.last_accessed_at else None,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return unified_response(500, f"获取失败: {str(e)}", None)
