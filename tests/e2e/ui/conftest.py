"""Playwright UI test fixtures with admin auth."""
import pytest


@pytest.fixture(scope="session")
def app_url():
    return "https://localhost"

@pytest.fixture(scope="session")
def admin_credentials():
    return {"username": "admin", "password": "Admin123!"}
