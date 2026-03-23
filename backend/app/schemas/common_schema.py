from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Optional


class UnifiedResponse(BaseModel):
    code: int
    message: str
    data: Any = None


class UserInfo(BaseModel):
    id: str
    username: str = ""


class LoginResponseData(BaseModel):
    token: str
    userInfo: UserInfo


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginResponse(UnifiedResponse):
    data: Optional[LoginResponseData] = None


class ModifyUserRequest(BaseModel):
    """用户信息修改请求"""
    id: str
    username: str
    password: str
    newUsername: str = ""
    newPassword: str = ""
