"""Test mobile responsive layout."""

import contextlib

import pytest
from playwright.sync_api import Page, expect

MOBILE_VIEWPORT = {"width": 375, "height": 812}


def _body_scroll_width_after_navigation(page: Page) -> int:
    """Read body width after any auth/status navigation races settle."""
    for attempt in range(3):
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=3_000)
        try:
            return int(page.evaluate("() => document.body.scrollWidth"))
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(500)
    return int(page.evaluate("() => document.body.scrollWidth"))


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
    # On mobile the sidebar is off-screen (translateX(-100%)) and a hamburger
    # button is shown instead.  The sidebar element still exists at full width
    # but its bounding-box x position is negative (off-screen to the left).
    hamburger = page.locator(".hamburger-btn")
    expect(hamburger).to_be_visible(timeout=10_000)
    sidebar = page.locator("#sidebar, nav.sidebar, aside")
    if sidebar.count() > 0:
        box = sidebar.first.bounding_box()
        # Sidebar either has no box (hidden) or is positioned off-screen
        assert box is None or box["x"] < 0, (
            f"Sidebar should be off-screen on mobile, got x={box['x'] if box else 'N/A'}px"
        )


def test_settings_page_mobile(authenticated_page: Page, app_url: str):
    """Settings page renders properly on mobile viewport."""
    page = authenticated_page
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{app_url}/settings", wait_until="domcontentloaded")
    expect(page.locator("h1, h2, .page-title").first).to_be_visible(timeout=15_000)
    # Page content should not overflow the mobile viewport
    body_width = _body_scroll_width_after_navigation(page)
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
