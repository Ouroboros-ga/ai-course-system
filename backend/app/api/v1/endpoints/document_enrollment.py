"""
选课、学生管理、统计、幻灯片 API
"""

from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from sqlmodel import Session, select, text, func

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, _get_user_id
from app.models.database import get_session
from app.models.course_model import (
    Course, ScriptNode, StudentEnrollment,
    CourseStatus, LearningProgress, UnderstandingLevel,
)
from app.models.user_model import User
from .document_utils import get_enrolled_course, PPT_SLIDES_DIR

router = APIRouter(prefix="/document", tags=["选课与统计"])

# 以下端点从 document.py 原位迁移：
# - POST /course/{course_id}/enroll     (line ~1553)
# - POST /course/{course_id}/unenroll   (line ~1725)
# - GET /my-courses                     (line ~1760)
# - GET /course/{course_id}/students    (line ~1830)
# - GET /course/{course_id}/stats       (line ~1943)
# - GET /course/{course_id}/slides      (line ~2106)
# - GET /course/{course_id}/slide/{page_num} (line ~2249)
