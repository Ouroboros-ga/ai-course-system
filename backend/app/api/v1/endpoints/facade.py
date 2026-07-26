"""Phase A 前后端契约对齐门面层

新增门面端点，返回统一的 ViewModel，不暴露 Shadow DTO 或数据库 ID。
前端应消费此层而非直接消费零散的 V1 端点响应。

ViewModel 契约:
  - HomeViewModel: 工作首页聚合视图，含继续学习、我建设的、待审核、系统任务
  - CourseCard: 课程列表读模型（learning/building/hall 视图）
  - CourseOverviewViewModel: 课程概览，含能力声明、统一 document_id、结构摘要
  - CitationViewModel: 引用定位，含稳定 document_id (UUID)
  - QuizViewModel: 题目视图，含知识点关联和发布状态

所有端点使用 require_course_permission 进行课程级权限校验。
"""
from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.core.config import settings
from app.models.database import get_session
from app.models.course_model import (
    Course,
    CourseScript,
    DoclingDocument,
    DoclingText,
    ScriptNode,
    StudentEnrollment,
)
from app.models.access_control_model import CourseMembership
from app.models.user_model import User
from app.models.document_artifact_model import DocumentArtifact
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionStatus,
)
from app.services.course_access_service import (
    require_course_permission,
    serialize_access_context,
    ALL_PERMISSIONS,
)
from app.services.facade_home_service import facade_home_service

router = APIRouter(tags=["Phase A 门面层"])


# ==================== HomeViewModel（阶段1） ====================

@router.get("/home")
async def get_home(
    mode: Optional[str] = Query(None, description="强制视图：student 或 teacher"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """工作首页聚合 ViewModel

    返回 HomeViewModel，包含：
    - active_mode: student/teacher/mixed，由当前用户的课程成员关系推导
    - continue_learning: 最近学习的课程（学生视角）
    - building_courses: 我建设的课程（教师视角）
    - pending_reviews: 待处理审核（教师视角）
    - system_tasks: 失败/进行中任务（所有视角）

    所有数据基于 CourseMembership 严格隔离，跨用户/跨课程不可见。
    """
    data = facade_home_service.get_home(
        session,
        current_user,
        mode=mode,
    )
    return unified_response(
        code=200,
        message="获取工作首页成功",
        data=data,
    )


# ==================== CourseCard（阶段1课程列表读模型） ====================

@router.get("/courses")
async def list_courses(
    view: str = Query(..., description="列表视图：learning/building/hall"),
    cursor: Optional[str] = Query(None, description="上一页返回的 next_cursor"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，1..100"),
    query: Optional[str] = Query(None, description="按标题模糊搜索"),
    subject: Optional[str] = Query(None, description="按学科过滤（hall 视图预留）"),
    status: Optional[str] = Query(None, description="按状态过滤（learning/building 视图）"),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程列表读模型

    - view=learning: 当前用户作为学生可学习的课程
    - view=building: 当前用户有 course.edit 或建设职责的课程
    - view=hall: 课程大厅，仅返回允许发现的已发布课程；草稿不进入大厅

    返回 items / next_cursor / total / has_next；游标分页协议与 §1.2 一致。
    """
    data = facade_home_service.list_courses(
        session,
        current_user,
        view=view,
        cursor=cursor,
        page_size=page_size,
        query=query,
        subject=subject,
        status_filter=status,
    )
    return unified_response(
        code=200,
        message="获取课程列表成功",
        data=data,
    )


# ==================== CourseOverviewViewModel ====================

@router.get("/course/{course_id}/overview")
async def get_course_overview(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程概览门面 ViewModel

    聚合课程信息、能力声明、统一 document_id、结构摘要。
    前端消费此 ViewModel，不直接消费 V1 端点的零散响应。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])

    course = session.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    # 统一 document_id (DocumentArtifact.document_id UUID)
    artifact = session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).first()
    document_id = artifact.document_id if artifact else None

    # 能力声明
    capabilities = context.capabilities

    # 结构摘要
    active_script = session.exec(
        select(CourseScript).where(
            CourseScript.course_id == course_id,
            CourseScript.is_active == True,
        )
    ).first()

    node_count = 0
    chapter_count = 0
    if active_script:
        nodes = session.exec(
            select(ScriptNode).where(ScriptNode.script_id == active_script.id)
        ).all()
        node_count = len(nodes)
        chapter_ids = {n.chapter_id for n in nodes if n.chapter_id}
        chapter_count = len(chapter_ids)

    # 进度摘要（学生）
    progress_summary = None
    if context.role and context.role.value == "student":
        enrollment = session.exec(
            select(StudentEnrollment).where(
                StudentEnrollment.student_id == user_id,
                StudentEnrollment.course_id == course_id,
            )
        ).first()
        if enrollment:
            progress_summary = {
                "overall_progress": enrollment.overall_progress or 0,
                "avg_understanding_score": enrollment.avg_understanding_score or 0,
                "total_study_minutes": enrollment.total_study_minutes or 0,
            }

    # 权限视图
    access_view = serialize_access_context(context, ALL_PERMISSIONS)

    return unified_response(
        code=200,
        message="获取课程概览成功",
        data={
            "course_id": course_id,
            "title": course.title,
            "description": course.description or "",
            "status": course.status.value if course.status else "draft",
            "teacher_id": course.teacher_id,
            "document_id": document_id,
            "capabilities": capabilities,
            "access": access_view,
            "structure": {
                "node_count": node_count,
                "chapter_count": chapter_count,
                "total_pages": course.total_pages or 0,
                "total_duration": course.total_duration or 0,
            },
            "progress": progress_summary,
            "role": context.role.value if context.role else None,
            "participation_mode": context.participation_mode.value if context.participation_mode else None,
            "analytics_eligible": context.analytics_eligible,
        },
    )


# ==================== CitationViewModel ====================

@router.get("/course/{course_id}/citation/{node_id}")
async def get_citation_view(
    course_id: int,
    node_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """引用定位门面 ViewModel

    返回统一 document_id (UUID)，与 GET /document/{document_id} 契约一致。
    不暴露 DoclingDocument 整数主键。
    """
    require_course_permission(session, current_user, course_id, "course.citation.read")

    # 查询节点
    node = session.get(ScriptNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 验证节点属于该课程
    script = session.get(CourseScript, node.script_id) if node.script_id else None
    if not script or script.course_id != course_id:
        raise HTTPException(status_code=404, detail="节点不属于该课程")

    # 查询 DocumentArtifact 获取统一 document_id
    artifact = session.exec(
        select(DocumentArtifact).where(DocumentArtifact.course_id == course_id)
    ).first()
    document_id = artifact.document_id if artifact else None

    # 查询原文片段
    docling_doc = session.exec(
        select(DoclingDocument).where(DoclingDocument.course_id == course_id)
    ).first()

    page_start = node.page_start
    page_end = node.page_end
    snippet = None

    if docling_doc and page_start is not None:
        texts = session.exec(
            select(DoclingText)
            .where(DoclingText.doc_id == docling_doc.id)
            .where(DoclingText.page_no == page_start)
        ).all()
        if texts:
            snippet = " ".join(t.text for t in texts[:5])[:500]

    return unified_response(
        code=200,
        message="获取引用定位成功",
        data={
            "document_id": document_id,
            "course_id": course_id,
            "node_id": node_id,
            "node_title": node.title or node.content[:50] if node.content else "",
            "page_start": page_start,
            "page_end": page_end,
            "snippet": snippet,
            "source_file": artifact.file_name if artifact else (docling_doc.origin_filename if docling_doc else ""),
            "return_anchor": {
                "node_id": node_id,
                "label": node.title or "",
            },
        },
    )


# ==================== QuizViewModel ====================

@router.get("/course/{course_id}/quiz")
async def get_quiz_view(
    course_id: int,
    node_id: Optional[int] = Query(None, description="按知识点筛选"),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """题目视图门面 ViewModel

    返回统一格式的题目列表，学生仅可见 published。
    关联知识点和返回锚点。
    """
    context = require_course_permission(session, current_user, course_id, "question_bank.read")

    stmt = select(QuestionBankItem).where(
        QuestionBankItem.course_id == course_id,
        QuestionBankItem.is_latest == True,
    )

    # 学生只能看 published
    if context.role and context.role.value == "student":
        stmt = stmt.where(QuestionBankItem.status == QuestionStatus.PUBLISHED)

    if node_id:
        stmt = stmt.where(QuestionBankItem.knowledge_node_ids.contains([node_id]))

    stmt = stmt.limit(limit)
    items = session.exec(stmt).all()

    return unified_response(
        code=200,
        message="获取题目视图成功",
        data={
            "course_id": course_id,
            "items": [
                _serialize_quiz_item(
                    q,
                    include_answer=not (
                        context.role and context.role.value in {"student", "observer"}
                    ),
                )
                for q in items
            ],
            "total": len(items),
            "role": context.role.value if context.role else None,
        },
    )


def _serialize_quiz_item(
    q: QuestionBankItem,
    *,
    include_answer: bool,
) -> dict[str, Any]:
    """序列化题目为 QuizViewModel"""
    data = {
        "question_id": q.id,
        "question_text": q.question_text,
        "options": q.options,
        "question_type": q.question_type.value,
        "difficulty": q.difficulty.value,
        "knowledge_node_ids": q.knowledge_node_ids,
        "status": q.status.value,
        "version": q.version,
        "return_anchor": {
            "node_id": q.knowledge_node_ids[0] if q.knowledge_node_ids else None,
            "label": q.category or "",
        },
    }
    if include_answer:
        data["answer"] = q.answer
    return data


# ==================== R2 检索能力检查 ====================

@router.get("/course/{course_id}/retrieval-capability")
async def get_retrieval_capability(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """检查课程的 R2 检索能力

    前端通过此端点识别是否可显示引用与检索轨迹。
    采用课程白名单/能力开关，支持一键回退。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")

    # 检查课程能力开关
    evidence_capable = context.capabilities.get("evidence", False)

    # 检查 Feature Flag
    r2_enabled = False
    r2_mode = "v1_only"
    try:
        from app.core.feature_flags import (
            DOCUMENT_KG_RUNTIME_MODE,
            resolve_effective_modes,
        )
        configured = {
            DOCUMENT_KG_RUNTIME_MODE: getattr(settings, DOCUMENT_KG_RUNTIME_MODE, "v1_only"),
        }
        effective = resolve_effective_modes(configured)
        r2_mode = effective[DOCUMENT_KG_RUNTIME_MODE].effective
        r2_enabled = (
            r2_mode == "v2_shadow"
            and settings.R2_STUDENT_ANSWER_ENABLED
        )
    except Exception:
        pass

    # 检查课程侧车是否存在
    sidecar_exists = False
    try:
        from app.platform.shadow.course_evidence_sidecar import CourseEvidenceSidecarStore
        store = CourseEvidenceSidecarStore()
        sidecar_exists = store.read_course(str(course_id)) is not None
    except Exception:
        pass

    # 综合判定
    retrieval_available = evidence_capable and r2_enabled and sidecar_exists

    return unified_response(
        code=200,
        message="获取检索能力成功",
        data={
            "course_id": course_id,
            "retrieval_available": retrieval_available,
            "evidence_capability": evidence_capable,
            "r2_mode": r2_mode,
            "r2_enabled": r2_enabled,
            "student_answer_gate_enabled": settings.R2_STUDENT_ANSWER_ENABLED,
            "sidecar_exists": sidecar_exists,
            "can_show_citations": retrieval_available,
            "policy_version": "r2-retrieval-v1.0",
            "fallback_to_v1": not retrieval_available,
        },
    )


# ==================== 阶段2：成员/设置聚合读模型 ====================

@router.get("/course/{course_id}/members")
async def get_course_members_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """成员页面聚合读模型

    返回 members / groups / pending_join_requests / recent_sync_runs / audit_summary。
    跨课程严格隔离；非教师角色看不到 pending_join_requests。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")
    user_id = int(current_user["user_id"])

    from app.models.course_lifecycle_model import (
        CourseGroup,
        CourseJoinRequest,
        CourseSettingVersion,
        IntegrationSyncRun,
        JoinRequestStatus,
        SyncRunStatus,
    )
    from app.services.course_lifecycle_service import (
        course_group_service,
        fanya_sync_service,
        join_request_service,
    )

    # 成员列表（基于 CourseMembership）
    memberships = session.exec(
        select(CourseMembership)
        .where(CourseMembership.course_id == course_id)
        .order_by(CourseMembership.role, CourseMembership.user_id)
    ).all()
    member_user_ids = [m.user_id for m in memberships]
    users_map = {
        u.id: u for u in session.exec(select(User).where(User.id.in_(member_user_ids))).all()
    } if member_user_ids else {}

    members_view = []
    for m in memberships:
        u = users_map.get(m.user_id)
        members_view.append({
            "user_id": m.user_id,
            "username": u.username if u else None,
            "role": m.role.value,
            "status": m.status.value,
            "analytics_excluded": m.analytics_excluded,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            "left_at": m.left_at.isoformat() if m.left_at else None,
        })

    # 分组
    groups = course_group_service.list_groups(session, course_id=course_id)
    groups_view = [
        {
            "group_id": g.group_id,
            "name": g.name,
            "description": g.description,
            "group_type": g.group_type,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in groups
    ]

    # 待处理加入申请（仅教师可见）
    pending_requests = []
    if context.allows("membership.role.change"):
        reqs = join_request_service.list_requests(
            session,
            course_id=course_id,
            status_filter=JoinRequestStatus.PENDING,
        )
        pending_requests = [
            {
                "request_id": r.request_id,
                "applicant_user_id": r.applicant_user_id,
                "apply_reason": r.apply_reason,
                "channel": r.channel.value,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in reqs
        ]

    # 最近同步运行
    sync_runs = fanya_sync_service.list_runs(session, course_id=course_id, limit=5)
    sync_view = [
        {
            "sync_run_id": r.sync_run_id,
            "status": r.status.value,
            "applied_added": r.applied_added,
            "applied_removed": r.applied_removed,
            "applied_skipped": r.applied_skipped,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_message": r.error_message,
        }
        for r in sync_runs
    ]

    return unified_response(
        code=200,
        message="获取成员页面聚合读模型成功",
        data={
            "course_id": course_id,
            "members": members_view,
            "groups": groups_view,
            "pending_join_requests": pending_requests,
            "recent_sync_runs": sync_view,
            "can_review_join_requests": context.allows("membership.role.change"),
            "viewer_role": context.role.value if context.role else None,
        },
    )


@router.get("/course/{course_id}/settings")
async def get_course_settings_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """设置页面聚合读模型

    返回当前活跃设置版本 + 能力声明 + 教师可编辑范围。
    跨课程严格隔离；非教师角色 can_edit=False。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")

    from app.services.course_lifecycle_service import course_settings_service

    current_setting = course_settings_service.get_current(session, course_id=course_id)
    setting_view = None
    if current_setting is not None:
        setting_view = {
            "setting_version_id": current_setting.setting_version_id,
            "version": current_setting.version,
            "profile": current_setting.profile,
            "publish": current_setting.publish,
            "agent_policy": current_setting.agent_policy,
            "safety": current_setting.safety,
            "sandbox": current_setting.sandbox,
            "integration": current_setting.integration,
            "created_by": current_setting.created_by,
            "created_at": current_setting.created_at.isoformat() if current_setting.created_at else None,
        }

    course = session.get(Course, course_id)
    course_profile = {
        "title": course.title if course else None,
        "description": getattr(course, "description", "") if course else None,
        "cover_url": getattr(course, "cover_url", None) if course else None,
        "status": course.status.value if course else None,
        "invite_code": course.invite_code if course else None,
    } if course else None

    return unified_response(
        code=200,
        message="获取设置页面聚合读模型成功",
        data={
            "course_id": course_id,
            "course_profile": course_profile,
            "current_setting": setting_view,
            "capabilities": context.capabilities,
            "can_edit": context.allows("course.edit"),
            "can_publish": context.allows("course.publish"),
            "viewer_role": context.role.value if context.role else None,
        },
    )


# ==================== 阶段3：课程建设聚合读模型 ====================

@router.get("/course/{course_id}/build")
async def get_course_build_view(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """课程建设聚合读模型

    返回七步建设状态 + 质量门禁 + 发布历史。
    跨课程严格隔离；非教师角色 can_build=False。
    """
    context = require_course_permission(session, current_user, course_id, "course.view")

    from app.services.course_build_service import course_build_service

    # 教师视角自动初始化草稿
    if context.allows("course.edit"):
        course_build_service.get_or_create_draft(
            session,
            course_id=course_id,
            actor_user_id=context.user_id,
        )
        session.commit()

    build_view = course_build_service.get_build_view(session, course_id=course_id)
    build_view["can_build"] = context.allows("course.edit")
    build_view["can_publish"] = context.allows("course.publish")
    build_view["viewer_role"] = context.role.value if context.role else None
    return unified_response(
        code=200,
        message="获取课程建设聚合读模型成功",
        data=build_view,
    )
