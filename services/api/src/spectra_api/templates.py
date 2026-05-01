"""Shared Jinja2Templates instance for API-owned web UI."""

from fastapi.templating import Jinja2Templates

from spectra_api.paths import template_directory
from spectra_common.constants import format_feature_label
from spectra_platform._meta.version import __version__
from spectra_platform.core.config import settings

templates = Jinja2Templates(directory=str(template_directory()))
templates.env.auto_reload = settings.DEBUG
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["version"] = __version__
templates.env.filters["feature_label"] = format_feature_label
