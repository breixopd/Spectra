"""Sidebar entitlement gates: API docs, manual mode, and upgrade affordances (see confirm.js + base.html)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.ui.harness.db_user import (
    create_verified_test_user,
    grant_user_plan_features,
    ui_login,
)

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _wait_for_sidebar_hydration(page: Page) -> None:
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)
    # /api/v1/auth/me must complete before [data-entitlement-gate] is processed
    page.wait_for_function(
        """() => {
            const u = document.getElementById('sidebar-username');
            return u && u.textContent && u.textContent.trim().length > 0;
        }""",
        timeout=20_000,
    )


@pytest.mark.timeout(60)
def test_api_docs_link_gated_without_api_access(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    api_link = page.locator('a[data-entitlement-gate="api_access"]')
    expect(api_link).to_have_attribute("aria-disabled", "true", timeout=5_000)
    expect(page.locator('[data-upgrade-link-for="api_access"] a[href="/profile#plan"]')).to_be_visible(timeout=5_000)


@pytest.mark.timeout(60)
def test_api_docs_link_ungated_with_api_access(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"api_access": True})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    api_link = page.locator('a[data-entitlement-gate="api_access"]')
    expect(api_link).not_to_have_attribute("aria-disabled", "true")
    expect(page.locator('[data-upgrade-link-for="api_access"]')).to_have_count(0)


@pytest.mark.timeout(60)
def test_manual_link_gated_without_manual_mode(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("user")
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    manual_link = page.locator('a[data-entitlement-gate="manual_mode"]')
    expect(manual_link).to_have_attribute("aria-disabled", "true", timeout=5_000)
    expect(page.locator('[data-upgrade-link-for="manual_mode"] a[href="/profile#plan"]')).to_be_visible(timeout=5_000)


@pytest.mark.timeout(60)
def test_manual_link_ungated_with_manual_mode(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"manual_mode": True})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    manual_link = page.locator('a[data-entitlement-gate="manual_mode"]')
    expect(manual_link).not_to_have_attribute("aria-disabled", "true")
    expect(page.locator('[data-upgrade-link-for="manual_mode"]')).to_have_count(0)


@pytest.mark.timeout(60)
def test_admin_sidebar_links_not_gated_by_plan(page: Page, app_url: str) -> None:
    username, _uid = create_verified_test_user("admin")
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    expect(page.locator('a[data-entitlement-gate="api_access"]')).not_to_have_attribute("aria-disabled", "true")
    expect(page.locator('a[data-entitlement-gate="manual_mode"]')).not_to_have_attribute("aria-disabled", "true")
