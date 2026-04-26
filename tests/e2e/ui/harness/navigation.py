"""Stable Playwright navigation — prefer domcontentloaded + shell visibility over networkidle."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def goto_authenticated_app_path(page: Page, app_url: str, path: str) -> None:
    """Navigate to an in-app path and wait for the dashboard shell (#sidebar)."""
    if not path.startswith("/"):
        path = f"/{path}"
    page.goto(f"{app_url}{path}", wait_until="domcontentloaded")
    expect(page.locator("#sidebar")).to_be_visible(timeout=20_000)
