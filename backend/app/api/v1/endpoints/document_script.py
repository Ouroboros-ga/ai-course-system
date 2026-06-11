"""
脚本版本管理 API
脚本快照、版本历史、回滚
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Body
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_only, _get_user_id
from app.models.database import get_session
from app.models.course_model import Course, CourseScript
from .document_utils import verify_course_owner

router = APIRouter(prefix="/document", tags=["脚本管理"])

# 以下端点从 document.py 原位迁移：
# - POST /course/{course_id}/script/snapshot    (line ~1128)
# - GET /course/{course_id}/script/versions      (line ~1223)
# - POST /course/{course_id}/script/rollback/{script_id} (line ~1259)
