from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import traceback
import functools


def unified_response(code: int, message: str, data: any = None):
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else None,
    }


def shadow_response(code: int, message: str, data: any = None, *, kind: str = "shadow", note: str = ""):
    """Unified response that explicitly marks data as non-official (shadow/demo/mock/research).

    批次0要求：不把 Shadow、研究功能、Mock 数据标成正式功能。
    """
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else None,
        "provenance": {"kind": kind, "is_official": False, "note": note},
    }


async def global_exception_handler(request: Request, exc: HTTPException):
    # Keep the public envelope stable: ``message`` is always display text and
    # structured machine-readable rejection details live in ``data``.
    # Several Phase B--E endpoints use an error_code to let the frontend offer
    # a precise recovery action instead of parsing a human-facing message.
    if isinstance(exc.detail, dict):
        detail = exc.detail
        return JSONResponse(
            status_code=exc.status_code,
            content=unified_response(
                code=exc.status_code,
                message=str(detail.get("message") or "请求被拒绝"),
                data=detail,
            ),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=unified_response(code=exc.status_code, message=exc.detail, data=None),
    )


class BusinessException(HTTPException):
    def __init__(self, code: int, message: str):
        super().__init__(status_code=code, detail=message)


# ---------------------------------------------------------------------------
# 统一错误码工厂（阶段0）
# 与 PageDesign前端API契约规划.md §1.3 对齐：每个错误码对应明确的 HTTP 与前端行为。
# 路由调用 reject(...) 抛出 HTTPException，detail 形如
# {"error_code": "VALIDATION_FAILED", "message": "...", "details": {...}}
# global_exception_handler 会把它放进响应 data，前端按 error_code 路由恢复动作。
# ---------------------------------------------------------------------------

def reject(status_code: int, error_code: str, message: str, *, details: dict | None = None) -> None:
    """Raise a structured HTTPException aligned with the unified error contract.

    任何课程接口在权限/状态/依赖失败时调用此函数，而不是返回 200+错误文案。
    """
    payload: dict = {"error_code": error_code, "message": message}
    if details:
        payload["details"] = details
    raise HTTPException(status_code=status_code, detail=payload)


def reject_auth_required(message: str = "需要登录") -> None:
    reject(401, "AUTH_REQUIRED", message)


def reject_course_access_denied(message: str = "课程访问被拒绝") -> None:
    reject(403, "COURSE_ACCESS_DENIED", message)


def reject_capability_disabled(message: str = "课程未启用该能力") -> None:
    reject(403, "CAPABILITY_DISABLED", message)


def reject_course_not_found(message: str = "课程不存在") -> None:
    reject(404, "COURSE_NOT_FOUND", message)


def reject_resource_not_found(message: str = "资源不存在") -> None:
    reject(404, "RESOURCE_NOT_FOUND", message)


def reject_version_conflict(message: str = "资源版本冲突", *, details: dict | None = None) -> None:
    reject(409, "VERSION_CONFLICT", message, details=details)


def reject_state_conflict(message: str = "状态冲突", *, details: dict | None = None) -> None:
    reject(409, "STATE_CONFLICT", message, details=details)


def reject_validation_failed(message: str = "请求参数校验失败", *, details: dict | None = None) -> None:
    reject(422, "VALIDATION_FAILED", message, details=details)


def reject_budget_exceeded(message: str = "预算超限，请稍后重试") -> None:
    reject(429, "BUDGET_EXCEEDED", message)


def reject_dependency_unavailable(message: str = "外部依赖不可用，已降级") -> None:
    reject(503, "DEPENDENCY_UNAVAILABLE", message)


def handle_api_errors(default_message: str = "操作失败", log_prefix: str = ""):
    """
    API 端点异常处理装饰器

    用法：
        @router.get("/xxx")
        @handle_api_errors("获取数据失败", "[数据接口]")
        async def get_xxx(...):
            # 不需要 try/except，直接写业务逻辑
            return unified_response(code=200, ...)

    效果：自动捕获 Exception 并返回统一格式的错误响应，
         同时打印完整堆栈到日志（便于调试）。
    """
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            except HTTPException:
                raise
            except BusinessException:
                raise
            except Exception as e:
                if log_prefix:
                    print(f"[{log_prefix}] 异常: {e}")
                traceback.print_exc()
                return unified_response(code=500, message=f"{default_message}: {str(e)}", data={"error": str(e)})

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                return result
            except HTTPException:
                raise
            except BusinessException:
                raise
            except Exception as e:
                if log_prefix:
                    print(f"[{log_prefix}] 异常: {e}")
                traceback.print_exc()
                return unified_response(code=500, message=f"{default_message}: {str(e)}", data={"error": str(e)})

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    import asyncio
    return decorator
