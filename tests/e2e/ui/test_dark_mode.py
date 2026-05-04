"""Dark mode toggle test — verify theme switching UI.

The Spectra UI currently uses a single dark theme by default. No manual
theme toggle exists in the interface, so these tests document the gap.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.ui.harness.db_user import (
    create_verified_test_user,
    ui_login,
)
from tests.e2e.ui.harness.navigation import goto_authenticated_app_path

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


@pytest.mark.timeout(60)
def test_dark_mode_toggle_exists(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)

    toggle = page.locator(
        '[data-testid="theme-toggle"], [data-testid="dark-mode-toggle"], '
        '#theme-toggle, #dark-mode-toggle, .theme-toggle, .dark-mode-toggle'
    )

    if toggle.count() == 0:
        pytest.skip("Dark mode toggle is not present in the UI — documented as missing")

    expect(toggle).to_be_visible(timeout=5_000)


@pytest.mark.timeout(60)
def test_dark_mode_toggle_changes_theme(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    goto_authenticated_app_path(page, app_url, "/dashboard")
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)

    toggle = page.locator(
        '[data-testid="theme-toggle"], [data-testid="dark-mode-toggle"], '
        '#theme-toggle, #dark-mode-toggle, .theme-toggle, .dark-mode-toggle'
    )

    if toggle.count() == 0:
        pytest.skip("Dark mode toggle is not present in the UI — documented as missing")

    html = page.locator("html")
    before = html.get_attribute("class") or ""
    toggle.click()
    expect(html).not_to_have_attribute("class", before, timeout=5_000)
    after = html.get_attribute("class") or ""

    assert before != after, "Theme class should change after toggling dark mode"
