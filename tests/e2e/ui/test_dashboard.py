"""Test dashboard page functionality."""

from playwright.sync_api import Page, expect


def test_dashboard_renders(authenticated_page: Page):
    """Dashboard should render with key elements."""
    expect(authenticated_page.get_by_test_id("mission-target")).to_be_visible()
    expect(authenticated_page.get_by_test_id("launch-btn")).to_be_visible()


def test_getting_started_links_to_settings(authenticated_page: Page, app_url: str):
    """Getting started card should link to settings, not API docs."""
    getting_started = authenticated_page.get_by_test_id("getting-started")
    if getting_started.is_visible():
        link = getting_started.locator("a[href='/settings']")
        expect(link).to_be_visible()


def test_buttons_have_visible_content(authenticated_page: Page):
    """All buttons should have visible text or icon content."""
    expect(authenticated_page.get_by_test_id("launch-btn")).to_be_visible()
    buttons = authenticated_page.locator("button:visible")
    count = buttons.count()
    for i in range(count):
        btn = buttons.nth(i)
        # Button should have text content or an icon
        text = btn.text_content().strip()
        has_icon = btn.locator("i, svg").count() > 0
        assert text or has_icon, f"Button {i} has no visible content"
