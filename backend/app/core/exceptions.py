from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse


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
