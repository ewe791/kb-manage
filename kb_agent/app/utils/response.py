"""统一响应封装：{code, message, data}。code=0 表示成功。"""
from typing import Any

from fastapi.responses import JSONResponse


class BizError(Exception):
    def __init__(self, message: str, code: int = 400, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def ok(data: Any = None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def page_data(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "code": 0,
        "message": "success",
        "data": {"items": items, "total": total, "page": page, "page_size": page_size},
    }


def error_response(code: int, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message, "data": None})
