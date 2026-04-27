"""Release-candidate browser coverage for roles, entitlements, and error paths."""

from __future__ import annotations

import uuid

import httpx
import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.ui.harness.db_user import (
    DEFAULT_TEST_PASSWORD,
    create_verified_test_user,
    grant_user_plan_features,
    ui_login,
)
from tests.e2e.ui.harness.navigation import goto_authenticated_app_path

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


@pytest.mark.timeout(60)
def test_api_docs_denied_without_api_access(page: Page, app_url: str) -> None:
    username, _user_id = create_verified_test_user("user")
    ui_login(page, app_url, username)

    response = page.goto(f"{app_url}/docs/api", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 403
    expect(page.locator(".error-code")).to_contain_text("403", timeout=10_000)
    expect(page.locator("body")).to_contain_text("No active subscription", timeout=10_000)


@pytest.mark.timeout(60)
def test_api_docs_hides_admin_routes_for_api_access_user(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"api_access": True})
    ui_login(page, app_url, username)

    goto_authenticated_app_path(page, app_url, "/docs/api")

    expect(page.locator(".doc-sidebar")).to_be_visible(timeout=15_000)
    expect(page.locator(".endpoint-card").first).to_be_visible(timeout=15_000)
    assert page.locator(".group-btn[data-group='admin']").count() == 0
    assert page.locator(".endpoint-card[data-path*='/api/admin/']").count() == 0
    assert page.locator(".endpoint-card[data-path*='/api/v1/system/']").count() == 0


@pytest.mark.timeout(60)
def test_manual_mode_redirects_without_entitlement(page: Page, app_url: str) -> None:
    username, _user_id = create_verified_test_user("user")
    ui_login(page, app_url, username)

    response = page.goto(f"{app_url}/manual", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 403
    expect(page.locator(".error-code")).to_contain_text("403", timeout=10_000)
    expect(page.locator("body")).to_contain_text("No active subscription", timeout=10_000)


@pytest.mark.timeout(60)
def test_non_admin_plugin_creator_redirects_to_toolbox(page: Page, app_url: str) -> None:
    username, _user_id = create_verified_test_user("user")
    ui_login(page, app_url, username)

    page.goto(f"{app_url}/toolbox/create", wait_until="domcontentloaded")

    page.wait_for_url("**/toolbox", timeout=15_000)
    expect(page.locator("body")).to_contain_text("Tool", timeout=15_000)


@pytest.mark.timeout(60)
def test_staff_mission_launch_denied_by_api(page: Page, app_url: str) -> None:
    username, _user_id = create_verified_test_user("staff")
    ui_login(page, app_url, username)

    with httpx.Client(base_url=app_url, timeout=30) as client:
        response = client.post(
            "/api/v1/auth/token",
            data={"username": username, "password": DEFAULT_TEST_PASSWORD},
        )
        response.raise_for_status()
        staff_token = response.json()["access_token"]
        launch = client.post(
            "/api/v1/missions",
            headers={"Authorization": f"Bearer {staff_token}"},
            json={
                "target": "127.0.0.1",
                "directive": "Do not run; permission regression check",
                "authorization_confirmed": True,
            },
        )

    assert launch.status_code == 403, launch.text


@pytest.mark.timeout(45)
def test_invalid_shell_session_returns_clear_404(page: Page, app_url: str) -> None:
    username, _user_id = create_verified_test_user("user")
    ui_login(page, app_url, username)

    response = page.goto(f"{app_url}/shell/{uuid.uuid4()}", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 404
    expect(page.locator("body")).to_contain_text("Session not found or inactive", timeout=10_000)


@pytest.mark.timeout(45)
def test_auth_redirect_without_suppression(browser: Browser, app_url: str) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
        page.wait_for_url("**/login", timeout=15_000)
        expect(page.locator("#username")).to_be_visible(timeout=10_000)
    finally:
        context.close()
