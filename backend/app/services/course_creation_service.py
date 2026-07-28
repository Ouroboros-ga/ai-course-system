"""Creation service for an empty course-building workspace."""
from __future__ import annotations

import uuid

from sqlmodel import Session

from app.models.course_model import Course, CourseStatus
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_build_service import course_build_service
from app.services.course_lifecycle_service import course_settings_service


class CourseCreationService:
    def create_empty_course(
        self,
        session: Session,
        *,
        owner_user_id: int,
        title: str,
        description: str = "",
        subject: str = "",
        course_type: str = "",
        teaching_audience: str = "",
        language: str = "zh-CN",
    ) -> dict:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("课程名称不能为空")

        course = Course(
            fanya_course_id=f"local_{uuid.uuid4().hex[:12]}",
            fanya_course_name=clean_title,
            title=clean_title,
            description=description.strip() or None,
            teacher_id=owner_user_id,
            status=CourseStatus.DRAFT,
            is_ai_generated=False,
        )
        session.add(course)
        session.flush()

        # A newly created course is usable immediately only after this baseline
        # has created its owner membership and default capability record.
        establish_course_access_baseline(session, course.id, owner_user_id)
        draft = course_build_service.get_or_create_draft(
            session,
            course_id=course.id,
            actor_user_id=owner_user_id,
        )
        settings = course_settings_service.update_section(
            session,
            course_id=course.id,
            section="profile",
            patch={
                "title": clean_title,
                "description": description.strip(),
                "subject": subject.strip(),
                "course_type": course_type.strip(),
                "teaching_audience": teaching_audience.strip(),
                "language": language.strip() or "zh-CN",
            },
            actor_user_id=owner_user_id,
        )
        return {
            "course_id": course.id,
            "status": course.status.value,
            "title": course.title,
            "draft_id": draft.draft_id,
            "current_step": draft.current_step.value,
            "setting_version_id": settings.setting_version_id,
            "profile": settings.profile,
        }


course_creation_service = CourseCreationService()
