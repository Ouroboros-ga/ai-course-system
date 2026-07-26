"""阶段1：工作首页与课程列表聚合读模型服务。

契约来源：
- PageDesign前端API契约规划.md §3.1 / §3.2
- PageDesign后端全量实施路线图.md §4（阶段1）

设计要点：
- 不复制授权事实：所有可见性判断都基于 CourseMembership + CourseCapability，
  不缓存到独立表；前端不再依赖 teacher_id 推断课程角色。
- 课程大厅只返回允许发现的已发布课程，禁止泄露草稿；
- 跨课程/跨用户严格按 owner_user_id / membership 过滤；
- 失败任务、待审核候选均来源于现有领域表，不在 facade 层伪造数据；
- LLM/Agent/WebResearch 不在此层产生正式事实。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, or_, select

from app.core.exceptions import reject_validation_failed
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.graph_production_model import GraphNodeReview
from app.models.question_bank_model import QuestionBankItem, QuestionStatus
from app.models.task_model import TaskRecord
from app.models.user_model import User
from app.services.course_access_service import (
    CAPABILITY_NAMES,
    DEFAULT_NEW_COURSE_CAPABILITIES,
    resolve_course_access,
    serialize_access_context,
    ALL_PERMISSIONS,
)


# ---------------------------------------------------------------------------
# 阶段1：能力成熟度声明
# ---------------------------------------------------------------------------

# 与 PageDesign前端API契约规划.md §1.1 状态标记对齐。
# 这些是产品级能力成熟度，区别于单课程 capability 开关。
SYSTEM_CAPABILITY_MATURITY: dict[str, str] = {
    "course_learning": "available",
    "course_building": "available",
    "question_bank": "available",
    "knowledge_graph": "experimental",
    "evidence": "experimental",
    "experiment": "planned",
    "coding_sandbox": "available",
    "cognitive_analysis": "available",
    "visualization": "available",
    "media_timeline": "adapter_needed",
    "teaching_agent": "adapter_needed",
    "web_research": "adapter_needed",
}


# ---------------------------------------------------------------------------
# ViewModel 数据类
# ---------------------------------------------------------------------------


@dataclass
class CourseCard:
    """CourseCard 契约：必须包含 course_id/title/cover/status/role/access/capabilities。
    progress 仅对学习视图填充；build_status 仅对建设视图填充。
    """

    course_id: int
    title: str
    cover: Optional[str]
    status: str
    role: Optional[str]
    access: dict[str, Any]
    capabilities: dict[str, bool]
    progress: Optional[dict[str, Any]] = None
    build_status: Optional[dict[str, Any]] = None
    teacher_name: Optional[str] = None
    description: Optional[str] = None
    last_activity_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "course_id": self.course_id,
            "title": self.title,
            "cover": self.cover,
            "status": self.status,
            "role": self.role,
            "access": self.access,
            "capabilities": self.capabilities,
            "teacher_name": self.teacher_name,
            "description": self.description,
            "last_activity_at": self.last_activity_at,
        }
        if self.progress is not None:
            data["progress"] = self.progress
        if self.build_status is not None:
            data["build_status"] = self.build_status
        return data


@dataclass
class ContinueLearningCard:
    """首页"继续进行"学习卡片。"""

    course_id: int
    title: str
    role: str
    current_chapter: Optional[str]
    last_position: Optional[dict[str, Any]]
    progress: float
    last_activity_at: Optional[str]
    main_action: str = "continue_learning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "title": self.title,
            "role": self.role,
            "current_chapter": self.current_chapter,
            "last_position": self.last_position,
            "progress": self.progress,
            "last_activity_at": self.last_activity_at,
            "main_action": self.main_action,
        }


@dataclass
class BuildingCourseCard:
    """首页"我建设的"课程卡片。"""

    course_id: int
    title: str
    role: str
    status: str
    current_build_step: Optional[str]
    pending_review_count: int
    failed_task_count: int
    last_edited_at: Optional[str]
    main_action: str = "continue_building"

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "title": self.title,
            "role": self.role,
            "status": self.status,
            "current_build_step": self.current_build_step,
            "pending_review_count": self.pending_review_count,
            "failed_task_count": self.failed_task_count,
            "last_edited_at": self.last_edited_at,
            "main_action": self.main_action,
        }


@dataclass
class PendingReviewCard:
    """首页"需要处理"卡片。"""

    item_id: str
    course_id: int
    course_title: str
    kind: str  # question_review | graph_review | failed_task | join_request
    title: str
    detail: str
    created_at: Optional[str]
    action_url: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "course_id": self.course_id,
            "course_title": self.course_title,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "created_at": self.created_at,
            "action_url": self.action_url,
        }


@dataclass
class TaskSummary:
    """首页"系统任务"摘要。"""

    task_id: str
    task_type: str
    status: str
    progress: int
    course_id: Optional[int]
    error_code: str
    error_message: str
    created_at: Optional[str]
    updated_at: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "course_id": self.course_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# FacadeHomeService
# ---------------------------------------------------------------------------


class FacadeHomeService:
    """阶段1 首页与课程列表聚合服务。

    所有方法都接收 Session，由路由层管理事务边界；
    服务自身不创建独立 session，避免与请求级事务脱节。
    """

    # 首页卡片数量上限（与 page-design.md §8.3 A "最多展示 3 个条目" 对齐）
    HOME_CONTINUE_LIMIT = 3
    HOME_BUILDING_LIMIT = 3
    HOME_PENDING_LIMIT = 10
    HOME_TASKS_LIMIT = 5

    # 课程列表分页上限
    COURSE_LIST_PAGE_SIZE = 20
    COURSE_LIST_MAX_PAGE_SIZE = 100

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def get_home(
        self,
        session: Session,
        current_user: dict[str, Any],
        *,
        mode: Optional[str] = None,
    ) -> dict[str, Any]:
        """聚合 HomeViewModel。

        - mode=student/teacher 强制以单一视角呈现；不传则基于实际成员关系推导
          active_mode；
        - 跨课程严格按 membership 过滤，平台管理员在教师视图下看到所有
          其有 review 权限的待办。
        """
        user_id = int(current_user["user_id"])
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            from app.core.exceptions import reject_auth_required
            reject_auth_required("账户不可用")

        if mode is not None and mode not in {"student", "teacher"}:
            reject_validation_failed(
                "mode 必须为 student 或 teacher",
                details={"allowed": ["student", "teacher"]},
            )

        # 推导 active_mode
        memberships = session.exec(
            select(CourseMembership).where(
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).all()
        has_student = any(m.role == CourseRole.STUDENT for m in memberships)
        has_teacher = any(
            m.role in {CourseRole.OWNER, CourseRole.TEACHER, CourseRole.TEACHING_ASSISTANT}
            for m in memberships
        )

        if mode is None:
            if has_student and has_teacher:
                active_mode = "mixed"
            elif has_teacher:
                active_mode = "teacher"
            else:
                active_mode = "student"
        else:
            active_mode = mode

        # student 视图下的"继续学习"
        continue_learning: list[ContinueLearningCard] = []
        if active_mode in {"student", "mixed"}:
            continue_learning = self._build_continue_learning(session, user_id)

        # teacher 视图下的"我建设的"
        building_courses: list[BuildingCourseCard] = []
        if active_mode in {"teacher", "mixed"}:
            building_courses = self._build_building_courses(session, user_id)

        # 待处理审核（teacher 视图）
        pending_reviews: list[PendingReviewCard] = []
        if active_mode in {"teacher", "mixed"}:
            pending_reviews = self._build_pending_reviews(session, user_id)

        # 系统任务（所有视图都展示失败任务）
        system_tasks = self._build_system_tasks(session, user_id)

        return {
            "active_mode": active_mode,
            "continue_learning": [c.to_dict() for c in continue_learning],
            "building_courses": [c.to_dict() for c in building_courses],
            "pending_reviews": [p.to_dict() for p in pending_reviews],
            "system_tasks": [t.to_dict() for t in system_tasks],
            "capabilities": dict(SYSTEM_CAPABILITY_MATURITY),
        }

    def list_courses(
        self,
        session: Session,
        current_user: dict[str, Any],
        *,
        view: str,
        cursor: Optional[str] = None,
        page_size: int = 20,
        query: Optional[str] = None,
        subject: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> dict[str, Any]:
        """课程列表读模型。

        - view=learning: 当前用户作为学生可学习的课程；
        - view=building: 当前用户有 course.edit 或建设职责的课程；
        - view=hall: 课程大厅，仅返回允许发现的已发布课程；
        - 跨用户/跨课程严格隔离；草稿不进入 hall。
        """
        if view not in {"learning", "building", "hall"}:
            reject_validation_failed(
                "view 必须为 learning/building/hall",
                details={"allowed": ["learning", "building", "hall"]},
            )
        if page_size < 1 or page_size > self.COURSE_LIST_MAX_PAGE_SIZE:
            reject_validation_failed(
                f"page_size 必须在 1..{self.COURSE_LIST_MAX_PAGE_SIZE} 之间"
            )

        user_id = int(current_user["user_id"])
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            from app.core.exceptions import reject_auth_required
            reject_auth_required("账户不可用")

        if view == "learning":
            return self._list_learning_courses(
                session, user_id, cursor=cursor, page_size=page_size,
                query=query, status_filter=status_filter,
            )
        if view == "building":
            return self._list_building_courses(
                session, user_id, cursor=cursor, page_size=page_size,
                query=query, status_filter=status_filter,
            )
        return self._list_hall_courses(
            session, user_id, cursor=cursor, page_size=page_size,
            query=query, subject=subject, status_filter=status_filter,
        )

    # ------------------------------------------------------------------
    # 首页：继续学习
    # ------------------------------------------------------------------

    def _build_continue_learning(
        self, session: Session, user_id: int
    ) -> list[ContinueLearningCard]:
        """学生最近学习的课程（最多3个）。"""
        enrollments = session.exec(
            select(StudentEnrollment)
            .where(
                StudentEnrollment.student_id == user_id,
                StudentEnrollment.is_active == True,
            )
            .order_by(
                StudentEnrollment.last_study_time.desc().nullslast(),
                StudentEnrollment.enrolled_at.desc(),
            )
            .limit(self.HOME_CONTINUE_LIMIT)
        ).all()

        cards: list[ContinueLearningCard] = []
        for enr in enrollments:
            course = session.get(Course, enr.course_id)
            if course is None:
                continue
            # 仅显示已发布或允许学生访问的课程
            if course.status not in {CourseStatus.PUBLISHED, CourseStatus.CLOSED}:
                continue
            cards.append(ContinueLearningCard(
                course_id=course.id,
                title=course.title,
                role="student",
                current_chapter=None,  # 后续阶段补 current_node 摘要
                last_position={
                    "overall_progress": round(enr.overall_progress or 0.0, 2),
                    "last_study_time": enr.last_study_time.isoformat() if enr.last_study_time else None,
                },
                progress=round(enr.overall_progress or 0.0, 2),
                last_activity_at=enr.last_study_time.isoformat() if enr.last_study_time else None,
            ))
        return cards

    # ------------------------------------------------------------------
    # 首页：我建设的
    # ------------------------------------------------------------------

    def _build_building_courses(
        self, session: Session, user_id: int
    ) -> list[BuildingCourseCard]:
        """教师最近建设的课程（最多3个）。"""
        teacher_roles = {CourseRole.OWNER, CourseRole.TEACHER, CourseRole.TEACHING_ASSISTANT}
        memberships = session.exec(
            select(CourseMembership)
            .where(
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
                CourseMembership.role.in_(teacher_roles),
            )
            .order_by(CourseMembership.updated_at.desc())
            .limit(self.HOME_BUILDING_LIMIT)
        ).all()

        cards: list[BuildingCourseCard] = []
        for m in memberships:
            course = session.get(Course, m.course_id)
            if course is None:
                continue
            pending = self._count_pending_reviews_for_course(session, course.id)
            failed = self._count_failed_tasks_for_course(session, course.id, user_id)
            cards.append(BuildingCourseCard(
                course_id=course.id,
                title=course.title,
                role=m.role.value,
                status=course.status.value if course.status else "draft",
                current_build_step=None,  # 阶段3 补充建设步骤状态机
                pending_review_count=pending,
                failed_task_count=failed,
                last_edited_at=course.updated_at.isoformat() if course.updated_at else None,
            ))
        return cards

    # ------------------------------------------------------------------
    # 首页：待处理审核
    # ------------------------------------------------------------------

    def _build_pending_reviews(
        self, session: Session, user_id: int
    ) -> list[PendingReviewCard]:
        """教师需要处理的审核项（最多10个）。"""
        teacher_roles = {CourseRole.OWNER, CourseRole.TEACHER, CourseRole.TEACHING_ASSISTANT}
        memberships = session.exec(
            select(CourseMembership)
            .where(
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
                CourseMembership.role.in_(teacher_roles),
            )
        ).all()
        if not memberships:
            return []

        course_ids = [m.course_id for m in memberships]
        course_by_id = {m.course_id: session.get(Course, m.course_id) for m in memberships}
        cards: list[PendingReviewCard] = []

        # 1. 题目审核：auto_accepted/draft/stale 状态的题目需要教师审核
        questions = session.exec(
            select(QuestionBankItem)
            .where(
                QuestionBankItem.course_id.in_(course_ids),
                QuestionBankItem.is_latest == True,
                QuestionBankItem.status.in_([
                    QuestionStatus.AUTO_ACCEPTED,
                    QuestionStatus.DRAFT,
                    QuestionStatus.STALE,
                ]),
            )
            .order_by(QuestionBankItem.updated_at.desc())
            .limit(self.HOME_PENDING_LIMIT)
        ).all()
        for q in questions:
            course = course_by_id.get(q.course_id)
            if course is None:
                continue
            cards.append(PendingReviewCard(
                item_id=f"question:{q.id}",
                course_id=course.id,
                course_title=course.title,
                kind="question_review",
                title=f"题目待审核: {(q.question_text or '')[:40]}",
                detail=f"状态: {q.status.value}",
                created_at=q.updated_at.isoformat() if q.updated_at else None,
                action_url=f"/app/course/{course.id}/build?page-mappings",
            ))
            if len(cards) >= self.HOME_PENDING_LIMIT:
                return cards

        # 2. 图谱节点审核：proposed 状态
        reviews = session.exec(
            select(GraphNodeReview)
            .where(
                GraphNodeReview.course_id.in_(course_ids),
                GraphNodeReview.decision == "proposed",
            )
            .order_by(GraphNodeReview.created_at.desc())
            .limit(self.HOME_PENDING_LIMIT - len(cards))
        ).all()
        for r in reviews:
            course = course_by_id.get(r.course_id)
            if course is None:
                continue
            cards.append(PendingReviewCard(
                item_id=f"graph_review:{r.id}",
                course_id=course.id,
                course_title=course.title,
                kind="graph_review",
                title=f"图谱候选待审核: {r.target_type} {r.target_id}",
                detail=r.review_comment or "AI 提出的图谱候选，等待教师确认",
                created_at=r.created_at.isoformat() if r.created_at else None,
                action_url=f"/app/course/{course.id}/knowledge?view=candidates",
            ))
            if len(cards) >= self.HOME_PENDING_LIMIT:
                return cards

        # 3. 失败任务
        failed_tasks = session.exec(
            select(TaskRecord)
            .where(
                TaskRecord.course_id.in_(course_ids),
                TaskRecord.status == "failed",
                TaskRecord.acknowledged == False,
            )
            .order_by(TaskRecord.updated_at.desc())
            .limit(self.HOME_PENDING_LIMIT - len(cards))
        ).all()
        for t in failed_tasks:
            course = course_by_id.get(t.course_id)
            if course is None:
                continue
            cards.append(PendingReviewCard(
                item_id=f"failed_task:{t.task_id}",
                course_id=course.id,
                course_title=course.title,
                kind="failed_task",
                title=f"任务失败: {t.task_type}",
                detail=t.error_message or t.error_code or "未知原因",
                created_at=t.updated_at.isoformat() if t.updated_at else None,
                action_url=f"/app/tasks/created?focus={t.task_id}",
            ))
            if len(cards) >= self.HOME_PENDING_LIMIT:
                return cards

        return cards

    # ------------------------------------------------------------------
    # 首页：系统任务
    # ------------------------------------------------------------------

    def _build_system_tasks(
        self, session: Session, user_id: int
    ) -> list[TaskSummary]:
        """用户拥有的失败/进行中任务（最多5个）。"""
        records = session.exec(
            select(TaskRecord)
            .where(
                TaskRecord.owner_user_id == user_id,
                TaskRecord.status.in_(["failed", "running", "partial_success"]),
            )
            .order_by(TaskRecord.updated_at.desc())
            .limit(self.HOME_TASKS_LIMIT)
        ).all()
        return [
            TaskSummary(
                task_id=r.task_id,
                task_type=r.task_type,
                status=r.status,
                progress=r.progress,
                course_id=r.course_id,
                error_code=r.error_code,
                error_message=r.error_message,
                created_at=r.created_at.isoformat() if r.created_at else None,
                updated_at=r.updated_at.isoformat() if r.updated_at else None,
            )
            for r in records
        ]

    # ------------------------------------------------------------------
    # 课程列表：learning
    # ------------------------------------------------------------------

    def _list_learning_courses(
        self,
        session: Session,
        user_id: int,
        *,
        cursor: Optional[str],
        page_size: int,
        query: Optional[str],
        status_filter: Optional[str],
    ) -> dict[str, Any]:
        """学生可学习课程列表（基于 StudentEnrollment + CourseMembership）。"""
        # 仅基于 CourseMembership（Course Access v1 是唯一授权来源）
        stmt = (
            select(CourseMembership, Course)
            .join(Course, Course.id == CourseMembership.course_id)
            .where(
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
                CourseMembership.role == CourseRole.STUDENT,
            )
        )

        # 学生可学习的课程状态：published/closed/archived（closed 仍允许已加入成员继续学习）
        allowed_statuses = {CourseStatus.PUBLISHED, CourseStatus.CLOSED, CourseStatus.ARCHIVED}
        stmt = stmt.where(Course.status.in_(allowed_statuses))

        if query:
            stmt = stmt.where(Course.title.contains(query))
        if status_filter:
            try:
                stmt = stmt.where(Course.status == CourseStatus(status_filter))
            except ValueError:
                reject_validation_failed(f"未知的 status 过滤值: {status_filter}")

        # 游标分页：按 updated_at desc, id desc
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Course.updated_at < cursor_ts,
                    (Course.updated_at == cursor_ts) & (Course.id < cursor_id),
                )
            )

        stmt = stmt.order_by(Course.updated_at.desc(), Course.id.desc()).limit(page_size + 1)
        rows = session.exec(stmt).all()
        has_next = len(rows) > page_size
        rows = rows[:page_size]

        items = [
            self._serialize_course_card(session, user_id, course, role=m.role.value)
            for m, course in rows
        ]
        next_cursor = _encode_cursor(rows[-1][1]) if has_next and rows else None
        return {
            "view": "learning",
            "items": items,
            "next_cursor": next_cursor,
            "total": len(items),
            "has_next": has_next,
        }

    # ------------------------------------------------------------------
    # 课程列表：building
    # ------------------------------------------------------------------

    def _list_building_courses(
        self,
        session: Session,
        user_id: int,
        *,
        cursor: Optional[str],
        page_size: int,
        query: Optional[str],
        status_filter: Optional[str],
    ) -> dict[str, Any]:
        """教师建设课程列表（owner/teacher/teaching_assistant）。"""
        teacher_roles = {CourseRole.OWNER, CourseRole.TEACHER, CourseRole.TEACHING_ASSISTANT}
        stmt = (
            select(CourseMembership, Course)
            .join(Course, Course.id == CourseMembership.course_id)
            .where(
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
                CourseMembership.role.in_(teacher_roles),
            )
        )

        # 建设视图允许所有状态（draft/published/closed/archived）
        if query:
            stmt = stmt.where(Course.title.contains(query))
        if status_filter:
            try:
                stmt = stmt.where(Course.status == CourseStatus(status_filter))
            except ValueError:
                reject_validation_failed(f"未知的 status 过滤值: {status_filter}")

        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Course.updated_at < cursor_ts,
                    (Course.updated_at == cursor_ts) & (Course.id < cursor_id),
                )
            )

        stmt = stmt.order_by(Course.updated_at.desc(), Course.id.desc()).limit(page_size + 1)
        rows = session.exec(stmt).all()
        has_next = len(rows) > page_size
        rows = rows[:page_size]

        items: list[dict[str, Any]] = []
        for m, course in rows:
            card = self._serialize_course_card(session, user_id, course, role=m.role.value)
            # 补充建设状态摘要
            card["build_status"] = {
                "pending_review_count": self._count_pending_reviews_for_course(session, course.id),
                "failed_task_count": self._count_failed_tasks_for_course(session, course.id, user_id),
                "current_build_step": None,  # 阶段3 补充
            }
            items.append(card)

        next_cursor = _encode_cursor(rows[-1][1]) if has_next and rows else None
        return {
            "view": "building",
            "items": items,
            "next_cursor": next_cursor,
            "total": len(items),
            "has_next": has_next,
        }

    # ------------------------------------------------------------------
    # 课程列表：hall
    # ------------------------------------------------------------------

    def _list_hall_courses(
        self,
        session: Session,
        user_id: int,
        *,
        cursor: Optional[str],
        page_size: int,
        query: Optional[str],
        subject: Optional[str],
        status_filter: Optional[str],
    ) -> dict[str, Any]:
        """课程大厅：仅返回允许发现的已发布课程。

        - 严格只显示 status=published 的课程；草稿、已关闭、已归档不进入大厅；
        - 已加入的课程仍可在大厅显示（学生可见自己已加入的课程并显示"已加入"标记）；
        - 平台管理员可看到所有 published 课程（不在此处扩展跨状态查看）。
        """
        stmt = select(Course).where(Course.status == CourseStatus.PUBLISHED)

        if query:
            stmt = stmt.where(
                or_(
                    Course.title.contains(query),
                    Course.fanya_course_name.contains(query),
                )
            )
        # subject 字段在当前 Course 模型中未持久化；保留接口契约，过滤在持久化字段存在时生效。
        # status_filter 在 hall 视图下被忽略：hall 只允许 published。
        _ = subject  # noqa: F841

        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Course.updated_at < cursor_ts,
                    (Course.updated_at == cursor_ts) & (Course.id < cursor_id),
                )
            )

        stmt = stmt.order_by(Course.updated_at.desc(), Course.id.desc()).limit(page_size + 1)
        courses = session.exec(stmt).all()
        has_next = len(courses) > page_size
        courses = courses[:page_size]

        # 预查用户已加入的课程 ID 集合，用于标记 "已加入"
        joined_ids = set(session.exec(
            select(CourseMembership.course_id).where(
                CourseMembership.user_id == user_id,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).all())

        items: list[dict[str, Any]] = []
        for course in courses:
            # 课程大厅对未加入用户只暴露 minimum access 信息
            membership = session.exec(
                select(CourseMembership).where(
                    CourseMembership.user_id == user_id,
                    CourseMembership.course_id == course.id,
                    CourseMembership.status == MembershipStatus.ACTIVE,
                )
            ).first()
            role = membership.role.value if membership else None
            capabilities = self._read_course_capabilities(session, course.id)

            items.append({
                "course_id": course.id,
                "title": course.title,
                "cover": course.cover_image,
                "status": course.status.value if course.status else "draft",
                "role": role,
                "access": {
                    "course_role": role,
                    "joined": course.id in joined_ids,
                    "join_method": self._infer_join_method(course),
                },
                "capabilities": capabilities,
                "teacher_name": self._lookup_teacher_name(session, course),
                "description": course.description,
                "last_activity_at": course.updated_at.isoformat() if course.updated_at else None,
            })

        next_cursor = _encode_cursor(courses[-1]) if has_next and courses else None
        return {
            "view": "hall",
            "items": items,
            "next_cursor": next_cursor,
            "total": len(items),
            "has_next": has_next,
        }

    # ------------------------------------------------------------------
    # 序列化与查询辅助
    # ------------------------------------------------------------------

    def _serialize_course_card(
        self,
        session: Session,
        user_id: int,
        course: Course,
        *,
        role: Optional[str],
    ) -> dict[str, Any]:
        """构造单个 CourseCard ViewModel（用于 learning/building 列表）。"""
        # 通过 resolve_course_access 获取权限视图（避免直接读 capability 字段）
        principal = {"user_id": str(user_id), "role": "student" if role == "student" else "teacher"}
        try:
            context = resolve_course_access(session, principal, course.id)
            access_view = serialize_access_context(context, ALL_PERMISSIONS)
            capabilities = context.capabilities
        except Exception:
            # 课程被删除或权限解析失败时退化为最小可见信息
            access_view = {
                "course_role": role,
                "allowed": {},
                "capabilities": dict(DEFAULT_NEW_COURSE_CAPABILITIES),
            }
            capabilities = self._read_course_capabilities(session, course.id)

        # 学习进度（仅学生角色）
        progress: Optional[dict[str, Any]] = None
        if role == "student":
            enr = session.exec(
                select(StudentEnrollment).where(
                    StudentEnrollment.student_id == user_id,
                    StudentEnrollment.course_id == course.id,
                    StudentEnrollment.is_active == True,
                )
            ).first()
            if enr:
                progress = {
                    "overall_progress": round(enr.overall_progress or 0.0, 2),
                    "completed_nodes": enr.total_nodes_completed,
                    "total_nodes": enr.total_nodes_count,
                    "last_study_time": enr.last_study_time.isoformat() if enr.last_study_time else None,
                }

        card = CourseCard(
            course_id=course.id,
            title=course.title,
            cover=course.cover_image,
            status=course.status.value if course.status else "draft",
            role=role,
            access=access_view,
            capabilities=capabilities,
            progress=progress,
            teacher_name=self._lookup_teacher_name(session, course),
            description=course.description,
            last_activity_at=course.updated_at.isoformat() if course.updated_at else None,
        )
        return card.to_dict()

    def _read_course_capabilities(self, session: Session, course_id: int) -> dict[str, bool]:
        cap = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == course_id)
        ).first()
        if cap is None:
            return dict(DEFAULT_NEW_COURSE_CAPABILITIES)
        return {name: bool(getattr(cap, name)) for name in CAPABILITY_NAMES}

    def _lookup_teacher_name(self, session: Session, course: Course) -> Optional[str]:
        """查询课程主讲教师姓名（owner 优先；找不到则回退到 course.teacher_id）。"""
        owner_membership = session.exec(
            select(CourseMembership)
            .where(
                CourseMembership.course_id == course.id,
                CourseMembership.role == CourseRole.OWNER,
                CourseMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        owner_id = owner_membership.user_id if owner_membership else course.teacher_id
        if owner_id is None:
            return None
        owner = session.get(User, owner_id)
        if owner is None:
            return None
        return owner.real_name or owner.username

    def _infer_join_method(self, course: Course) -> str:
        """推断课程大厅中显示的加入方式。"""
        if course.invite_code:
            return "invite_code"
        # 申请审核端点尚未实现（阶段2）；当前默认直接加入。
        return "direct"

    def _count_pending_reviews_for_course(
        self, session: Session, course_id: int
    ) -> int:
        """统计课程待审核候选数（题目 + 图谱节点）。"""
        q_count = session.exec(
            select(QuestionBankItem)
            .where(
                QuestionBankItem.course_id == course_id,
                QuestionBankItem.is_latest == True,
                QuestionBankItem.status.in_([
                    QuestionStatus.AUTO_ACCEPTED,
                    QuestionStatus.DRAFT,
                    QuestionStatus.STALE,
                ]),
            )
        ).all()
        g_count = session.exec(
            select(GraphNodeReview)
            .where(
                GraphNodeReview.course_id == course_id,
                GraphNodeReview.decision == "proposed",
            )
        ).all()
        return len(q_count) + len(g_count)

    def _count_failed_tasks_for_course(
        self, session: Session, course_id: int, user_id: int
    ) -> int:
        """统计课程失败任务数（仅 owner 视角可见）。"""
        records = session.exec(
            select(TaskRecord)
            .where(
                TaskRecord.course_id == course_id,
                TaskRecord.status == "failed",
                TaskRecord.acknowledged == False,
                TaskRecord.owner_user_id == user_id,
            )
        ).all()
        return len(records)


# ---------------------------------------------------------------------------
# 游标编解码
# ---------------------------------------------------------------------------


def _encode_cursor(course: Course) -> str:
    """生成下一页游标：updated_at|id。"""
    ts = course.updated_at.isoformat() if course.updated_at else datetime.now(timezone.utc).isoformat()
    return f"{ts}|{course.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    """解析游标，返回 (timestamp, course_id)。"""
    try:
        cursor_ts_str, cursor_id_str = cursor.split("|", 1)
        return datetime.fromisoformat(cursor_ts_str), int(cursor_id_str)
    except (ValueError, IndexError) as exc:
        reject_validation_failed(
            "cursor 格式非法",
            details={"expected": "ISO8601_TIMESTAMP|COURSE_ID"},
        )
        raise RuntimeError("unreachable") from exc


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


facade_home_service = FacadeHomeService()
