"""Test mobile responsive layout."""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def mobile_page(page: Page, app_url: str):
    """Page with mobile viewport."""
    page.set_viewport_size({"width": 375, "height": 812})  # iPhone 13
    page.goto(f"{app_url}/login")
    return page


def test_login_page_mobile(mobile_page: Page):
    """Login page should be usable on mobile."""
    expect(mobile_page.locator("#username")).to_be_visible()
    expect(mobile_page.locator("#password")).to_be_visible()
    # Form should not overflow viewport
    form = mobile_page.locator("form")
    box = form.bounding_box()
    assert box is not None
    assert box["width"] <= 375, "Form overflows mobile viewport"


def test_dashboard_mobile_scrollable(page: Page, app_url: str):
    """Dashboard should be scrollable on mobile."""
    page.set_viewport_size({"width": 375, "height": 812})

    # Login first
    page.goto(f"{app_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "TestPassword123!")
    page.click("button[type='submit']")
    page.wait_for_url("**/dashboard", timeout=10000)

    # Check that body allows scrolling (no overflow-hidden on mobile)
    overflow = page.evaluate("() => getComputedStyle(document.body).overflowY")
    assert overflow != "hidden", "Body should allow vertical scrolling on mobile"
