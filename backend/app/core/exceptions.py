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


async def global_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=unified_response(code=exc.status_code, message=exc.detail, data=None),
    )


class BusinessException(HTTPException):
    def __init__(self, code: int, message: str):
        super().__init__(status_code=code, detail=message)


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
