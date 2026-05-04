"""Test branding consistency."""

from playwright.sync_api import Page, expect

LOGIN_SHIELD_SELECTOR = (
    "svg:visible.lucide-shield, "
    "svg[data-lucide='shield']:visible, "
    "i[data-lucide='shield']:visible, "
    "svg:visible:has(path[d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'])"
)
SIDEBAR_BRAND_SHIELD_SELECTOR = (
    "a[href='/dashboard'] svg:visible:has(path[d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'])"
)


def test_favicon_exists(login_page: Page, app_url: str):
    """Favicon should reference a proper file."""
    favicon = login_page.locator("link[rel='icon']")
    expect(favicon).to_have_attribute("href", "/static/favicon.svg")


def test_shield_icon_on_login(login_page: Page):
    """Login page should have the shield icon."""
    shield = login_page.locator(LOGIN_SHIELD_SELECTOR)
    expect(shield.first).to_be_visible()


def test_shield_icon_in_sidebar(authenticated_page: Page):
    """Sidebar should use shield icon for branding."""
    sidebar = authenticated_page.get_by_test_id("sidebar")
    if sidebar.is_visible():
        shield = sidebar.locator(SIDEBAR_BRAND_SHIELD_SELECTOR)
        expect(shield.first).to_be_visible()
