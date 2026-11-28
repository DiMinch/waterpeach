from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Business error rendered as ``{"detail": ..., "error_code": ...}`` (contract 1.3)."""

    def __init__(self, status_code: int, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


def not_found(error_code: str, detail: str) -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, error_code, detail)


def forbidden(error_code: str, detail: str) -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, error_code, detail)


def conflict(error_code: str, detail: str) -> AppError:
    return AppError(status.HTTP_409_CONFLICT, error_code, detail)


def bad_request(error_code: str, detail: str) -> AppError:
    return AppError(status.HTTP_400_BAD_REQUEST, error_code, detail)


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
