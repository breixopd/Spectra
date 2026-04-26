"""Shared Jinja2Templates instance for all routers."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.requests import Request

from app.core.config import settings
from app.core.constants import format_feature_label
from app.version import __version__

_APP_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _APP_DIR / "templates"


class SpectraTemplates(Jinja2Templates):
    """Keep existing TemplateResponse(name, context) calls working on new Starlette."""

    def TemplateResponse(
        self,
        request: Request | str,
        name: str | dict[str, Any],
        context: dict[str, Any] | None = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ):
        if isinstance(request, str) and isinstance(name, dict):
            template_name = request
            template_context = name if context is None else context
            template_request = template_context.get("request")
            if not isinstance(template_request, Request):
                raise ValueError("Template context must include a Request under 'request'")
            return super().TemplateResponse(
                template_request,
                template_name,
                template_context,
                status_code=status_code,
                headers=headers,
                media_type=media_type,
                background=background,
            )
        return super().TemplateResponse(
            request,
            name,
            context,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )


templates = SpectraTemplates(directory=str(_TEMPLATES_DIR))
templates.env.auto_reload = settings.DEBUG
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["version"] = __version__
templates.env.filters["feature_label"] = format_feature_label
