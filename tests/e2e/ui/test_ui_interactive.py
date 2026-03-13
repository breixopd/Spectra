"""Comprehensive interactive Playwright browser tests.

These tests actually log in, interact with forms, click buttons,
and verify page content — replacing shallow URL-only navigation tests.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]

APP_URL = "http://localhost:5000"


# ---------------------------------------------------------------------------
# 1. Login & Dashboard
# ---------------------------------------------------------------------------

def test_login_and_dashboard(logged_in_page: Page):
    """Log in as admin, verify dashboard loads with sidebar and content."""
    page = logged_in_page

    # Dashboard should be loaded
    expect(page).to_have_url(f"{APP_URL}/dashboard", timeout=10_000)

    # Sidebar should be visible
    sidebar = page.locator("#sidebar")
    expect(sidebar).to_be_visible(timeout=10_000)

    # At least one dashboard section present (the mission target input)
    expect(page.locator("#mission-target")).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 2. Signup shows errors
# ---------------------------------------------------------------------------

def test_signup_shows_errors(page: Page):
    """Submit empty registration form — HTML validation prevents submission.
    Then fill invalid data and verify error message."""
    page.goto(f"{APP_URL}/register", wait_until="networkidle")

    submit_btn = page.locator("#submitBtn")
    expect(submit_btn).to_be_visible(timeout=10_000)

    # Try to click submit on empty form — browser validation should prevent submission.
    # The username field has `required`, so it should block submission.
    username_input = page.locator("#username")
    is_valid = page.evaluate("document.getElementById('registerForm').checkValidity()")
    assert not is_valid, "Empty form should not pass HTML validation"

    # Fill invalid data: username too short (minlength=3), bad email
    username_input.fill("ab")
    page.locator("#email").fill("not-an-email")
    page.locator("#password").fill("short")

    # Force submit via JS to bypass HTML validation and trigger server-side errors
    page.evaluate("document.getElementById('registerForm').requestSubmit()")

    # Error message should appear in the msg div
    msg = page.locator("#msg")
    expect(msg).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 3. Signup with existing user
# ---------------------------------------------------------------------------

def test_signup_with_existing_user(page: Page):
    """Register with existing 'admin' username — verify error message."""
    page.goto(f"{APP_URL}/register", wait_until="networkidle")

    page.locator("#username").fill("admin")
    page.locator("#email").fill("admin@test.com")
    page.locator("#password").fill("Password123!")

    page.locator("#submitBtn").click()

    msg = page.locator("#msg")
    expect(msg).to_be_visible(timeout=10_000)
    # Error should indicate the user already exists
    expect(msg).to_contain_text("already", ignore_case=True, timeout=10_000)


# ---------------------------------------------------------------------------
# 4. Navigation sidebar
# ---------------------------------------------------------------------------

_SIDEBAR_LINKS = [
    ("/dashboard", "Dashboard"),
    ("/history", "History"),
    ("/targets", "Targets"),
    ("/reports", "Reports"),
    ("/overseer", "Agents"),
    ("/toolbox", "Toolbox"),
    ("/observability", "Observability"),
    ("/settings", "Settings"),
]


def test_navigation_sidebar(logged_in_page: Page, app_url: str):
    """Click each sidebar link and verify the page loads."""
    page = logged_in_page

    for path, _link_text in _SIDEBAR_LINKS:
        sidebar_link = page.locator(f"#sidebar nav a[href='{path}']")
        sidebar_link.click()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(f"{app_url}{path}", timeout=10_000)


# ---------------------------------------------------------------------------
# 5. Admin panel tabs
# ---------------------------------------------------------------------------

_ADMIN_TABS = [
    ("users", "Users"),
    ("plans", "Plans"),
    ("services", "Services"),
    ("audit", "Audit"),
    ("content", "Content"),
    ("backups", "Backups"),
    ("email", "Email"),
]


def test_admin_panel_tabs(logged_in_page: Page, app_url: str):
    """Go to /admin, click each tab, verify the section loads."""
    page = logged_in_page
    page.goto(f"{app_url}/admin", wait_until="networkidle")
    page.wait_for_timeout(2_000)  # let JS initialise

    for section_id, _label in _ADMIN_TABS:
        tab_link = page.locator(f".admin-sidebar a[data-section='{section_id}']")
        tab_link.click()
        # The corresponding section should become visible
        section = page.locator(f"#section-{section_id}")
        expect(section).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 6. Profile page
# ---------------------------------------------------------------------------

def test_profile_page(logged_in_page: Page, app_url: str):
    """Navigate to /profile, verify profile form with username field."""
    page = logged_in_page
    page.goto(f"{app_url}/profile", wait_until="networkidle")

    username_field = page.locator("#profile-username")
    expect(username_field).to_be_visible(timeout=10_000)

    email_field = page.locator("#profile-email")
    expect(email_field).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 7. Observability page
# ---------------------------------------------------------------------------

def test_observability_page(logged_in_page: Page, app_url: str):
    """Go to /observability, verify metrics/charts section loads."""
    page = logged_in_page
    page.goto(f"{app_url}/observability", wait_until="networkidle")

    heading = page.locator("h1", has_text="Observability")
    expect(heading).to_be_visible(timeout=10_000)

    # At least one chart canvas should be present
    charts = page.locator("canvas[id^='chart-']")
    expect(charts.first).to_be_attached(timeout=10_000)


# ---------------------------------------------------------------------------
# 8. Landing page elements
# ---------------------------------------------------------------------------

def test_landing_page_elements(page: Page):
    """Verify hero, features, pricing, CTA buttons on landing page."""
    page.goto(f"{APP_URL}/", wait_until="networkidle")

    # Hero section
    hero = page.locator("section.hero")
    expect(hero).to_be_visible(timeout=10_000)

    # Features section
    features = page.locator("#features")
    expect(features).to_be_attached(timeout=10_000)

    # Pricing section
    pricing = page.locator("#pricing")
    expect(pricing).to_be_attached(timeout=10_000)

    # CTA button exists and is clickable
    cta = page.locator("a.btn-primary", has_text="Start Free Assessment")
    expect(cta).to_be_visible(timeout=10_000)

    # No mentions of "self-hosting" anywhere on the page
    body_text = page.locator("body").inner_text()
    assert "self-hosting" not in body_text.lower(), "Landing page should not mention self-hosting"


# ---------------------------------------------------------------------------
# 9. Legal pages
# ---------------------------------------------------------------------------

_LEGAL_PAGES = [
    ("/legal/terms", "Terms of Service"),
    ("/legal/privacy", "Privacy Policy"),
    ("/legal/cookies", "Cookie"),
]


def test_legal_pages(page: Page):
    """Verify legal pages load with Spectra branding and headings."""
    for path, expected_heading in _LEGAL_PAGES:
        page.goto(f"{APP_URL}{path}", wait_until="networkidle")

        # Page should contain the expected heading text
        heading = page.locator("h1")
        expect(heading).to_be_visible(timeout=10_000)
        expect(heading).to_contain_text(expected_heading)

        # Should use Spectra branding, not placeholder "[Company Name]"
        body_text = page.locator("body").inner_text()
        assert "[Company Name]" not in body_text, f"{path} still has placeholder branding"


# ---------------------------------------------------------------------------
# 10. Error pages
# ---------------------------------------------------------------------------

def test_error_pages(page: Page):
    """Navigate to non-existent URL, verify 404 page."""
    response = page.goto(f"{APP_URL}/nonexistent-url-that-does-not-exist", wait_until="networkidle")
    assert response is not None
    assert response.status == 404

    error_code = page.locator(".error-code")
    expect(error_code).to_be_visible(timeout=10_000)
    expect(error_code).to_contain_text("404")

    title = page.locator(".error-title")
    expect(title).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 11. Logout
# ---------------------------------------------------------------------------

def test_logout(logged_in_page: Page, app_url: str):
    """Log in, click logout, verify redirect to /login."""
    page = logged_in_page

    logout_btn = page.locator("button[title='Sign out']")
    expect(logout_btn).to_be_visible(timeout=10_000)
    logout_btn.click()

    page.wait_for_url("**/login", timeout=10_000)
    expect(page).to_have_url(f"{app_url}/login")


# ---------------------------------------------------------------------------
# 12. Forgot password flow
# ---------------------------------------------------------------------------

def test_forgot_password_flow(page: Page):
    """Go to /forgot-password, fill in email, submit, verify message."""
    page.goto(f"{APP_URL}/forgot-password", wait_until="networkidle")

    email_input = page.locator("#email")
    expect(email_input).to_be_visible(timeout=10_000)

    email_input.fill("admin@test.com")
    page.locator("#submitBtn").click()

    msg = page.locator("#msg")
    expect(msg).to_be_visible(timeout=10_000)
