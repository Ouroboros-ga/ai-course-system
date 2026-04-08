"""
服务层
负责业务逻辑和Prompt构造
"""

from app.services.smart_course_service import smart_course_service, SmartCourseService, ScriptPromptBuilder
from app.services.qa_service import qa_service, QAService, QAPromptBuilder
from app.services.progress_service import progress_service, ProgressService, ProgressPromptBuilder

__all__ = [
    "smart_course_service",
    "SmartCourseService",
    "ScriptPromptBuilder",
    "qa_service",
    "QAService",
    "QAPromptBuilder",
    "progress_service",
    "ProgressService",
    "ProgressPromptBuilder",
]
