"""Test authentication flow - login, navigation, logout."""

import re

from playwright.sync_api import Page, expect

from tests.e2e.ui.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, _reset_user_activity


def test_login_page_renders(login_page: Page):
    """Login page should render with form fields."""
    expect(login_page.locator("#username")).to_be_visible()
    expect(login_page.locator("#password")).to_be_visible()
    expect(login_page.locator("button[type='submit']")).to_be_visible()


def test_login_no_connecting_message(login_page: Page):
    """Login page should NOT show 'connecting to server' status bar."""
    status_bar = login_page.locator("#global-status-bar")
    login_page.wait_for_function(
        """() => {
            const bar = document.getElementById('global-status-bar');
            return !bar || bar.classList.contains('hidden') || !bar.innerText.includes('Connecting to server');
        }""",
        timeout=2_000,
    )
    if status_bar.is_visible():
        expect(status_bar).not_to_contain_text("Connecting to server")


def test_login_success_redirects_to_dashboard(login_page: Page, app_url: str):
    """Successful login should redirect to dashboard."""
    _reset_user_activity(ADMIN_USERNAME)
    login_page.fill("#username", ADMIN_USERNAME)
    login_page.fill("#password", ADMIN_PASSWORD)
    with login_page.expect_response(
        lambda r: "/api/v1/auth/token" in r.url and r.request.method == "POST",
        timeout=120_000,
    ) as resp_ev:
        login_page.click("button[type='submit']")
    resp = resp_ev.value
    assert resp.ok, f"login token HTTP {resp.status}: {resp.text()[:1200]}"
    login_page.wait_for_url(re.compile(r".*/dashboard/?.*"), timeout=180_000)
    login_page.locator("[data-testid='sidebar'], #sidebar").first.wait_for(state="visible", timeout=180_000)
    expect(login_page).to_have_url(re.compile(rf"^{re.escape(app_url)}/dashboard/?$"))


def test_navigation_after_login(authenticated_page: Page, app_url: str):
    """After login, navigation to other sections should work (not redirect to login)."""
    for path in ["/targets", "/history", "/settings"]:
        try:
            authenticated_page.goto(f"{app_url}{path}", wait_until="domcontentloaded")
        except Exception:
            # Retry once — a page-JS redirect may race with the navigation
            authenticated_page.goto(f"{app_url}{path}", wait_until="domcontentloaded")
        expect(authenticated_page).to_have_url(f"{app_url}{path}", timeout=15_000)
