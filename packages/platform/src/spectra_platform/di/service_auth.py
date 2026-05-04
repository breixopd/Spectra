"""Inter-service authentication via shared secret."""

import hmac

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


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
            raise HTTPException(status_code=401, detail="Service authentication not configured")

        provided = request.headers.get("X-Service-Auth", "")
        if not hmac.compare_digest(provided, self.secret):
            raise HTTPException(status_code=401, detail="Invalid service auth")

        return await call_next(request)
