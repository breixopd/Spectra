"""Browser-backed acceptance tests for the supported React operator workspace."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    return errors


def test_login_and_shell_are_operational(page: Page, app_url: str, admin_credentials: dict[str, str]) -> None:
    """The public login flow establishes a session and renders the operator shell."""
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    page.locator("#username").fill(admin_credentials["username"])
    page.locator("#password").fill(admin_credentials["password"])
    with page.expect_response(lambda response: "/api/v1/auth/token" in response.url, timeout=60_000) as event:
        page.get_by_role("button", name="Sign in", exact=True).click()
    assert event.value.ok
    page.wait_for_url(re.compile(r".*/dashboard/?(?:\?.*)?$"), timeout=60_000)
    expect(page.get_by_role("heading", name="Mission Control", exact=True)).to_be_visible(timeout=30_000)
    expect(page.locator("aside nav a[href='/missions']")).to_be_visible()

    errors = _console_errors(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Mission Control", exact=True)).to_be_visible(timeout=30_000)
    assert not errors, f"Browser console errors: {errors}"


def test_logout_returns_to_the_login_boundary(authenticated_page: Page, app_url: str) -> None:
    """Signing out clears the session and routes the operator back to the public boundary."""
    page = authenticated_page
    expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()
    with page.expect_response(lambda response: "/api/v1/auth/logout" in response.url, timeout=60_000) as event:
        page.get_by_role("button", name="Sign out", exact=True).click()
    assert event.value.ok
    page.wait_for_url(re.compile(r".*/login/?(?:\?.*)?$"), timeout=30_000)
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()


def test_command_palette_and_lazy_workspace_routes(authenticated_page: Page, app_url: str) -> None:
    """Keyboard navigation and every supported lazy workspace route remain usable."""
    page = authenticated_page
    errors = _console_errors(page)

    page.keyboard.press("ControlOrMeta+K")
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="Command palette", exact=True)).to_be_visible()
    command_input = dialog.get_by_placeholder("Type a destination…")
    command_input.fill("Missions")
    command_input.press("Enter")
    expect(page).to_have_url(f"{app_url}/missions", timeout=30_000)
    expect(page.get_by_role("heading", name="Missions", exact=True)).to_be_visible(timeout=30_000)

    for path, heading in (
        ("/findings", "Findings"),
        ("/evidence", "Evidence Browser"),
        ("/reports", "Reports"),
        ("/tools", "Tools"),
        ("/settings", "Settings"),
        ("/attack-graph", "Attack Graph"),
    ):
        page.goto(f"{app_url}{path}", wait_until="domcontentloaded")
        expect(page).to_have_url(f"{app_url}{path}", timeout=30_000)
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(timeout=30_000)

    assert not errors, f"Browser console errors: {errors}"


def test_authenticated_product_guide_and_api_docs(authenticated_page: Page, app_url: str) -> None:
    """Authenticated operators can reach the guide and private Swagger surface."""
    page = authenticated_page

    help_response = page.goto(f"{app_url}/help", wait_until="domcontentloaded")
    assert help_response is not None and help_response.ok
    expect(page.get_by_role("heading", name="Getting Started", exact=True)).to_be_visible()

    docs_response = page.goto(f"{app_url}/docs/api", wait_until="domcontentloaded")
    assert docs_response is not None and docs_response.ok
    expect(page).to_have_title(re.compile("API Documentation"))
    # The isolated runner does not load Swagger's external UI bundle, but the
    # authenticated HTML shell and its private OpenAPI URL must be present.
    expect(page.locator("#swagger-ui")).to_be_attached()
    expect(page.locator("script[src*='swagger-ui']")).to_have_count(1)


def test_mobile_navigation_has_no_horizontal_overflow(authenticated_page: Page, app_url: str) -> None:
    """The real mobile navigation is reachable and the workspace fits a phone viewport."""
    page = authenticated_page
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Mission Control", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Open navigation").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="Navigation", exact=True)).to_be_visible()
    dialog.get_by_role("link", name=re.compile("Missions")).click()
    expect(page).to_have_url(f"{app_url}/missions", timeout=30_000)
    expect(page.get_by_role("heading", name="Missions", exact=True)).to_be_visible(timeout=30_000)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
