"""The single runtime authority for course-scoped access decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    CourseRole,
    MembershipStatus,
    ParticipationMode,
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.course_model import Course
from app.models.user_model import User


ALL_PERMISSIONS = frozenset({
    "course.view", "course.learn", "course.content.read", "course.progress.read_self",
    "course.question.ask", "course.citation.read", "course.feedback.create", "course.feedback.manage", "knowledge.view", "experiment.view",
    "experiment.run", "note.write_local", "course.edit", "course.structure.edit",
    "course.script.edit", "course.mapping.edit", "course.media.generate", "course.validate",
    "course.publish", "course.unpublish", "course.rollback", "course.delete",
    "course.transfer_owner", "course.archive", "permission.manage", "knowledge.review",
    "knowledge.edit", "knowledge.relation.edit", "evidence.review", "evidence.confirm",
    "knowledge.version.view", "membership.view", "membership.invite", "membership.approve",
    "membership.remove", "membership.role.change", "membership.sync", "experiment.configure",
    "experiment.assign", "submission.review", "sandbox.policy.view", "sandbox.policy.configure",
    "agent.policy.view", "agent.policy.configure", "analytics.view_course",
    "analytics.view_member", "analytics.export", "learning_signal.review", "question.answer",
    "question_bank.read", "question_bank.manage", "question_bank.publish",
    "question_mapping.manage", "question_mapping.generate",
})

LEARNER_PERMISSIONS = frozenset({
    "course.view", "course.learn", "course.content.read", "course.progress.read_self",
    "course.question.ask", "course.citation.read", "course.feedback.create", "knowledge.view", "experiment.view",
    "experiment.run", "note.write_local", "question_bank.read",
})

TEACHER_PERMISSIONS = LEARNER_PERMISSIONS | frozenset({
    "course.edit", "course.structure.edit", "course.script.edit", "course.mapping.edit", "course.feedback.manage",
    "course.media.generate", "course.validate", "course.publish", "course.unpublish",
    "course.rollback", "knowledge.review", "knowledge.edit", "knowledge.relation.edit",
    "evidence.review", "evidence.confirm", "knowledge.version.view", "membership.view",
    "membership.invite", "membership.approve", "membership.remove", "membership.role.change",
    "membership.sync", "experiment.configure", "experiment.assign", "submission.review",
    "sandbox.policy.view", "sandbox.policy.configure", "agent.policy.view",
    "agent.policy.configure", "analytics.view_course", "analytics.view_member", "analytics.export",
    "learning_signal.review", "question.answer",
    "question_bank.manage", "question_bank.publish",
    "question_mapping.manage", "question_mapping.generate",
})

ROLE_PERMISSIONS = {
    CourseRole.STUDENT: LEARNER_PERMISSIONS,
    CourseRole.OBSERVER: frozenset({"course.view", "course.content.read", "course.citation.read", "knowledge.view"}),
    CourseRole.TEACHING_ASSISTANT: LEARNER_PERMISSIONS | frozenset({
        "question.answer", "submission.review", "analytics.view_course", "membership.view", "knowledge.review",
    }),
    CourseRole.TEACHER: TEACHER_PERMISSIONS,
    CourseRole.OWNER: TEACHER_PERMISSIONS | frozenset({
        "course.delete", "course.transfer_owner", "course.archive", "permission.manage",
    }),
}

CAPABILITY_FOR_PERMISSION = {
    "knowledge.view": "knowledge_graph",
    "course.edit": "course_building", "course.structure.edit": "course_building",
    "course.script.edit": "course_building", "course.mapping.edit": "course_building",
    "course.media.generate": "course_building", "course.validate": "course_building",
    "course.publish": "course_building", "course.unpublish": "course_building",
    "course.rollback": "course_building", "knowledge.review": "knowledge_graph",
    "knowledge.edit": "knowledge_graph", "knowledge.relation.edit": "knowledge_graph",
    "evidence.review": "evidence", "evidence.confirm": "evidence",
    "experiment.view": "experiment", "experiment.run": "experiment",
    "experiment.configure": "experiment", "experiment.assign": "experiment",
    "sandbox.policy.view": "coding_sandbox", "sandbox.policy.configure": "coding_sandbox",
    "analytics.view_course": "cognitive_analysis", "analytics.view_member": "cognitive_analysis",
    "analytics.export": "cognitive_analysis", "learning_signal.review": "cognitive_analysis",
    "agent.policy.view": "safety_policy", "agent.policy.configure": "safety_policy",
    "question_bank.manage": "course_building", "question_bank.publish": "course_building",
    "question_mapping.manage": "course_building", "question_mapping.generate": "course_building",
}

CAPABILITY_NAMES = frozenset({"learning", "course_building", "knowledge_graph", "evidence", "experiment", "coding_sandbox", "cognitive_analysis", "safety_policy"})
DEFAULT_NEW_COURSE_CAPABILITIES = {
    "learning": True,
    "course_building": True,
    # New courses use the formal parse -> GraphRAG draft -> review -> vector
    # index pipeline.  These switches expose the governed workflow; they do
    # not bypass the teacher approval gate or publish a bundle automatically.
    "knowledge_graph": True,
    "evidence": True,
    # 本地 Demo 阶段新课程默认全开（含实验/沙箱/安全策略配置入口）；
    # 能力门禁只拦「配置类权限」，教师角色权限本身不受影响。
    "experiment": True,
    "coding_sandbox": True,
    "cognitive_analysis": True,
    "safety_policy": True,
}


@dataclass(frozen=True)
class CourseAccessContext:
    course_id: int
    user_id: int
    role: CourseRole | None
    membership_status: MembershipStatus | None
    permissions: frozenset[str]
    capabilities: dict[str, bool]
    platform_permissions: frozenset[str]
    analytics_eligible: bool
    participation_mode: ParticipationMode | None

    def allows(self, permission: str) -> bool:
        if permission not in self.permissions:
            return False
        required_capability = CAPABILITY_FOR_PERMISSION.get(permission)
        return required_capability is None or self.capabilities.get(required_capability, False)


def _capability_values(value: CourseCapability | None) -> dict[str, bool]:
    if value is None:
        return {name: False for name in CAPABILITY_NAMES}
    return {name: bool(getattr(value, name)) for name in CAPABILITY_NAMES}


def _override_sets(overrides: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    data = overrides or {}
    grants = {str(item) for item in data.get("grant", []) if str(item) in ALL_PERMISSIONS}
    denies = {str(item) for item in data.get("deny", []) if str(item) in ALL_PERMISSIONS}
    for permission, enabled in data.items():
        if permission not in ALL_PERMISSIONS:
            continue
        if enabled is True:
            grants.add(permission)
        elif enabled is False:
            denies.add(permission)
    return grants, denies


def _platform_permissions(session: Session, user_id: int) -> frozenset[str]:
    assignments = session.exec(
        select(PlatformPermissionAssignment).where(
            PlatformPermissionAssignment.user_id == user_id,
            PlatformPermissionAssignment.revoked_at.is_(None),
        )
    ).all()
    return frozenset(assignment.permission.value for assignment in assignments)


def _platform_course_permissions(platform_permissions: frozenset[str]) -> frozenset[str]:
    if PlatformPermission.ADMIN.value in platform_permissions:
        return ALL_PERMISSIONS
    permissions: set[str] = set()
    if PlatformPermission.COURSE_AUDIT.value in platform_permissions:
        permissions.update({"course.view", "course.content.read", "course.citation.read", "knowledge.view", "analytics.view_course", "analytics.view_member"})
    if PlatformPermission.SAFETY_MANAGE.value in platform_permissions:
        permissions.update({"agent.policy.view", "agent.policy.configure", "sandbox.policy.view", "sandbox.policy.configure"})
    if PlatformPermission.CAPABILITY_MANAGE.value in platform_permissions:
        permissions.add("permission.manage")
    return frozenset(permissions)


def require_platform_permission(session: Session, current_user: dict[str, Any], permission: PlatformPermission) -> int:
    """Authorize a cross-course action from explicit persisted permissions."""
    user_id = int(current_user["user_id"])
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账户不可用")
    permissions = _platform_permissions(session, user_id)
    if PlatformPermission.ADMIN.value not in permissions and permission.value not in permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="平台权限不足")
    return user_id


def establish_course_access_baseline(session: Session, course_id: int, owner_user_id: int) -> None:
    """Create the mandatory owner membership and capability record for a course."""
    membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course_id,
            CourseMembership.user_id == owner_user_id,
        )
    ).first()
    if membership is None:
        session.add(CourseMembership(
            course_id=course_id,
            user_id=owner_user_id,
            role=CourseRole.OWNER,
            status=MembershipStatus.ACTIVE,
            analytics_excluded=True,
        ))
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    if capability is None:
        session.add(CourseCapability(course_id=course_id, **DEFAULT_NEW_COURSE_CAPABILITIES))


def activate_student_membership(session: Session, course_id: int, student_user_id: int) -> None:
    """Create or reactivate the membership paired with a student enrolment."""
    membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.course_id == course_id,
            CourseMembership.user_id == student_user_id,
        )
    ).first()
    if membership is None:
        session.add(CourseMembership(
            course_id=course_id,
            user_id=student_user_id,
            role=CourseRole.STUDENT,
            status=MembershipStatus.ACTIVE,
            analytics_excluded=False,
        ))
        return
    if membership.role == CourseRole.STUDENT:
        membership.status = MembershipStatus.ACTIVE
        membership.analytics_excluded = False
        membership.left_at = None
        membership.updated_at = utcnow_aware()
        session.add(membership)


def _participation_mode(role: CourseRole, analytics_excluded: bool) -> tuple[ParticipationMode, bool]:
    if role == CourseRole.STUDENT and not analytics_excluded:
        return ParticipationMode.LEARNER, True
    if role in {CourseRole.OWNER, CourseRole.TEACHER}:
        return ParticipationMode.TEACHER_PREVIEW, False
    if role == CourseRole.TEACHING_ASSISTANT:
        return ParticipationMode.STAFF_TEST, False
    return ParticipationMode.OBSERVER, False


def resolve_course_access(session: Session, current_user: dict[str, Any], course_id: int) -> CourseAccessContext:
    """Return the effective access decision without any legacy fallback."""
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在")

    user_id = int(current_user["user_id"])
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账户不可用")

    platform_permissions = _platform_permissions(session, user_id)
    capabilities = _capability_values(session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first())
    membership = session.exec(
        select(CourseMembership).where(
            CourseMembership.user_id == user_id,
            CourseMembership.course_id == course_id,
        )
    ).first()
    platform_permissions_for_course = _platform_course_permissions(platform_permissions)

    if membership is None or membership.status != MembershipStatus.ACTIVE:
        return CourseAccessContext(
            course_id=course_id,
            user_id=user_id,
            role=None,
            membership_status=membership.status if membership else None,
            permissions=platform_permissions_for_course,
            capabilities=capabilities,
            platform_permissions=platform_permissions,
            analytics_eligible=False,
            participation_mode=None,
        )

    grants, denies = _override_sets(membership.permission_overrides)
    permissions = (set(ROLE_PERMISSIONS[membership.role]) | grants | set(platform_permissions_for_course)) - denies
    participation_mode, analytics_eligible = _participation_mode(membership.role, membership.analytics_excluded)
    return CourseAccessContext(
        course_id=course_id,
        user_id=user_id,
        role=membership.role,
        membership_status=membership.status,
        permissions=frozenset(permissions),
        capabilities=capabilities,
        platform_permissions=platform_permissions,
        analytics_eligible=analytics_eligible,
        participation_mode=participation_mode,
    )


def require_course_permission(session: Session, current_user: dict[str, Any], course_id: int, permission: str) -> CourseAccessContext:
    context = resolve_course_access(session, current_user, course_id)
    if not context.allows(permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="课程权限不足")
    return context


def course_permission(permission: str):
    """Create a FastAPI dependency for routes whose path contains course_id.

    The dependency is deliberately parameter-name agnostic beyond the stable
    ``course_id`` route contract, so endpoint code receives an already-scoped
    access context instead of repeating identity and role checks.
    """
    from app.core.security import get_current_user
    from app.models.database import get_session

    async def dependency(
        request: Request,
        session: Session = Depends(get_session),
        current_user: dict = Depends(get_current_user),
    ) -> CourseAccessContext:
        raw_course_id = request.path_params.get("course_id") or request.query_params.get("course_id")
        if raw_course_id is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="权限依赖缺少 course_id")
        return require_course_permission(session, current_user, int(raw_course_id), permission)

    return dependency


def serialize_access_context(context: CourseAccessContext, requested: Iterable[str] | None = None) -> dict[str, Any]:
    visible_permissions = sorted(set(requested or ALL_PERMISSIONS))
    return {
        "course_id": context.course_id,
        "course_role": context.role.value if context.role else None,
        "membership_status": context.membership_status.value if context.membership_status else None,
        "permissions": sorted(context.permissions),
        "allowed": {permission: context.allows(permission) for permission in visible_permissions},
        "capabilities": context.capabilities,
        "platform_permissions": sorted(context.platform_permissions),
        "analytics_eligible": context.analytics_eligible,
        "participation_mode": context.participation_mode.value if context.participation_mode else None,
    }
