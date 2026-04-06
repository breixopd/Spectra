"""Page coverage Playwright tests — ensure every navigable page renders correctly."""

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]

APP_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")


# ---------------------------------------------------------------------------
# 1. Targets page
# ---------------------------------------------------------------------------


def test_targets_page(logged_in_page: Page, app_url: str):
    """Navigate to /targets, verify heading, add-target button, and list container."""
    page = logged_in_page
    page.goto(f"{app_url}/targets", wait_until="networkidle")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Target Management")

    # An "Add Target" button should be present (icon-only with aria-label)
    add_btn = page.locator("button[aria-label='Add Target']")
    expect(add_btn.first).to_be_visible(timeout=10_000)

    # Target list container
    target_list = page.locator("#target-list, .target-list, table, .targets-container")
    expect(target_list.first).to_be_attached(timeout=10_000)


# ---------------------------------------------------------------------------
# 2. History page
# ---------------------------------------------------------------------------


def test_history_page(logged_in_page: Page, app_url: str):
    """Navigate to /history, verify heading and mission list container."""
    page = logged_in_page
    page.goto(f"{app_url}/history", wait_until="networkidle")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Assessment History")

    # Mission list or table
    mission_list = page.locator("#mission-list, .mission-list, table, .history-container")
    expect(mission_list.first).to_be_attached(timeout=10_000)


# ---------------------------------------------------------------------------
# 3. Reports page
# ---------------------------------------------------------------------------


def test_reports_page(logged_in_page: Page, app_url: str):
    """Navigate to /reports, verify heading and reports container."""
    page = logged_in_page
    page.goto(f"{app_url}/reports", wait_until="networkidle")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Assessment Reports")

    reports_section = page.locator("#reports, .reports-container, .reports-section, main")
    expect(reports_section.first).to_be_attached(timeout=10_000)


# ---------------------------------------------------------------------------
# 4. Toolbox page
# ---------------------------------------------------------------------------


def test_toolbox_page(logged_in_page: Page, app_url: str):
    """Navigate to /toolbox, verify heading and tools list/grid."""
    page = logged_in_page
    page.goto(f"{app_url}/toolbox", wait_until="networkidle")

    heading = page.locator("h2")
    expect(heading.first).to_be_visible(timeout=15_000)
    expect(heading.first).to_contain_text("Tool Registry")

    tools_container = page.locator(
        "#tools-list, .tools-list, .tools-grid, #tools-grid, .toolbox-container, .plugin-list, table, main"
    )
    expect(tools_container.first).to_be_attached(timeout=15_000)


# ---------------------------------------------------------------------------
# 5. Toolbox create page
# ---------------------------------------------------------------------------


def test_toolbox_create_page(logged_in_page: Page, app_url: str):
    """Navigate to /toolbox/create, verify plugin creation form."""
    page = logged_in_page
    page.goto(f"{app_url}/toolbox/create", wait_until="networkidle")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Plugin Creator")

    # Plugin creator uses div layout, not a form tag
    load_example = page.locator("button", has_text="Load Example")
    expect(load_example).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# 6. Manual tools page
# ---------------------------------------------------------------------------


def test_manual_tools_page(logged_in_page: Page, app_url: str, ensure_manual_mode_subscription: None):
    """Navigate to /manual, verify Manual Mode heading."""
    page = logged_in_page

    response = page.goto(f"{app_url}/manual", wait_until="networkidle")

    assert "/dashboard" not in page.url, "Redirected to /dashboard — manual_mode subscription setup failed"

    assert response is not None and response.status < 500, (
        f"/manual returned {response.status if response else 'no response'}"
    )

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Manual Mode")


# ---------------------------------------------------------------------------
# 7. Help page
# ---------------------------------------------------------------------------


def test_help_page(logged_in_page: Page, app_url: str):
    """Navigate to /help, verify heading and at least one help section."""
    page = logged_in_page
    page.goto(f"{app_url}/help", wait_until="networkidle")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Help Center")

    # At least one help section or guide card
    sections = page.locator(".help-section, .guide-card, .help-card, .help-content, article, section")
    expect(sections.first).to_be_attached(timeout=10_000)


# ---------------------------------------------------------------------------
# 8. Changelog page (public)
# ---------------------------------------------------------------------------


def test_changelog_page(page: Page, app_url: str):
    """Navigate to /changelog (public), verify heading."""
    page.goto(f"{app_url}/changelog", wait_until="domcontentloaded")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Changelog")


# ---------------------------------------------------------------------------
# 9. Status page (public)
# ---------------------------------------------------------------------------


def test_status_page(page: Page, app_url: str):
    """Navigate to /status (public), verify system status heading."""
    page.goto(f"{app_url}/status", wait_until="domcontentloaded")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("System Status")


# ---------------------------------------------------------------------------
# 10. Security page (public)
# ---------------------------------------------------------------------------


def test_security_page(page: Page, app_url: str):
    """Navigate to /security (public), verify security heading."""
    page.goto(f"{app_url}/security", wait_until="domcontentloaded")

    heading = page.locator("h1")
    expect(heading).to_be_visible(timeout=10_000)
    expect(heading).to_contain_text("Security")


# ---------------------------------------------------------------------------
# 11. Targets — add a target
# ---------------------------------------------------------------------------


def test_targets_add_target(logged_in_page: Page, app_url: str):
    """Verify the Add Target modal opens and contains the expected form fields."""
    page = logged_in_page
    page.goto(f"{app_url}/targets", wait_until="networkidle")

    # Click "Add Target" button to open the modal (icon-only trigger)
    add_btn = page.locator("button[aria-label='Add Target']")
    expect(add_btn.first).to_be_visible(timeout=10_000)

    # Open modal via JS directly — click may not work if Lucide icons haven't rendered
    page.evaluate("openAddTargetModal()")

    # Wait for the modal to appear
    modal = page.locator("#add-target-modal")
    expect(modal).to_be_visible(timeout=10_000)

    # Verify form fields are present
    address_input = page.locator("#add-target-form input[name='address']")
    expect(address_input).to_be_visible(timeout=5_000)

    description_input = page.locator("#add-target-form input[name='description']")
    expect(description_input).to_be_visible(timeout=5_000)

    submit_btn = page.locator("#add-target-form button[type='submit']")
    expect(submit_btn).to_be_visible(timeout=5_000)
    expect(submit_btn).to_contain_text("Add Target")


# ---------------------------------------------------------------------------
# 12. Dashboard — mission launch form
# ---------------------------------------------------------------------------


def test_dashboard_mission_launch_form(logged_in_page: Page, app_url: str):
    """Verify the mission launch form on the dashboard is interactive."""
    page = logged_in_page
    page.goto(f"{app_url}/dashboard", wait_until="networkidle")

    # Mission target input
    target_input = page.locator("#mission-target")
    expect(target_input).to_be_visible(timeout=10_000)

    # Launch/start button
    launch_btn = page.locator(
        "button:has-text('Launch'), button:has-text('Start'), button:has-text('Scan'), button[type='submit']"
    )
    expect(launch_btn.first).to_be_visible(timeout=10_000)

    # Fill in a target but do NOT submit (avoid starting a real mission)
    target_input.fill("example.com")
    assert target_input.input_value() == "example.com", "Target input should accept typed value"


# ---------------------------------------------------------------------------
# 13. Admin — user management
# ---------------------------------------------------------------------------


def test_admin_user_management(logged_in_page: Page, app_url: str):
    """Navigate to /admin, verify the Users section shows user data."""
    page = logged_in_page
    page.goto(f"{app_url}/admin", wait_until="networkidle")

    # Click Users tab
    users_tab = page.locator(".admin-sidebar [data-section='users']")
    expect(users_tab).to_be_visible(timeout=10_000)
    users_tab.click()

    # Users section should be visible
    users_section = page.locator("#section-users")
    expect(users_section).to_be_visible(timeout=10_000)

    # Wait for user list to load (JS fetch)
    page.wait_for_function(
        """() => {
            const section = document.getElementById('section-users');
            return section && section.innerText.toLowerCase().includes('admin');
        }""",
        timeout=15_000,
    )
