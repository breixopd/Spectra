"""Test branding consistency."""

from playwright.sync_api import Page, expect


def test_favicon_exists(login_page: Page, app_url: str):
    """Favicon should reference a proper file."""
    favicon = login_page.locator("link[rel='icon']")
    expect(favicon).to_have_attribute("href", "/static/favicon.svg")


def test_shield_icon_on_login(login_page: Page):
    """Login page should have the shield icon."""
    shield = login_page.locator(".fa-shield-halved")
    expect(shield.first).to_be_visible()


def test_shield_icon_in_sidebar(authenticated_page: Page):
    """Sidebar should use shield icon for branding."""
    sidebar = authenticated_page.locator("#sidebar")
    if sidebar.is_visible():
        shield = sidebar.locator(".fa-shield-halved")
        expect(shield.first).to_be_visible()
