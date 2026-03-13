"""Inter-service authentication via shared secret."""

import hmac

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """Validate X-Service-Auth header for inter-service requests.

    Only applied to internal service endpoints (ai_service, scheduler, worker).
    Skips validation for /health endpoints and when no secret is configured.
    """

    def __init__(self, app, secret: str = ""):
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/healthz"):
            return await call_next(request)

        if not self.secret:
            return await call_next(request)

        provided = request.headers.get("X-Service-Auth", "")
        if not hmac.compare_digest(provided, self.secret):
            raise HTTPException(status_code=401, detail="Invalid service auth")

        return await call_next(request)
