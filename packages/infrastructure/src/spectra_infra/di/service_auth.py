"""Inter-service authentication via shared secret."""

import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """Validate X-Service-Auth header for inter-service requests.

    Used on AI, scheduler, and worker HTTP servers. Lightweight probes may omit
    the header only for ``/health`` and ``/healthz``. When no shared secret is
    configured, all other routes fail closed (401).
    """

    def __init__(self, app, secret: str = ""):
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/healthz"):
            return await call_next(request)

        if not self.secret:
            return JSONResponse(status_code=401, content={"detail": "Service authentication not configured"})

        provided = request.headers.get("X-Service-Auth", "")
        if not hmac.compare_digest(provided, self.secret):
            return JSONResponse(status_code=401, content={"detail": "Invalid service auth"})

        return await call_next(request)
