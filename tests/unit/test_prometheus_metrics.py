"""Unit tests for the Prometheus /metrics endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.metrics import router as metrics_router
from app.core.telemetry import MetricFamily, Sample


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(metrics_router)
    return app


class TestPrometheusMetrics:
    @pytest.mark.asyncio
    async def test_returns_text_plain(self):
        app = _build_app()

        families = [
            MetricFamily(
                name="http.server.requests",
                description="Total HTTP requests received",
                type="counter",
                samples=[Sample(labels={"method": "GET"}, value=42)],
            ),
        ]

        with patch("app.api.routers.metrics.telemetry") as mock_tel:
            mock_tel.get_all_metrics.return_value = families

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/metrics")

        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_format_includes_help_type_value(self):
        app = _build_app()

        families = [
            MetricFamily(
                name="llm_calls_total",
                description="Total LLM API calls",
                type="counter",
                samples=[
                    Sample(labels={"model": "gpt-4"}, value=10),
                    Sample(labels={"model": "claude"}, value=5),
                ],
            ),
            MetricFamily(
                name="http.server.request.duration",
                description="HTTP request duration in milliseconds",
                type="summary",
                samples=[Sample(labels={}, value=123.45)],
            ),
        ]

        with patch("app.api.routers.metrics.telemetry") as mock_tel:
            mock_tel.get_all_metrics.return_value = families

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/metrics")

        body = resp.text
        # HELP lines
        assert "# HELP llm_calls_total Total LLM API calls" in body
        assert "# HELP http_server_request_duration" in body
        # TYPE lines
        assert "# TYPE llm_calls_total counter" in body
        assert "# TYPE http_server_request_duration summary" in body
        # Value lines with labels
        assert 'llm_calls_total{model="gpt-4"} 10' in body
        assert 'llm_calls_total{model="claude"} 5' in body
        assert "http_server_request_duration 123.45" in body

    @pytest.mark.asyncio
    async def test_empty_metrics(self):
        app = _build_app()

        with patch("app.api.routers.metrics.telemetry") as mock_tel:
            mock_tel.get_all_metrics.return_value = []

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.get("/metrics")

        assert resp.status_code == 200
        assert resp.text.strip() == ""
