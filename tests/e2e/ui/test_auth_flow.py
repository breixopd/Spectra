"""Test authentication flow - login, navigation, logout."""

from playwright.sync_api import Page, expect


def test_login_page_renders(login_page: Page):
    """Login page should render with form fields."""
    expect(login_page.locator("#username")).to_be_visible()
    expect(login_page.locator("#password")).to_be_visible()
    expect(login_page.locator("button[type='submit']")).to_be_visible()


def test_login_no_connecting_message(login_page: Page):
    """Login page should NOT show 'connecting to server' status bar."""
    # Wait a moment for any status polling to fire
    login_page.wait_for_timeout(2000)
    status_bar = login_page.locator("#global-status-bar")
    # Should be hidden or not have connecting text
    if status_bar.is_visible():
        expect(status_bar).not_to_contain_text("Connecting to server")


def test_login_success_redirects_to_dashboard(login_page: Page, app_url: str):
    """Successful login should redirect to dashboard."""
    login_page.fill("#username", "admin")
    login_page.fill("#password", "TestPassword123!")
    login_page.click("button[type='submit']")
    login_page.wait_for_url("**/dashboard", timeout=10000)
    expect(login_page).to_have_url(f"{app_url}/dashboard")


def test_navigation_after_login(authenticated_page: Page, app_url: str):
    """After login, navigation to other sections should work (not redirect to login)."""
    # Navigate to targets
    authenticated_page.goto(f"{app_url}/targets")
    authenticated_page.wait_for_load_state("networkidle")
    expect(authenticated_page).to_have_url(f"{app_url}/targets")

    # Navigate to history
    authenticated_page.goto(f"{app_url}/history")
    authenticated_page.wait_for_load_state("networkidle")
    expect(authenticated_page).to_have_url(f"{app_url}/history")

    # Navigate to settings
    authenticated_page.goto(f"{app_url}/settings")
    authenticated_page.wait_for_load_state("networkidle")
    expect(authenticated_page).to_have_url(f"{app_url}/settings")
