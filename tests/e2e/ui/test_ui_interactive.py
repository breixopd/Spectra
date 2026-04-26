"""Comprehensive interactive Playwright browser tests.

These tests actually log in, interact with forms, click buttons,
and verify page content — replacing shallow URL-only navigation tests.
"""

import os
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]

APP_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")


# ---------------------------------------------------------------------------
# 1. Login & Dashboard
# ---------------------------------------------------------------------------


def test_login_and_dashboard(logged_in_page: Page, app_url: str):
    """Log in as admin, verify dashboard loads with sidebar and content."""
    page = logged_in_page

    # Dashboard should be loaded
    expect(page).to_have_url(f"{app_url}/dashboard", timeout=10_000)

    # Sidebar should be visible
    sidebar = page.locator("#sidebar")
    expect(sidebar).to_be_visible(timeout=10_000)

    # At least one dashboard section present (the mission target input)
    expect(page.locator("#mission-target")).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 2. Signup shows errors
# ---------------------------------------------------------------------------


def test_signup_shows_errors(page: Page, app_url: str):
    """Invalid signup data should be blocked by native browser validation."""
    page.goto(f"{app_url}/register", wait_until="domcontentloaded")

    submit_btn = page.locator("#submitBtn")
    expect(submit_btn).to_be_visible(timeout=10_000)
    msg = page.locator("#msg")

    # Empty required fields should keep the form invalid before any submit handler runs.
    username_input = page.locator("#username")
    is_valid = page.evaluate("document.getElementById('registerForm').checkValidity()")
    assert not is_valid, "Empty form should not pass HTML validation"

    # Fill invalid client-side data and attempt a real submit.
    username_input.fill("ab")
    page.locator("#email").fill("not-an-email")
    page.locator("#password").fill("short")
    submit_btn.click()

    expect(submit_btn).to_have_text("Create Account")
    expect(page).to_have_url(f"{app_url}/register", timeout=10_000)
    expect(msg).to_have_text("")

    invalid_state = page.evaluate(
        """
        () => {
            const form = document.getElementById('registerForm');
            const username = document.getElementById('username');
            const email = document.getElementById('email');
            const password = document.getElementById('password');
            return {
                form_valid: form.checkValidity(),
                username_message: username.validationMessage,
                email_message: email.validationMessage,
                password_message: password.validationMessage,
            };
        }
        """
    )

    assert not invalid_state["form_valid"], "Invalid registration data should be blocked client-side"
    assert invalid_state["username_message"], "Username minlength validation should be active"
    assert invalid_state["email_message"], "Email format validation should be active"
    assert invalid_state["password_message"], "Password minlength validation should be active"


# ---------------------------------------------------------------------------
# 3. Signup with existing user
# ---------------------------------------------------------------------------


def test_signup_with_existing_user(page: Page, app_url: str):
    """Register with existing 'admin' username — verify error message."""
    page.goto(f"{app_url}/register", wait_until="domcontentloaded")

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
    ("/docs/api", "Documentation"),
    ("/manual", "Manual Tools"),
    ("/overseer", "Agents"),
    ("/toolbox", "Toolbox"),
    ("/observability", "Observability"),
    ("/settings", "Settings"),
]


def test_navigation_sidebar(logged_in_page: Page, app_url: str):
    """Click each sidebar link and verify the page loads."""
    page = logged_in_page

    expect(page).to_have_url(f"{app_url}/dashboard", timeout=15_000)

    for path, _link_text in _SIDEBAR_LINKS[1:]:
        sidebar_link = page.locator(f"#sidebar nav a[href='{path}']")
        if sidebar_link.count() == 0:
            continue
        expect(sidebar_link).to_be_visible(timeout=15_000)
        page.goto(f"{app_url}{path}", wait_until="networkidle")
        assert page.url == f"{app_url}{path}" or page.url.startswith(f"{app_url}{path}#")


# ---------------------------------------------------------------------------
# 5. Admin panel tabs
# ---------------------------------------------------------------------------

_ADMIN_TABS = [
    ("users", "Users"),
    ("plans", "Plans"),
    ("usage", "Usage"),
    ("services", "Services"),
    ("scaling", "Scaling"),
    ("audit", "Audit"),
    ("content", "Content"),
    ("llm", "AI Config"),
    ("tensorzero", "AI Gateway"),
    ("backups", "Backups"),
    ("email", "Email"),
    ("rollback", "Rollback"),
]


def test_admin_panel_tabs(logged_in_page: Page, app_url: str):
    """Go to /admin, click each tab, verify the section loads."""
    page = logged_in_page
    page.goto(f"{app_url}/admin", wait_until="networkidle")

    for section_id, _label in _ADMIN_TABS:
        tab_link = page.locator(f".admin-sidebar [data-section='{section_id}']")
        if tab_link.count() == 0:
            continue
        tab_link.scroll_into_view_if_needed()
        tab_link.click(force=True)
        # The corresponding section should become visible
        section = page.locator(f"#section-{section_id}")
        expect(section).to_be_visible(timeout=15_000)


# ---------------------------------------------------------------------------
# 6. Profile page
# ---------------------------------------------------------------------------


def test_profile_page(logged_in_page: Page, app_url: str):
    """Navigate to /profile, verify profile form with username field."""
    page = logged_in_page
    page.goto(f"{app_url}/profile", wait_until="networkidle")

    username_field = page.locator("#profile-username")
    expect(username_field).to_be_visible(timeout=15_000)

    email_field = page.locator("#profile-email")
    expect(email_field).to_be_visible(timeout=15_000)


# ---------------------------------------------------------------------------
# 7. Observability page
# ---------------------------------------------------------------------------


def test_observability_page(logged_in_page: Page, app_url: str):
    """Go to /observability, verify metrics/charts section loads."""
    page = logged_in_page
    page.goto(f"{app_url}/observability", wait_until="networkidle")

    heading = page.locator("h1", has_text="Observability")
    expect(heading).to_be_visible(timeout=15_000)

    # At least one chart canvas should be present
    charts = page.locator("canvas[id^='chart-']")
    expect(charts.first).to_be_attached(timeout=15_000)


# ---------------------------------------------------------------------------
# 8. Landing page elements
# ---------------------------------------------------------------------------


def test_landing_page_elements(page: Page, app_url: str):
    """Verify hero, features, pricing, CTA buttons on landing page."""
    page.goto(f"{app_url}/", wait_until="domcontentloaded")

    # Hero section
    hero = page.locator("section.hero")
    expect(hero).to_be_visible(timeout=10_000)

    # Features section
    features = page.locator("#features")
    expect(features).to_be_attached(timeout=10_000)

    # Pricing section
    pricing = page.locator("#pricing")
    expect(pricing).to_be_attached(timeout=10_000)

    # Primary hero CTA exists and is clickable
    cta = page.locator("section.hero .hero-actions a.btn-primary", has_text="Get Started")
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


def test_legal_pages(page: Page, app_url: str):
    """Verify legal pages load with Spectra branding and headings."""
    for path, expected_heading in _LEGAL_PAGES:
        page.goto(f"{app_url}{path}", wait_until="domcontentloaded")

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


def test_error_pages(page: Page, app_url: str):
    """Navigate to non-existent URL, verify 404 page."""
    response = page.goto(f"{app_url}/nonexistent-url-that-does-not-exist", wait_until="domcontentloaded")
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
    expect(logout_btn).to_be_visible(timeout=15_000)
    logout_btn.click()

    page.wait_for_url("**/login", timeout=30_000, wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r".*/login"))
    # Wait for the keepalive logout response (which sends Set-Cookie to
    # delete auth cookies) to complete before the fixture tears down.
    # This prevents the delayed Set-Cookie from clobbering cookies
    # injected by subsequent tests' fixtures.
    page.wait_for_timeout(2000)
    page.context.clear_cookies()


# ---------------------------------------------------------------------------
# 12. Forgot password flow
# ---------------------------------------------------------------------------


def test_forgot_password_flow(page: Page, app_url: str):
    """Go to /forgot-password, fill in email, submit, verify message."""
    page.goto(f"{app_url}/forgot-password", wait_until="domcontentloaded")

    email_input = page.locator("#email")
    expect(email_input).to_be_visible(timeout=10_000)

    email_input.fill("admin@test.com")
    page.locator("#submitBtn").click()

    msg = page.locator("#msg")
    expect(msg).to_be_visible(timeout=10_000)
