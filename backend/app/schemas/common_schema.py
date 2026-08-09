from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Optional


class Provenance(BaseModel):
    """Data provenance marker for shadow/research/demo/mock responses.

    批次0要求：不把 Shadow、研究功能、Mock 数据标成正式功能。
    任何返回非正式（shadow/demo/mock/research/experimental）数据的端点
    必须附带 provenance，使前端与运维能区分正式数据与试验数据。
    """
    kind: str  # "shadow" | "demo" | "mock" | "research" | "experimental"
    is_official: bool = False
    note: str = ""


class UnifiedResponse(BaseModel):
    code: int
    message: str
    data: Any = None
    provenance: Optional[Provenance] = None


class UserInfo(BaseModel):
    id: str
    username: str = ""
    role: str = "user"
    platform_permissions: list[str] = Field(default_factory=list)


class LoginResponseData(BaseModel):
    token: str
    userInfo: UserInfo


class LoginRequest(BaseModel):
    # Keep the request field for existing clients.  Its value may be either a
    # username or the numeric platform user ID.
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)


class LoginResponse(UnifiedResponse):
    data: Optional[LoginResponseData] = None


class ModifyUserRequest(BaseModel):
    """用户信息修改请求"""
    id: str
    username: str
    password: str
    newUsername: str = ""
    newPassword: str = ""


class ProfileUpdateRequest(BaseModel):
    """Authenticated self-service profile update.

    The numeric account ID never changes.  ``username`` is the single
    user-facing login and display name.  A password change always requires the
    current password.
    """

    username: Optional[str] = Field(default=None, max_length=50)
    current_password: Optional[str] = Field(default=None, min_length=1, max_length=200)
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=200)
