"""Business errors shared by feature services and HTTP handlers."""

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unavailable(AppError):
    status_code = 503
    code = "unavailable"


async def app_error_handler(_request: Request, error: AppError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"code": error.code, "detail": error.message})
