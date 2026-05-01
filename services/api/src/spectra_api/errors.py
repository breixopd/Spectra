"""HTTP exception handlers (HTML vs JSON) and standardized error payloads."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from starlette.responses import Response as StarletteResponse

from spectra_api.api.schemas.common import ErrorResponse
from spectra_common.errors import SpectraError, get_status_code_for_exception
from spectra_platform.auth.rate_limit import rate_limit_exceeded_handler_sync

logger = logging.getLogger(__name__)


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and not request.url.path.startswith("/api/")


def make_error_handler(
    templates: Jinja2Templates,
    status_code: int,
    default_detail: str,
    template: str,
    log: bool = False,
):
    async def handler(request: Request, exc: Exception) -> StarletteResponse:
        if log:
            logger.exception("Internal server error: %s", exc)

        detail = getattr(exc, "detail", None) or default_detail
        if status_code >= 500:
            detail = default_detail
        if not isinstance(detail, str):
            detail = str(detail)

        if status_code == 429 and request.url.path.startswith("/api/"):
            if isinstance(exc, RateLimitExceeded):
                return rate_limit_exceeded_handler_sync(request, exc)
            exc_headers = getattr(exc, "headers", None)
            error_response = ErrorResponse(detail=detail, status_code=429)
            return JSONResponse(
                error_response.model_dump(exclude_none=True),
                status_code=429,
                headers=exc_headers,
            )
        if wants_html(request):
            return HTMLResponse(
                content=templates.get_template(template).render(detail=detail),
                status_code=status_code,
            )
        error_response = ErrorResponse(detail=detail, status_code=status_code)
        return JSONResponse(error_response.model_dump(exclude_none=True), status_code=status_code)

    return handler


_ERROR_HANDLERS: list[tuple] = [
    (400, "Bad request", "errors/400.html"),
    (401, "Unauthorized", "errors/401.html"),
    (403, "Forbidden", "errors/403.html"),
    (404, "Not found", "errors/404.html"),
    (405, "Method not allowed", "errors/405.html"),
    (429, "Too many requests", "errors/429.html"),
    (500, "Internal server error", "errors/500.html", True),
    (502, "Bad gateway", "errors/502.html"),
    (503, "Service unavailable", "errors/503.html"),
    (504, "Request timeout", "errors/504.html"),
]


def register_exception_handlers(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.exception_handler(SpectraError)
    async def spectra_error_handler(request: Request, exc: SpectraError) -> HTMLResponse | JSONResponse:
        status_code = get_status_code_for_exception(exc)
        if wants_html(request):
            template_name = f"errors/{status_code}.html"
            try:
                templates.get_template(template_name)
            except Exception:
                logger.debug("Custom template not found, using default", exc_info=True)
                template_name = "errors/500.html"
            detail = exc.message if status_code < 500 else "Something went wrong. Please try again."
            return HTMLResponse(
                content=templates.get_template(template_name).render(detail=detail),
                status_code=status_code,
            )
        error_response = ErrorResponse(
            detail=exc.message,
            status_code=status_code,
            error=exc.code,
        )
        return JSONResponse(
            status_code=status_code,
            content=error_response.model_dump(exclude_none=True),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        detail = "; ".join(f"{e['loc']}: {e['msg']}" for e in errors) if errors else "Validation error"
        error_response = ErrorResponse(detail=detail, status_code=422, error="VALIDATION_ERROR")
        return JSONResponse(
            status_code=422,
            content=error_response.model_dump(exclude_none=True),
        )

    for entry in _ERROR_HANDLERS:
        app.exception_handler(entry[0])(make_error_handler(templates, *entry))
