"""Stable Playwright navigation — prefer domcontentloaded + shell visibility over networkidle."""

from __future__ import annotations

from playwright.sync_api import Error, Page, expect


def goto_authenticated_app_path(page: Page, app_url: str, path: str) -> None:
    """Navigate to an in-app path and wait for the dashboard shell (#sidebar)."""
    if not path.startswith("/"):
        path = f"/{path}"
    target_url = f"{app_url}{path}"
    for _attempt in range(3):
        try:
            page.goto(target_url, wait_until="domcontentloaded")
        except Error as exc:
            message = str(exc)
            interrupted = "is interrupted by another navigation" in message
            aborted = "net::ERR_ABORTED" in message
            if not (aborted or interrupted):
                raise
        if path in page.url:
            break
        page.wait_for_timeout(500)
    assert path in page.url, f"expected to reach {path}, got {page.url}"
    expect(page.get_by_test_id("sidebar")).to_be_visible(timeout=20_000)
