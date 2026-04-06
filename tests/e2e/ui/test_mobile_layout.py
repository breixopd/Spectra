"""Test mobile responsive layout."""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def mobile_page(page: Page, app_url: str):
    """Page with mobile viewport."""
    page.set_viewport_size({"width": 375, "height": 812})  # iPhone 13
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
    authenticated_page.set_viewport_size({"width": 375, "height": 812})

    # Reuse the shared authenticated flow before asserting the mobile layout.
    authenticated_page.goto(f"{app_url}/dashboard", wait_until="networkidle")

    # Check that body allows scrolling (no overflow-hidden on mobile)
    overflow = authenticated_page.evaluate("() => getComputedStyle(document.body).overflowY")
    assert overflow != "hidden", "Body should allow vertical scrolling on mobile"
