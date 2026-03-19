from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import uuid

# 规范要求的统一响应格式
def unified_response(code: int, msg: str, data: any = None):
    return {
        "code": code,
        "msg": msg,
        "data": data if data is not None else {},
        "requestId": f"req{uuid.uuid4().hex[:16]}"
    }

# 全局异常处理器
async def global_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=unified_response(
            code=exc.status_code,
            msg=exc.detail,
            data=None
        )
    )

# 通用业务异常类
class BusinessException(HTTPException):
    def __init__(self, code: int, msg: str):
        super().__init__(status_code=code, detail=msg)