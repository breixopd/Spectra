"""Shared Jinja2Templates instance for all routers."""

from pathlib import Path

from fastapi.templating import Jinja2Templates
from spectra_common.constants import format_feature_label

from app._meta.version import __version__
from app.core.config import settings

_APP_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _APP_DIR.parent / "templates"


templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.auto_reload = settings.DEBUG
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["version"] = __version__
templates.env.filters["feature_label"] = format_feature_label
