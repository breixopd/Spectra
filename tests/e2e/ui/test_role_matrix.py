"""Multi-role matrix tests — verify navigation visibility and access control for admin, staff, and user roles.

Role mapping (DB → alias):
  admin  -> admin
  staff  -> operator
  user   -> viewer

RBAC permissions are enforced server-side; these tests verify both UI visibility
and HTTP-level access restrictions.
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.ui.harness.db_user import (
    create_verified_test_user,
    ui_login,
)
from tests.e2e.ui.harness.navigation import goto_authenticated_app_path

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _wait_for_sidebar_hydration(page: Page) -> None:
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)
    page.wait_for_function(
        """() => {
            const u = document.getElementById('sidebar-username');
            return u && u.textContent && u.textContent.trim().length > 0;
        }""",
        timeout=20_000,
    )


def _api_get(app_url: str, path: str, username: str, password: str) -> httpx.Response:
    with httpx.Client(base_url=app_url, timeout=30) as client:
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": username, "password": password},
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        return client.get(path, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.timeout(60)
def test_admin_can_see_admin_nav(page: Page, app_url: str) -> None:
    """Admin user should see the admin navigation link in the sidebar."""
    username, _uid = create_verified_test_user("admin")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    _wait_for_sidebar_hydration(page)

    admin_link = page.get_by_test_id("admin-nav-link")
    expect(admin_link).to_be_visible(timeout=15_000)


@pytest.mark.timeout(60)
def test_admin_can_access_admin_panel(page: Page, app_url: str) -> None:
    """Admin user can navigate to /admin and see the admin panel content."""
    username, _uid = create_verified_test_user("admin")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/admin")

    expect(page).to_have_url(f"{app_url}/admin", timeout=15_000)
    expect(page.locator("text=Admin Panel")).to_be_visible(timeout=15_000)
    error_el = page.locator(".error-code")
    if error_el.count() > 0 and error_el.is_visible():
        code_text = error_el.inner_text()
        assert not code_text.startswith("4"), f"Admin got error {code_text} on /admin"


@pytest.mark.timeout(60)
def test_admin_can_access_user_management(page: Page, app_url: str) -> None:
    """Admin user can access the user management API endpoint."""
    username, _uid = create_verified_test_user("admin")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/admin")

    users_tab = page.locator('#tab-users, button:has-text("Users")').first
    if users_tab.count() > 0:
        users_tab.click()
        expect(page.locator("#section-users, #users-tbody").first).to_be_visible(timeout=10_000)


@pytest.mark.timeout(60)
def test_admin_can_access_plan_management(page: Page, app_url: str) -> None:
    """Admin user can access the plan management section."""
    username, _uid = create_verified_test_user("admin")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/admin")

    plans_tab = page.locator('#tab-plans, button:has-text("Plans")').first
    if plans_tab.count() > 0:
        plans_tab.click()
        expect(page.locator("#section-plans, #plans-grid").first).to_be_visible(timeout=10_000)


@pytest.mark.timeout(60)
def test_admin_api_access_to_user_endpoints(page: Page, app_url: str) -> None:
    """Admin can fetch user list via the admin API."""
    username, _uid = create_verified_test_user("admin")
    resp = _api_get(app_url, "/api/admin/users", username, "TestPassword123!")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "items" in data or "users" in data or isinstance(data, list)


@pytest.mark.timeout(60)
def test_admin_api_access_to_plan_endpoints(page: Page, app_url: str) -> None:
    """Admin can fetch plan list via the admin API."""
    username, _uid = create_verified_test_user("admin")
    resp = _api_get(app_url, "/api/admin/plans", username, "TestPassword123!")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


@pytest.mark.timeout(60)
def test_staff_cannot_see_admin_nav(page: Page, app_url: str) -> None:
    """Staff user should not see the admin navigation link."""
    username, _uid = create_verified_test_user("staff")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    _wait_for_sidebar_hydration(page)

    admin_link = page.get_by_test_id("admin-nav-link")
    if admin_link.count() > 0:
        is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
        assert not admin_link.is_visible() or is_hidden, (
            "Staff user should not see the admin navigation link"
        )


@pytest.mark.timeout(60)
def test_staff_can_view_missions_and_findings(page: Page, app_url: str) -> None:
    """Staff can view missions (History) and findings-related pages."""
    username, _uid = create_verified_test_user("staff")
    ui_login(page, app_url, username)

    for path in ["/dashboard", "/history", "/reports"]:
        goto_authenticated_app_path(page, app_url, path)
        expect(page).to_have_url(f"{app_url}{path}", timeout=15_000)
        error_el = page.locator(".error-code")
        if error_el.count() > 0 and error_el.is_visible():
            code_text = error_el.inner_text()
            assert not code_text.startswith("4"), f"Staff got error {code_text} on {path}"


@pytest.mark.timeout(60)
def test_staff_can_view_targets(page: Page, app_url: str) -> None:
    """Staff can view the targets page."""
    username, _uid = create_verified_test_user("staff")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/targets")
    expect(page).to_have_url(f"{app_url}/targets", timeout=15_000)


@pytest.mark.timeout(60)
def test_staff_cannot_access_admin_page(page: Page, app_url: str) -> None:
    """Staff user cannot access the admin panel — should 403 or redirect."""
    username, _uid = create_verified_test_user("staff")
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/admin", wait_until="domcontentloaded")

    url = page.url
    at_admin = url.rstrip("/").endswith("/admin")
    if at_admin:
        error_el = page.locator(".error-code, .forbidden, [data-error]")
        assert error_el.count() > 0, "Staff reached /admin without any error indicator"
    else:
        assert "/login" in url or "/dashboard" in url, f"Unexpected redirect for staff: {url}"


@pytest.mark.timeout(60)
def test_staff_api_admin_endpoints_return_200(page: Page, app_url: str) -> None:
    """Staff API calls to user management endpoints should return 200 (staff has MANAGE_USERS)."""
    username, _uid = create_verified_test_user("staff")
    resp = _api_get(app_url, "/api/admin/users", username, "TestPassword123!")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


@pytest.mark.timeout(60)
def test_staff_api_plan_endpoints_return_403(page: Page, app_url: str) -> None:
    """Staff API calls to plan management endpoints should return 403."""
    username, _uid = create_verified_test_user("staff")
    resp = _api_get(app_url, "/api/admin/plans", username, "TestPassword123!")
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"


@pytest.mark.timeout(60)
def test_user_cannot_see_admin_nav(page: Page, app_url: str) -> None:
    """User (viewer) should not see the admin navigation link."""
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    _wait_for_sidebar_hydration(page)

    admin_link = page.get_by_test_id("admin-nav-link")
    if admin_link.count() > 0:
        is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
        assert not admin_link.is_visible() or is_hidden, (
            "User (viewer) should not see the admin navigation link"
        )


@pytest.mark.timeout(60)
def test_user_can_view_missions_and_findings(page: Page, app_url: str) -> None:
    """User can view missions and findings pages."""
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)

    for path in ["/dashboard", "/history", "/reports"]:
        goto_authenticated_app_path(page, app_url, path)
        expect(page).to_have_url(f"{app_url}{path}", timeout=15_000)
        error_el = page.locator(".error-code")
        if error_el.count() > 0 and error_el.is_visible():
            code_text = error_el.inner_text()
            assert not code_text.startswith("4"), f"User got error {code_text} on {path}"


@pytest.mark.timeout(60)
def test_user_cannot_access_admin_page(page: Page, app_url: str) -> None:
    """User cannot access the admin panel — should 403 or redirect."""
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/admin", wait_until="domcontentloaded")

    url = page.url
    at_admin = url.rstrip("/").endswith("/admin")
    if at_admin:
        error_el = page.locator(".error-code, .forbidden, [data-error]")
        assert error_el.count() > 0, "User reached /admin without any error indicator"
    else:
        assert "/login" in url or "/dashboard" in url, f"Unexpected redirect for user: {url}"


@pytest.mark.timeout(60)
def test_user_api_admin_endpoints_return_403(page: Page, app_url: str) -> None:
    """User API calls to admin endpoints should return 403."""
    username, _uid = create_verified_test_user("user")
    resp = _api_get(app_url, "/api/admin/users", username, "TestPassword123!")
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"


@pytest.mark.timeout(60)
def test_user_api_plan_endpoints_return_403(page: Page, app_url: str) -> None:
    """User API calls to plan management endpoints should return 403."""
    username, _uid = create_verified_test_user("user")
    resp = _api_get(app_url, "/api/admin/plans", username, "TestPassword123!")
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"


@pytest.mark.timeout(60)
def test_nav_visibility_matrix(page: Page, app_url: str) -> None:
    """Verify that common nav items are visible for all authenticated roles,
    while admin-only items are restricted.
    """
    common_links = [
        ("/dashboard", "Dashboard"),
        ("/history", "History"),
        ("/targets", "Targets"),
        ("/reports", "Reports"),
        ("/settings", "Settings"),
        ("/help", "Help Center"),
    ]

    for role in ("admin", "staff", "user"):
        username, _uid = create_verified_test_user(role)
        ui_login(page, app_url, username)
        goto_authenticated_app_path(page, app_url, "/dashboard")
        _wait_for_sidebar_hydration(page)

        for href, _label in common_links:
            link = page.locator(f'aside a[href="{href}"], nav a[href="{href}"]').first
            expect(link).to_be_visible(timeout=5_000)

        admin_link = page.get_by_test_id("admin-nav-link")
        if role == "admin":
            expect(admin_link).to_be_visible(timeout=5_000)
        else:
            if admin_link.count() > 0:
                is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
                assert not admin_link.is_visible() or is_hidden, (
                    f"{role} should not see admin nav link"
                )

        page.context.clear_cookies()
