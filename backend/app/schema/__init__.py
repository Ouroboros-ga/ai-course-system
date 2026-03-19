# app/schemas/__init__.py
"""
Pydantic数据校验模型模块
统一导出所有请求/响应模型
"""

from .common_schema import (
    UnifiedResponse,
    LoginRequest,
    LoginResponse,
    LoginResponseData
)
from .user_schema import UserCreate, UserUpdate, UserResponse
from .smart_course_schema import (
    LessonParseRequest,
    LessonParseResponse,
    GenerateScriptRequest,
    GenerateScriptResponse
)
from .qa_schema import (
    QaInteractRequest,
    QaInteractResponse,
    VoiceToTextRequest,
    VoiceToTextResponse
)
from .progress_schema import (
    TrackProgressRequest,
    TrackProgressResponse,
    AdjustProgressRequest,
    AdjustProgressResponse
)

__all__ = [
    "UnifiedResponse",
    "LoginRequest",
    "LoginResponse",
    "LoginResponseData",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "LessonParseRequest",
    "LessonParseResponse",
    "GenerateScriptRequest",
    "GenerateScriptResponse",
    "QaInteractRequest",
    "QaInteractResponse",
    "VoiceToTextRequest",
    "VoiceToTextResponse",
    "TrackProgressRequest",
    "TrackProgressResponse",
    "AdjustProgressRequest",
    "AdjustProgressResponse"
]