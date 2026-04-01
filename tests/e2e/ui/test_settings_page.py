"""Test settings page UI — sandbox pool, platform, and data management sections."""

from playwright.sync_api import Page, expect


def test_settings_page_renders(authenticated_page: Page, app_url: str):
    """Settings page should render with key sections."""
    authenticated_page.goto(f"{app_url}/settings")
    expect(authenticated_page.get_by_role("heading", name="System Settings", exact=True)).to_be_visible(timeout=10000)
    expect(authenticated_page.locator("#platform").get_by_role("heading", name="Platform")).to_be_visible()
    expect(authenticated_page.get_by_role("heading", name="Data Management", exact=True)).to_be_visible()


def test_settings_sandbox_section_visible(authenticated_page: Page, app_url: str):
    """Sandbox Pool section should be visible with all controls."""
    authenticated_page.goto(f"{app_url}/settings")
    expect(authenticated_page.get_by_role("heading", name="Sandbox Pool", exact=True)).to_be_visible(timeout=10000)
    expect(authenticated_page.locator("[name='sandbox_max_containers']")).to_be_visible()
    expect(authenticated_page.locator("[name='sandbox_memory_limit']")).to_be_visible()
    expect(authenticated_page.locator("[name='sandbox_cpu_shares']")).to_be_visible()
    expect(authenticated_page.locator("[name='sandbox_max_lifetime']")).to_be_visible()


def test_settings_sandbox_status_indicator(authenticated_page: Page, app_url: str):
    """Sandbox status indicator should appear and update after settings load."""
    authenticated_page.goto(f"{app_url}/settings")
    status_dot = authenticated_page.locator("#sandbox-status-dot")
    expect(status_dot).to_be_visible(timeout=10000)
    # After loadSettings, class should change from default slate to emerald or amber
    authenticated_page.wait_for_timeout(2000)
    classes = status_dot.get_attribute("class") or ""
    assert "bg-emerald-400" in classes or "bg-amber-400" in classes, (
        f"Sandbox status dot should update to emerald or amber, got: {classes}"
    )


def test_settings_sandbox_fields_populated(authenticated_page: Page, app_url: str):
    """Sandbox fields should be populated from API on page load."""
    authenticated_page.goto(f"{app_url}/settings")
    authenticated_page.wait_for_timeout(2000)
    max_containers = authenticated_page.locator("[name='sandbox_max_containers']")
    expect(max_containers).to_be_visible(timeout=10000)
    value = max_containers.input_value()
    # Should have a numeric value (default is 10)
    assert value.isdigit(), f"Expected numeric value for max_containers, got: {value}"


def test_settings_platform_section_visible(authenticated_page: Page, app_url: str):
    """Platform section should be visible with domain and base URL fields."""
    authenticated_page.goto(f"{app_url}/settings")
    expect(authenticated_page.locator("[name='platform_domain']")).to_be_visible(timeout=10000)
    expect(authenticated_page.locator("[name='platform_base_url']")).to_be_visible()
    expect(authenticated_page.locator("[name='platform_exposed']")).to_be_attached()


def test_settings_data_management_visible(authenticated_page: Page, app_url: str):
    """Data Management section should have clear buttons."""
    authenticated_page.goto(f"{app_url}/settings")
    expect(authenticated_page.get_by_role("heading", name="Data Management", exact=True)).to_be_visible(timeout=10000)
    expect(authenticated_page.locator("text=Tool Statistics")).to_be_visible()
    expect(authenticated_page.locator("text=Mission History")).to_be_visible()
    expect(authenticated_page.locator("text=Application Cache")).to_be_visible()
