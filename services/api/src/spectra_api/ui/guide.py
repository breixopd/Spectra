"""Authenticated product guidance and API documentation pages.

The generated OpenAPI schema is deliberately kept behind the normal user
authentication boundary.  This gives operators a useful in-product API
reference without publishing endpoint names, models, or operational metadata
to unauthenticated visitors in production.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from spectra_api.api.dependencies import get_current_active_user
from spectra_api.templates import templates
from spectra_common.config import settings
from spectra_persistence.models.user import User

router = APIRouter(
    dependencies=[Depends(get_current_active_user)],
    tags=["Product guide"],
)


@router.get("/docs/api", response_class=HTMLResponse, include_in_schema=False)
async def api_docs_page() -> HTMLResponse:
    """Render the authenticated Swagger UI for the Core API."""
    return get_swagger_ui_html(
        openapi_url="/docs/api/openapi.json",
        title=f"{settings.APP_NAME} API Documentation",
        swagger_ui_parameters={
            "syntaxHighlight.theme": "obsidian",
            "tryItOutEnabled": True,
            "displayRequestDuration": True,
            "defaultModelsExpandDepth": -1,
            "docExpansion": "none",
            "filter": True,
            "persistAuthorization": True,
            "deepLinking": True,
        },
    )


@router.get("/docs/api/openapi.json", include_in_schema=False)
async def private_openapi_schema(request: Request, _user: User = Depends(get_current_active_user)):
    """Return the generated schema only to authenticated users."""
    return JSONResponse(request.app.openapi())


@router.get("/help", response_class=HTMLResponse, include_in_schema=False)
async def help_page(request: Request, _user: User = Depends(get_current_active_user)) -> HTMLResponse:
    """Render the in-product getting-started guide."""
    return templates.TemplateResponse(
        request,
        "help.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "is_public_page": False,
            "page_width": "wide",
        },
    )
