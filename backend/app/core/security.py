import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt

from app.core.config import settings, UserRole

logger = logging.getLogger(__name__)

pwd_context = bcrypt
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/user/login", auto_error=False)


# --------------------------
# 2. 规范强制：MD5签名校验核心实现
# --------------------------
def _sort_params(params: Dict[str, Any]) -> str:
    """严格按规范：ASCII升序排列非空参数，排除enc"""
    filtered_params = {
        k: str(v)
        for k, v in params.items()
        if k != "enc" and v is not None and str(v).strip() != ""
    }
    sorted_keys = sorted(filtered_params.keys())
    result = "".join([f"{k}{filtered_params[k]}" for k in sorted_keys])
    
    logger.debug("MD5签名校验 - 原始参数: %s", params)
    logger.debug("MD5签名校验 - 过滤后参数: %s", filtered_params)
    logger.debug("MD5签名校验 - 排序后键: %s", sorted_keys)
    logger.debug("MD5签名校验 - 拼接字符串: %s", result)

    return result


def _verify_signature_core(params: Dict[str, Any], time_str: str, enc: str) -> bool:
    """签名校验核心逻辑"""
    # 校验时间格式
    try:
        request_time = datetime.strptime(time_str, settings.TIME_FORMAT)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="签名验证失败：time格式必须为yyyy-MM-dd HH:mm:ss",
        )
    # 防重放攻击
    server_time = datetime.now()
    time_diff = abs((server_time - request_time).total_seconds() / 60)
    if time_diff > settings.SIGN_TIMEOUT_MINUTES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"签名验证失败：请求超时，有效期{settings.SIGN_TIMEOUT_MINUTES}分钟",
        )

    # 计算签名
    sorted_str = _sort_params(params)
    raw_sign = f"{sorted_str}{settings.STATIC_KEY}{time_str}"
    calculated_enc = hashlib.md5(raw_sign.encode("utf-8")).hexdigest().upper()
    
    logger.debug("MD5签名校验 - 原始签名串: %s", raw_sign)
    logger.debug("MD5签名校验 - 计算的签名: %s", calculated_enc)
    logger.debug("MD5签名校验 - 收到的签名: %s", enc.upper())
    logger.debug("MD5签名校验 - 签名匹配: %s", calculated_enc == enc.upper())
    
    return calculated_enc == enc.upper()


async def verify_request_signature(request: Request):

    current_path = request.url.path
    logger.debug("MD5签名校验 - 收到请求: %s %s", request.method, current_path)

    if any(current_path.startswith(path) for path in settings.NO_AUTH_WHITELIST):
        logger.debug("MD5签名校验 - 白名单路径，跳过验证")
        return True

    # ----------------------------------分割线--------------------------------

    """【全局依赖】所有接口强制签名校验"""
    all_params = {}
    # 获取GET参数
    all_params.update(dict(request.query_params))
    # 获取POST参数
    if request.method in ["POST", "PUT", "DELETE"]:
        content_type = request.headers.get("content-type", "")
        logger.debug("MD5签名校验 - Content-Type: %s", content_type)
        if "application/json" in content_type:
            try:
                body_json = await request.json()
                logger.debug("MD5签名校验 - POST JSON 数据: %s", body_json)
                all_params.update(body_json)
            except Exception as e:
                logger.debug("MD5签名校验 - 读取 JSON 失败: %s", e)
        elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form_data = await request.form()
            all_params.update(dict(form_data))

    logger.debug("MD5签名校验 - 所有参数: %s", all_params)

    # 校验必填参数
    time_str = all_params.get("time")
    enc = all_params.get("enc")
    if not time_str or not enc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="签名验证失败：缺少必填参数time或enc",
        )

    # 执行验签
    if not _verify_signature_core(all_params, time_str, enc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="签名验证失败：签名不匹配"
        )
    return True


# --------------------------
# 3. JWT身份认证实现
# --------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    return pwd_context.hashpw(password.encode("utf-8"), pwd_context.gensalt()).decode(
        "utf-8"
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), request: Request = None
):
    """【身份认证依赖】获取当前登录用户

    支持两种token传递方式：
    1. Authorization: Bearer <token> 请求头（标准OAuth2方式）
    2. ?token=<token> URL查询参数（用于视频/音频等浏览器直接发起的请求）
    """
    if request and request.url.path in settings.NO_AUTH_WHITELIST:
        return None

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="身份认证失败：无效的访问令牌",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 优先从Header获取，其次从Query参数获取（支持浏览器直接访问的媒体资源）
    if not token and request:
        token = request.query_params.get("token")

    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
        user_role: Optional[str] = payload.get("role")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # 模拟用户数据（实际项目中替换为数据库查询）
    return {
        "user_id": user_id,
        "username": payload.get("username", "user"),
        "role": user_role,
        "school_id": payload.get("school_id", "sch10001"),
    }


# --------------------------
# 4. RBAC权限控制
# --------------------------
def role_required(allowed_roles: List[UserRole]):
    """【权限依赖工厂】生成角色校验依赖"""

    async def check_role(
        current_user=Depends(get_current_user), request: Request = None
    ):
        if request and request.url.path in settings.NO_AUTH_WHITELIST:
            return None
        if current_user["role"] not in [role.value for role in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足：您的角色无权访问此接口",
            )
        return current_user

    return check_role


# 预定义常用权限依赖
teacher_only = role_required([UserRole.TEACHER, UserRole.ADMIN])
student_only = role_required([UserRole.STUDENT, UserRole.ADMIN])


# --------------------------
# 便捷身份提取依赖（消除样板代码）
# --------------------------
async def _get_user_id(current_user: dict = Depends(get_current_user)) -> int:
    """直接返回当前用户 ID（int），替代重复的 int(current_user["user_id"])"""
    return int(current_user["user_id"])


async def _get_username(current_user: dict = Depends(get_current_user)) -> str:
    """直接返回当前用户名，替代重复的 current_user.get("username", "user")"""
    return current_user.get("username", "user")


async def _get_user_identity(current_user: dict = Depends(get_current_user)) -> tuple[int, str]:
    """同时返回 (user_id, username) 元组"""
    return int(current_user["user_id"]), current_user.get("username", "user")
teacher_student_allowed = role_required([UserRole.TEACHER, UserRole.STUDENT, UserRole.ADMIN])
admin_only = role_required([UserRole.ADMIN])
