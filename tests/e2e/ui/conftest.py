"""Playwright UI test fixtures."""

import http.client
import json
import os
import urllib.parse

import pytest
from playwright.sync_api import Page, expect

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
ALLOWED_APP_URL_SCHEMES = {"http", "https"}


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
def auth_token(app_url: str):
    """Fetch one auth token for the whole UI test session."""
    parsed_url = urllib.parse.urlsplit(app_url)
    payload = urllib.parse.urlencode(
        {
            "username": "admin",
            "password": "TestPassword123!",
        }
    ).encode()

    connection_cls = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(parsed_url.netloc, timeout=15)
    try:
        connection.request(
            "POST",
            "/api/auth/token",
            body=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response = connection.getresponse()
        if response.status >= 400:
            raise RuntimeError(f"Auth token request failed with status {response.status}")
        token_data = json.loads(response.read().decode())
    finally:
        connection.close()

    return token_data["access_token"]


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
def authenticated_page(page: Page, app_url: str, auth_token: str):
    """Get an authenticated dashboard page using the auth API for stability."""
    page.goto(f"{app_url}/login")
    page.evaluate(
        """
        token => {
            localStorage.setItem('token', token);
            document.cookie = `access_token=${token}; path=/; SameSite=Strict`;
        }
        """,
        auth_token,
    )
    page.goto(f"{app_url}/dashboard")
    expect(page.locator("#mission-target")).to_be_visible(timeout=30000)
    return page
