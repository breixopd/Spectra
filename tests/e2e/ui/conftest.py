"""Fixtures for the supported React operator-workspace browser suite."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect

ADMIN_USERNAME = os.environ.get("APP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASSWORD", "TestPassword123!")


def normalize_app_base_url(value: str) -> str:
    """Return a safe origin for browser tests, rejecting accidental file URLs."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("APP_BASE_URL must use http or https and include a host")
    return value.rstrip("/")


@pytest.fixture(scope="session")
def app_url() -> str:
    return normalize_app_base_url(os.environ.get("APP_BASE_URL", "http://localhost:5000"))


@pytest.fixture(scope="session")
def admin_credentials() -> dict[str, str]:
    return {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}


def login_as_admin(page: Page, app_url: str, credentials: dict[str, str]) -> None:
    """Authenticate through the public SPA flow and wait for the durable shell."""
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible(timeout=30_000)
    page.locator("#username").fill(credentials["username"])
    page.locator("#password").fill(credentials["password"])
    with page.expect_response(
        lambda response: "/api/v1/auth/token" in response.url and response.request.method == "POST",
        timeout=60_000,
    ) as response_event:
        page.get_by_role("button", name="Sign in", exact=True).click()
    response = response_event.value
    assert response.ok, f"Login failed with HTTP {response.status}: {response.text()[:800]}"
    page.wait_for_url(re.compile(r".*/dashboard/?(?:\?.*)?$"), timeout=60_000)
    expect(page.get_by_role("heading", name="Mission Control", exact=True)).to_be_visible(timeout=30_000)


@pytest.fixture
def authenticated_page(page: Page, app_url: str, admin_credentials: dict[str, str]) -> Page:
    login_as_admin(page, app_url, admin_credentials)
    return page
