"""Spectra API ASGI entrypoint."""

import uvicorn

from spectra_api.factory import create_app
from spectra_platform.core.config import settings

app = create_app()

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    uvicorn.run(
        "spectra_api.main:app",
        host="0.0.0.0",
        port=5000,
        reload=settings.DEBUG,
        log_level="info",
    )
