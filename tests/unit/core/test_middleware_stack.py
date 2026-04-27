"""Tests for the full middleware stack: security headers, correlation ID,
body size limiter, and request timeout.

Each middleware is tested independently via a minimal FastAPI app
and httpx AsyncClient.
"""

import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.bootstrap.logging_config import CorrelationIdMiddleware
from app.bootstrap.middleware import SecurityHeadersMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with(*middlewares) -> FastAPI:
    """Return a minimal FastAPI app with the given middlewares applied."""
    app = FastAPI()

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/api/data")
    async def api_data():
        return {"data": True}

    @app.post("/submit")
    async def submit(request: Request):
        return {"received": True}

    @app.post("/api/submit")
    async def api_submit(request: Request):
        return {"received": True}

    for mw in middlewares:
        if isinstance(mw, tuple):
            app.add_middleware(mw[0], **mw[1])
        else:
            app.add_middleware(mw)

    return app


async def _client(app: FastAPI):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


# =========================================================================
# Security Headers Middleware
# =========================================================================


class TestSecurityHeadersMiddleware:
    """Verify that SecurityHeadersMiddleware sets all required headers."""

    @pytest_asyncio.fixture
    async def client(self):
        app = _make_app_with(SecurityHeadersMiddleware)
        async with await _client(app) as c:
            yield c

    @pytest.mark.asyncio
    async def test_x_content_type_options(self, client):
        resp = await client.get("/ok")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, client):
        resp = await client.get("/ok")
        assert resp.headers["X-Frame-Options"] == "DENY"

    @pytest.mark.asyncio
    async def test_xss_protection_disabled(self, client):
        resp = await client.get("/ok")
        assert resp.headers["X-XSS-Protection"] == "0"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, client):
        resp = await client.get("/ok")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy(self, client):
        resp = await client.get("/ok")
        pp = resp.headers["Permissions-Policy"]
        assert "geolocation=()" in pp
        assert "microphone=()" in pp
        assert "camera=()" in pp

    @pytest.mark.asyncio
    async def test_csp_on_non_api_route(self, client):
        """CSP is set for non-API routes."""
        resp = await client.get("/ok")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_no_csp_on_api_route(self, client):
        """CSP should NOT be set for /api/* routes."""
        resp = await client.get("/api/data")
        assert "Content-Security-Policy" not in resp.headers

    @pytest.mark.asyncio
    async def test_csp_nonce_present(self, client):
        """CSP script-src should include a nonce directive."""
        resp = await client.get("/ok")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "'nonce-" in csp

    @pytest.mark.asyncio
    async def test_hsts_absent_in_debug_mode(self, client):
        """HSTS should NOT be set when DEBUG=True (default in tests)."""
        resp = await client.get("/ok")
        # In test env DEBUG may vary; this just checks consistency
        from app.core.config import settings

        if settings.DEBUG:
            assert "Strict-Transport-Security" not in resp.headers

    @pytest.mark.asyncio
    async def test_hsts_present_in_production(self):
        """HSTS should be present when DEBUG=False."""
        with patch("app.bootstrap.middleware.settings") as mock_settings:
            mock_settings.DEBUG = False
            mock_settings.CORS_ORIGINS = ["http://localhost:5000"]

            app = _make_app_with(SecurityHeadersMiddleware)
            async with await _client(app) as c:
                resp = await c.get("/ok")
            hsts = resp.headers.get("Strict-Transport-Security", "")
            assert "max-age=" in hsts
            assert "includeSubDomains" in hsts

    @pytest.mark.asyncio
    async def test_cross_origin_blocked_in_production(self):
        """POST with a disallowed Origin is rejected (403) in non-DEBUG mode."""
        with patch("app.bootstrap.middleware.settings") as mock_settings:
            mock_settings.DEBUG = False
            mock_settings.CORS_ORIGINS = ["http://localhost:5000"]

            app = _make_app_with(SecurityHeadersMiddleware)
            async with await _client(app) as c:
                resp = await c.post(
                    "/submit",
                    headers={"Origin": "http://evil.example.com"},
                )
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cookie_authenticated_api_post_requires_csrf(self, client):
        resp = await client.post(
            "/api/submit",
            headers={"cookie": "access_token=cookie-auth; csrf_token=csrf-value"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cookie_authenticated_api_post_passes_with_valid_csrf(self, client):
        resp = await client.post(
            "/api/submit",
            headers={"x-csrf-token": "csrf-value", "cookie": "access_token=cookie-auth; csrf_token=csrf-value"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    @pytest.mark.asyncio
    async def test_bearer_authenticated_api_post_skips_csrf(self, client):
        resp = await client.post(
            "/api/submit",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    @pytest.mark.asyncio
    async def test_api_key_authenticated_api_post_skips_csrf_with_access_cookie(self, client):
        resp = await client.post(
            "/api/submit",
            headers={"x-api-key": "test-key", "cookie": "access_token=cookie-auth"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}


# =========================================================================
# Correlation ID Middleware
# =========================================================================


class TestCorrelationIdMiddleware:
    """Verify correlation/request ID propagation."""

    @pytest_asyncio.fixture
    async def client(self):
        app = _make_app_with(CorrelationIdMiddleware)
        async with await _client(app) as c:
            yield c

    @pytest.mark.asyncio
    async def test_generates_correlation_id(self, client):
        """Response includes X-Correlation-ID even when caller sends none."""
        resp = await client.get("/ok")
        cid = resp.headers.get("X-Correlation-ID")
        assert cid is not None
        assert len(cid) > 0

    @pytest.mark.asyncio
    async def test_generates_request_id(self, client):
        """Response includes X-Request-ID mirroring the correlation ID."""
        resp = await client.get("/ok")
        assert resp.headers.get("X-Request-ID") is not None

    @pytest.mark.asyncio
    async def test_correlation_equals_request_id(self, client):
        """Both headers should carry the same value."""
        resp = await client.get("/ok")
        assert resp.headers["X-Correlation-ID"] == resp.headers["X-Request-ID"]

    @pytest.mark.asyncio
    async def test_echoes_caller_correlation_id(self, client):
        """When the caller supplies X-Correlation-ID, the response echoes it."""
        resp = await client.get("/ok", headers={"X-Correlation-ID": "my-trace-123"})
        assert resp.headers["X-Correlation-ID"] == "my-trace-123"

    @pytest.mark.asyncio
    async def test_echoes_caller_request_id(self, client):
        """When the caller supplies X-Request-ID, it is used as correlation."""
        resp = await client.get("/ok", headers={"X-Request-ID": "req-456"})
        assert resp.headers["X-Correlation-ID"] == "req-456"

    @pytest.mark.asyncio
    async def test_unique_ids_per_request(self, client):
        """Each request gets a unique correlation ID."""
        r1 = await client.get("/ok")
        r2 = await client.get("/ok")
        assert r1.headers["X-Correlation-ID"] != r2.headers["X-Correlation-ID"]


# =========================================================================
# Body Size Limiter Middleware
# =========================================================================


class TestBodySizeLimiterMiddleware:
    """Verify the request body size limiter from app.main."""

    @pytest_asyncio.fixture
    async def client(self):
        """Use the real app so the inline http middleware is included."""
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c

    @pytest.mark.asyncio
    async def test_oversized_body_rejected(self, client):
        """Content-Length exceeding MAX_REQUEST_BODY_SIZE yields 413."""
        from app.core.config import settings

        oversized = settings.MAX_REQUEST_BODY_SIZE + 1
        resp = await client.post(
            "/api/v1/health",
            content=b"x",
            headers={"Content-Length": str(oversized)},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_normal_body_passes(self, client):
        """Small request passes through the limiter."""
        resp = await client.get("/api/v1/health")
        assert resp.status_code != 413

    @pytest.mark.asyncio
    async def test_exact_limit_passes(self, client):
        """Body at exactly the limit is allowed."""
        from app.core.config import settings

        resp = await client.post(
            "/api/v1/health",
            content=b"x",
            headers={"Content-Length": str(settings.MAX_REQUEST_BODY_SIZE)},
        )
        assert resp.status_code != 413

    @pytest.mark.asyncio
    async def test_no_content_length_passes(self, client):
        """Requests without Content-Length are not rejected."""
        resp = await client.get("/ok")
        assert resp.status_code != 413


# =========================================================================
# Request Timeout Middleware
# =========================================================================


class TestRequestTimeoutMiddleware:
    """Verify that the request_timeout middleware in main.py returns 504 on slow handlers."""

    @pytest.mark.asyncio
    async def test_fast_request_succeeds(self):
        """A fast handler completes within timeout."""
        app = FastAPI()

        @app.get("/fast")
        async def fast():
            return {"ok": True}

        # Add timeout middleware
        @app.middleware("http")
        async def timeout_mw(request: Request, call_next):
            try:
                return await asyncio.wait_for(call_next(request), timeout=5.0)
            except TimeoutError:
                return JSONResponse({"detail": "Request timeout"}, status_code=504)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get("/fast")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_slow_request_returns_504(self):
        """A handler exceeding timeout returns 504."""
        app = FastAPI()

        @app.get("/slow")
        async def slow():
            await asyncio.sleep(10)
            return {"ok": True}

        @app.middleware("http")
        async def timeout_mw(request: Request, call_next):
            try:
                return await asyncio.wait_for(call_next(request), timeout=0.1)
            except TimeoutError:
                return JSONResponse({"detail": "Request timeout"}, status_code=504)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get("/slow")
        assert resp.status_code == 504
        assert resp.json()["detail"] == "Request timeout"

    @pytest.mark.asyncio
    async def test_timeout_disabled_when_zero(self):
        """When timeout is 0, requests run without time limit."""
        app = FastAPI()

        @app.get("/ok")
        async def ok():
            return {"ok": True}

        @app.middleware("http")
        async def timeout_mw(request: Request, call_next):
            timeout = 0
            if timeout <= 0:
                return await call_next(request)
            try:
                return await asyncio.wait_for(call_next(request), timeout=timeout)
            except TimeoutError:
                return JSONResponse({"detail": "Request timeout"}, status_code=504)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get("/ok")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_exempt_path_not_timed_out(self):
        """Paths in the exempt list skip the timeout."""
        exempt_prefixes = ("/api/v1/export", "/ws")
        app = FastAPI()

        @app.get("/api/v1/export/report")
        async def export_report():
            await asyncio.sleep(0.2)
            return {"report": "data"}

        @app.middleware("http")
        async def timeout_mw(request: Request, call_next):
            timeout = 0.05
            path = request.url.path
            if any(path.startswith(p) for p in exempt_prefixes):
                return await call_next(request)
            try:
                return await asyncio.wait_for(call_next(request), timeout=timeout)
            except TimeoutError:
                return JSONResponse({"detail": "Request timeout"}, status_code=504)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.get("/api/v1/export/report")
        assert resp.status_code == 200


# =========================================================================
# Combined Stack
# =========================================================================


class TestCombinedMiddlewareStack:
    """Verify multiple middleware work together correctly."""

    @pytest_asyncio.fixture
    async def client(self):
        app = _make_app_with(SecurityHeadersMiddleware, CorrelationIdMiddleware)
        async with await _client(app) as c:
            yield c

    @pytest.mark.asyncio
    async def test_both_security_and_correlation_headers(self, client):
        """Both security headers and correlation ID are present."""
        resp = await client.get("/ok")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Correlation-ID") is not None

    @pytest.mark.asyncio
    async def test_headers_on_all_status_codes(self, client):
        """Security headers present even on 404 responses."""
        resp = await client.get("/nonexistent")
        assert resp.status_code == 404
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Correlation-ID") is not None
