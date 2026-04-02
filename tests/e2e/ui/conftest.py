"""Playwright UI test fixtures."""

import os
import urllib.parse
from typing import Any, cast

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
ADMIN_USERNAME = os.environ.get("APP_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASSWORD", "TestPassword123!")
ALLOWED_APP_URL_SCHEMES = {"http", "https"}
AUTHENTICATED_PAGE_TIMEOUT_MS = 30_000
AUTH_TOKEN_ENDPOINT = "/api/v1/auth/token"
ACCESS_COOKIE_KEY = "access_token"
REFRESH_COOKIE_KEY = "refresh_token"
ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
AUTH_COOKIE_SAMESITE = "Strict"


def normalize_app_base_url(app_base_url: str) -> str:
    """Normalize the configured app base URL and reject unsafe schemes."""
    parsed_url = urllib.parse.urlsplit(app_base_url)
    if parsed_url.scheme not in ALLOWED_APP_URL_SCHEMES or not parsed_url.netloc:
        raise ValueError("APP_BASE_URL must use http or https and include a host")
    return urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path.rstrip("/"), "", ""))


@pytest.fixture(scope="session")
def app_url():
    """Base URL for the application."""
    return normalize_app_base_url(APP_BASE_URL)


@pytest.fixture(scope="session")
def authenticated_cookies(app_url: str) -> list[dict[str, object]]:
    """Authenticate once and reuse the issued auth cookies across UI tests."""
    return _build_auth_cookies(app_url)


def _assert_authenticated_dashboard(page: Page, app_url: str):
    """Assert the browser reached the authenticated dashboard shell."""
    expect(page).to_have_url(f"{app_url}/dashboard", timeout=AUTHENTICATED_PAGE_TIMEOUT_MS)
    expect(page.locator("#sidebar")).to_be_visible(timeout=AUTHENTICATED_PAGE_TIMEOUT_MS)
    expect(page.locator("#mission-target")).to_be_visible(timeout=AUTHENTICATED_PAGE_TIMEOUT_MS)


def _build_auth_cookies(app_url: str) -> list[dict[str, object]]:
    """Authenticate once via the real token endpoint and return the issued auth cookies."""
    parsed_url = urllib.parse.urlsplit(app_url)
    if not parsed_url.hostname:
        raise ValueError("APP_BASE_URL must resolve to a hostname for browser auth cookies")

    with httpx.Client(base_url=app_url, timeout=AUTHENTICATED_PAGE_TIMEOUT_MS / 1000) as client:
        response = client.post(
            AUTH_TOKEN_ENDPOINT,
            data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"UI auth fixture token login failed with HTTP {response.status_code}: {response.text.strip()}"
        )

    payload = response.json()
    if payload.get("mfa_required"):
        raise RuntimeError("UI auth fixture reached MFA instead of issuing a full auth token pair.")

    access_token = response.cookies.get(ACCESS_COOKIE_KEY)
    refresh_token = response.cookies.get(REFRESH_COOKIE_KEY)
    if not access_token or not refresh_token:
        raise RuntimeError("UI auth fixture token login did not set both auth cookies.")

    secure = parsed_url.scheme == "https"

    return [
        {
            "name": ACCESS_COOKIE_KEY,
            "value": access_token,
            "domain": parsed_url.hostname,
            "path": ACCESS_COOKIE_PATH,
            "httpOnly": True,
            "secure": secure,
            "sameSite": AUTH_COOKIE_SAMESITE,
        },
        {
            "name": REFRESH_COOKIE_KEY,
            "value": refresh_token,
            "domain": parsed_url.hostname,
            "path": REFRESH_COOKIE_PATH,
            "httpOnly": True,
            "secure": secure,
            "sameSite": AUTH_COOKIE_SAMESITE,
        },
    ]


@pytest.fixture
def authenticated_context(
    app_url: str,
    authenticated_cookies: list[dict[str, object]],
    browser: Browser,
    browser_context_args: dict,
):
    """Create a fresh browser context seeded with reused server-issued auth cookies."""
    context = browser.new_context(**browser_context_args)
    page = context.new_page()

    try:
        context.add_cookies(cast(Any, authenticated_cookies))
        page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        _assert_authenticated_dashboard(page, app_url)
        page.close()
        yield context
    finally:
        context.close()


@pytest.fixture
def setup_page(page: Page, app_url: str):
    """Navigate to setup page."""
    page.goto(f"{app_url}/setup")
    return page


@pytest.fixture
def login_page(page: Page, app_url: str):
    """Navigate to login page."""
    page.goto(f"{app_url}/login")
    return page


@pytest.fixture
def authenticated_page(authenticated_context: BrowserContext, app_url: str):
    """Return a fresh authenticated page backed by reused server auth cookies."""
    page = authenticated_context.new_page()
    page.goto(f"{app_url}/dashboard")
    _assert_authenticated_dashboard(page, app_url)
    return page


@pytest.fixture
def logged_in_page(authenticated_page: Page):
    """Alias for tests that only need a logged-in browser page."""
    return authenticated_page
