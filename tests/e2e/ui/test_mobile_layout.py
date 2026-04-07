"""Test mobile responsive layout."""

import pytest
from playwright.sync_api import Page, expect

MOBILE_VIEWPORT = {"width": 375, "height": 812}


@pytest.fixture
def mobile_page(page: Page, app_url: str):
    """Page with mobile viewport."""
    page.set_viewport_size(MOBILE_VIEWPORT)  # iPhone 13
    page.goto(f"{app_url}/login", wait_until="networkidle")
    return page


def test_login_page_mobile(mobile_page: Page):
    """Login page should be usable on mobile."""
    expect(mobile_page.locator("#username")).to_be_visible()
    expect(mobile_page.locator("#password")).to_be_visible()
    # Form should not significantly overflow viewport (allow minor scrollbar)
    form = mobile_page.locator("form")
    box = form.bounding_box()
    assert box is not None
    assert box["width"] <= 400, f"Form overflows mobile viewport: {box['width']}px"


def test_dashboard_mobile_scrollable(authenticated_page: Page, app_url: str):
    """Dashboard should be scrollable on mobile."""
    authenticated_page.set_viewport_size(MOBILE_VIEWPORT)

    # Reuse the shared authenticated flow before asserting the mobile layout.
    authenticated_page.goto(f"{app_url}/dashboard", wait_until="networkidle")

    # Check that body allows scrolling (no overflow-hidden on mobile)
    overflow = authenticated_page.evaluate("() => getComputedStyle(document.body).overflowY")
    assert overflow != "hidden", "Body should allow vertical scrolling on mobile"


def test_dashboard_mobile_layout(authenticated_page: Page, app_url: str):
    """Dashboard renders properly on mobile viewport."""
    page = authenticated_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    # Main content should be visible
    main = page.locator("main, #main-content, .main-content, [role='main']")
    expect(main.first).to_be_visible(timeout=15_000)
    # Sidebar should be hidden or collapsed on mobile
    sidebar = page.locator("#sidebar, nav.sidebar, aside")
    if sidebar.count() > 0:
        box = sidebar.first.bounding_box()
        assert box is None or box["width"] < 100, (
            f"Sidebar should be collapsed on mobile, got width={box['width'] if box else 'N/A'}px"
        )


def test_settings_page_mobile(authenticated_page: Page, app_url: str):
    """Settings page renders properly on mobile viewport."""
    page = authenticated_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{app_url}/settings", wait_until="domcontentloaded")
    expect(page.locator("h1, h2, .page-title").first).to_be_visible(timeout=15_000)
    # Page content should not overflow the mobile viewport
    body_width = page.evaluate("() => document.body.scrollWidth")
    assert body_width <= MOBILE_VIEWPORT["width"] + 20, (
        f"Settings page overflows mobile viewport: {body_width}px"
    )


def test_profile_page_mobile(authenticated_page: Page, app_url: str):
    """Profile page renders properly on mobile viewport."""
    page = authenticated_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{app_url}/profile", wait_until="domcontentloaded")
    expect(
        page.locator("[data-tab='general'], .tab, .profile-content, main").first
    ).to_be_visible(timeout=15_000)


def test_admin_page_mobile(authenticated_page: Page, app_url: str):
    """Admin page renders properly on mobile viewport (if accessible)."""
    page = authenticated_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{app_url}/admin", wait_until="domcontentloaded")
    # If redirected away (non-admin user), skip the test
    if "/admin" not in page.url:
        pytest.skip("User does not have admin access")
    expect(page.locator("h1, h2, .page-title, main").first).to_be_visible(timeout=15_000)
