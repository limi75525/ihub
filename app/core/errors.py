"""领域错误基类：services 层对外抛、main.py 统一映射为 HTTP 响应。

services 层不得直接 raise fastapi.HTTPException；
SeedError 继承本类以复用统一映射。detail 属性与 HTTPException.detail 同名，
调用方从 except HTTPException 迁移时错误文案取法不变。
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class UpstreamError(Exception):
    """上游/配置类领域错误。status_code 供 API 层映射为 HTTP 状态。"""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    @property
    def detail(self) -> str:
        return self.message


async def domain_error_handler(request: Request, exc: UpstreamError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})
