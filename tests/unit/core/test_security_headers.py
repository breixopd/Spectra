"""Tests for security headers middleware."""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def _app():
    """Create a minimal FastAPI app with the security headers middleware."""
    from fastapi import FastAPI

    from spectra_api.bootstrap.middleware import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/page")
    async def page():
        return {"ok": True}

    @app.get("/api/data")
    async def api_data():
        return {"data": 1}

    return app


@pytest.fixture
def client(_app):
    return TestClient(_app)


class TestSecurityHeaders:
    """Verify security-related HTTP headers are set on every response."""

    def test_x_content_type_options(self, client):
        resp = client.get("/page")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/page")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client):
        resp = client.get("/page")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_xss_protection_disabled(self, client):
        """Modern best practice: X-XSS-Protection set to 0."""
        resp = client.get("/page")
        assert resp.headers.get("X-XSS-Protection") == "0"

    def test_permissions_policy(self, client):
        resp = client.get("/page")
        assert "geolocation=()" in resp.headers.get("Permissions-Policy", "")

    def test_hsts_in_production_mode(self):
        """HSTS header should be present when DEBUG=False."""
        from fastapi import FastAPI

        from spectra_api.bootstrap.middleware import SecurityHeadersMiddleware

        with patch("spectra_api.bootstrap.middleware.settings") as mock_settings:
            mock_settings.DEBUG = False
            mock_settings.CORS_ORIGINS = ["http://localhost:5000"]
            app = FastAPI()
            app.add_middleware(SecurityHeadersMiddleware)

            @app.get("/test")
            async def _test():
                return {"ok": True}

            tc = TestClient(app)
            resp = tc.get("/test")
            hsts = resp.headers.get("Strict-Transport-Security", "")
            assert "max-age=" in hsts
            assert "includeSubDomains" in hsts

    def test_no_hsts_in_debug_mode(self):
        """HSTS should NOT be set when DEBUG=True."""
        from fastapi import FastAPI

        from spectra_api.bootstrap.middleware import SecurityHeadersMiddleware

        with patch("spectra_api.bootstrap.middleware.settings") as mock_settings:
            mock_settings.DEBUG = True
            mock_settings.CORS_ORIGINS = ["*"]
            app = FastAPI()
            app.add_middleware(SecurityHeadersMiddleware)

            @app.get("/test")
            async def _test():
                return {"ok": True}

            tc = TestClient(app)
            resp = tc.get("/test")
            assert "Strict-Transport-Security" not in resp.headers

    def test_csp_on_html_pages(self, client):
        """CSP header should be present on non-API paths."""
        resp = client.get("/page")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_no_csp_on_api_paths(self, client):
        """CSP should NOT be set on /api/ paths."""
        resp = client.get("/api/data")
        assert "Content-Security-Policy" not in resp.headers

    def test_cors_origin_blocked_in_production(self):
        """POST from unknown origin should be blocked in non-DEBUG mode."""
        from fastapi import FastAPI

        from spectra_api.bootstrap.middleware import SecurityHeadersMiddleware

        with patch("spectra_api.bootstrap.middleware.settings") as mock_settings:
            mock_settings.DEBUG = False
            mock_settings.CORS_ORIGINS = ["http://allowed.example.com"]
            app = FastAPI()
            app.add_middleware(SecurityHeadersMiddleware)

            @app.post("/action")
            async def _action():
                return {"done": True}

            tc = TestClient(app)
            resp = tc.post(
                "/action",
                headers={"Origin": "http://evil.example.com"},
            )
            assert resp.status_code == 403
