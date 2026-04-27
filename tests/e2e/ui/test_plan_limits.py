"""Plan limitation tests — verify UI gating and upgrade prompts per subscription tier."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.ui.harness.db_user import (
    create_verified_test_user,
    grant_user_plan_features,
    ui_login,
)
from tests.e2e.ui.harness.navigation import goto_authenticated_app_path

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _wait_for_sidebar_hydration(page: Page) -> None:
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)
    page.wait_for_function(
        """() => {
            const u = document.getElementById('sidebar-username');
            return u && u.textContent && u.textContent.trim().length > 0;
        }""",
        timeout=20_000,
    )


def _assert_link_gated(page: Page, href: str, feature: str) -> None:
    link = page.locator(f'a[href="{href}"]')
    expect(link).to_have_attribute("aria-disabled", "true", timeout=5_000)
    expect(page.locator(f'[data-upgrade-link-for="{feature}"] a[href="/profile#plan"]')).to_be_visible(timeout=5_000)


def _assert_link_ungated(page: Page, href: str, feature: str) -> None:
    link = page.locator(f'a[href="{href}"]')
    expect(link).not_to_have_attribute("aria-disabled", "true")
    expect(page.locator(f'[data-upgrade-link-for="{feature}"]')).to_have_count(0)


@pytest.mark.timeout(60)
def test_free_plan_api_docs_gated(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"api_access": False})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    _assert_link_gated(page, "/docs/api", "api_access")


@pytest.mark.timeout(60)
def test_free_plan_manual_tools_gated(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"manual_mode": False})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    _assert_link_gated(page, "/manual", "manual_mode")


@pytest.mark.timeout(60)
def test_free_plan_shows_upgrade_prompts(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {
        "api_access": False,
        "manual_mode": False,
        "custom_plugins": False,
        "advanced_reporting": False,
    })
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    expect(page.locator('[data-upgrade-link-for="api_access"]')).to_be_visible(timeout=5_000)
    expect(page.locator('[data-upgrade-link-for="manual_mode"]')).to_be_visible(timeout=5_000)


@pytest.mark.timeout(60)
def test_free_plan_cannot_access_api_docs_page(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"api_access": False})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/docs/api", wait_until="domcontentloaded")

    url = page.url
    if url.rstrip("/").endswith("/docs/api"):
        error_el = page.locator(".error-code, .forbidden, [data-error], .upgrade-prompt")
        assert error_el.count() > 0, "Free user reached /docs/api without gating indicator"
    else:
        assert "/dashboard" in url or "/profile" in url, f"Unexpected redirect for free user: {url}"


@pytest.mark.timeout(60)
def test_free_plan_cannot_access_manual_tools_page(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"manual_mode": False})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/manual", wait_until="domcontentloaded")

    url = page.url
    if url.rstrip("/").endswith("/manual"):
        error_el = page.locator(".error-code, .forbidden, [data-error], .upgrade-prompt")
        assert error_el.count() > 0, "Free user reached /manual without gating indicator"
    else:
        assert "/dashboard" in url or "/profile" in url, f"Unexpected redirect for free user: {url}"


@pytest.mark.timeout(60)
def test_pro_plan_can_access_standard_features(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {
        "api_access": True,
        "manual_mode": True,
        "advanced_reporting": True,
        "custom_plugins": True,
        "rag_enabled": True,
        "export_pdf": True,
    })
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    _assert_link_ungated(page, "/docs/api", "api_access")
    _assert_link_ungated(page, "/manual", "manual_mode")

    for path in ["/dashboard", "/history", "/targets", "/reports", "/settings"]:
        goto_authenticated_app_path(page, app_url, path)
        expect(page).to_have_url(f"{app_url}{path}", timeout=15_000)
        error_el = page.locator(".error-code")
        if error_el.count() > 0 and error_el.is_visible():
            code_text = error_el.inner_text()
            assert not code_text.startswith("4"), f"Pro user got error {code_text} on {path}"


@pytest.mark.timeout(60)
def test_enterprise_plan_can_access_team_features(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {
        "api_access": True,
        "manual_mode": True,
        "advanced_reporting": True,
        "custom_plugins": True,
        "rag_enabled": True,
        "export_pdf": True,
        "team_collaboration": True,
        "priority_support": True,
        "byok": True,
    })
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    _assert_link_ungated(page, "/docs/api", "api_access")
    _assert_link_ungated(page, "/manual", "manual_mode")

    for path in ["/dashboard", "/history", "/targets", "/reports", "/settings"]:
        goto_authenticated_app_path(page, app_url, path)
        expect(page).to_have_url(f"{app_url}{path}", timeout=15_000)
        error_el = page.locator(".error-code")
        if error_el.count() > 0 and error_el.is_visible():
            code_text = error_el.inner_text()
            assert not code_text.startswith("4"), f"Enterprise user got error {code_text} on {path}"


@pytest.mark.timeout(60)
def test_enterprise_team_collab_ungated(page: Page, app_url: str) -> None:
    username, user_id = create_verified_test_user("user")
    grant_user_plan_features(user_id, {"team_collaboration": True})
    ui_login(page, app_url, username)
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    _wait_for_sidebar_hydration(page)

    expect(page.locator('[data-upgrade-link-for="team_collaboration"]')).to_have_count(0)
