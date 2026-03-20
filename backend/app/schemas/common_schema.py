
from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Optional

# 统一响应基础模型
class UnifiedResponse(BaseModel):
    code: int
    msg: str
    data: Any = {}
    requestId: str

# 登录请求模型
class LoginRequest(BaseModel):
    username: str
    password: str

# 登录响应模型
class LoginResponseData(BaseModel):
    internalUserId: str
    syncStatus: str
    authToken: str

class LoginResponse(UnifiedResponse):
    data: LoginResponseData