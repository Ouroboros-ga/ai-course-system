"""
TTS 语音合成 API
文本转语音、音频服务、合成状态查询
"""

from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.schemas.common_schema import UnifiedResponse
from app.core.exceptions import unified_response
from app.core.security import get_current_user, teacher_only, _get_user_id
from app.models.database import get_session
from app.models.course_model import Course, ScriptNode, CourseScript
from .document_utils import get_course_audio_dir, cleanup_old_node_audio, tts_generation_status, AUDIO_STORAGE_DIR

router = APIRouter(prefix="/document", tags=["TTS语音"])

# 以下端点从 document.py 原位迁移：
# - POST /tts/synthesize          (line ~928)
# - GET /tts/health               (line ~1040)
# - GET /course/{course_id}/tts-status (line ~1074)
# - POST /course/{course_id}/node/{node_id}/synthesize-audio (line ~2270)
# - GET /audio/{course_id}/{filename}   (line ~2359)
# - POST /course/{course_id}/synthesize-all-audio (line ~2395)

# 迁移说明：将上述 endpoint 的函数体从 document.py 移至此文件，
# 使用上方定义的 router 实例。
