# app/core/signature_middleware.py
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings


class SignatureMiddleware(BaseHTTPMiddleware):
    """签名验证中间件 - 使用 BaseHTTPMiddleware 可以正确处理请求体"""

    def __init__(self, app, whitelist_paths: Optional[list] = None):
        super().__init__(app)
        self.whitelist_paths = whitelist_paths or settings.NO_AUTH_WHITELIST

    async def dispatch(self, request: Request, call_next):
        current_path = request.url.path

        # Optional external adapters may own a reference protocol with a
        # different signature canonicalisation and response envelope.  The
        # adapter registration is runtime state, not a permanent whitelist:
        # if the optional package is absent there is no bypass.
        signature_owned_prefixes = getattr(
            request.app.state, "signature_owned_path_prefixes", ()
        )
        if any(current_path.startswith(path) for path in signature_owned_prefixes):
            return await call_next(request)

        # 白名单路径跳过验证
        if any(current_path.startswith(path) for path in self.whitelist_paths):
            return await call_next(request)

        # GET请求的媒体资源路径跳过签名验证（仍需JWT认证）
        if request.method == "GET" and any(
            current_path.startswith(p) for p in getattr(settings, 'MEDIA_RESOURCE_PATHS', [])
        ):
            return await call_next(request)

        # 获取查询参数
        all_params = dict(request.query_params)

        # 对于 POST/PUT/DELETE 请求，读取请求体
        if request.method in ["POST", "PUT", "DELETE"]:
            content_type = request.headers.get("content-type", "")

            if "application/json" in content_type:
                # 读取请求体
                body = await request.body()
                if body:
                    try:
                        body_json = json.loads(body.decode("utf-8"))
                        all_params.update(body_json)

                        # 重要：重新构建请求，让后续处理器能读取请求体
                        async def receive():
                            return {"type": "http.request", "body": body}

                        request = Request(request.scope, receive, request._send)
                    except json.JSONDecodeError:
                        return JSONResponse(
                            status_code=403,
                            content={"code": 403, "message": "签名验证失败：无效的JSON格式", "data": None}
                        )
            elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                form_data = await request.form()
                all_params.update(dict(form_data))

        # 校验必填参数
        time_str = all_params.get("time")
        enc = all_params.get("enc")

        if not time_str or not enc:
            return JSONResponse(
                status_code=403,
                content={"code": 403, "message": "签名验证失败：缺少必填参数time或enc", "data": None}
            )

        # 执行验签
        if not self._verify_signature(all_params, time_str, enc):
            return JSONResponse(
                status_code=403,
                content={"code": 403, "message": "签名验证失败：签名不匹配", "data": None}
            )

        # 验签通过，继续处理请求
        return await call_next(request)

    def _verify_signature(self, params: Dict[str, Any], time_str: str, enc: str) -> bool:
        """签名校验核心逻辑"""
        # 校验时间格式
        try:
            request_time = datetime.strptime(time_str, settings.TIME_FORMAT)
        except ValueError:
            return False

        # 防重放攻击
        server_time = datetime.now()
        time_diff = abs((server_time - request_time).total_seconds() / 60)
        if time_diff > settings.SIGN_TIMEOUT_MINUTES:
            return False

        # 计算签名
        sorted_str = self._sort_params(params)
        raw_sign = f"{sorted_str}{settings.STATIC_KEY}{time_str}"
        calculated_enc = hashlib.md5(raw_sign.encode("utf-8")).hexdigest().upper()

        return calculated_enc == enc.upper()

    def _sort_params(self, params: Dict[str, Any]) -> str:
        """严格按规范：ASCII升序排列非空参数，排除enc"""
        filtered_params = {
            k: str(v)
            for k, v in params.items()
            if k != "enc" and v is not None and str(v).strip() != ""
        }
        sorted_keys = sorted(filtered_params.keys())
        result = "".join([f"{k}{filtered_params[k]}" for k in sorted_keys])

        return result
