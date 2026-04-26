"""Browser tests for API docs and help pages."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.ui]


def test_api_docs_loads(authenticated_page: Page, app_url: str):
    """API docs page loads and shows route groups."""
    authenticated_page.goto(f"{app_url}/docs/api", wait_until="networkidle")
    sidebar = authenticated_page.locator(".doc-sidebar")
    expect(sidebar).to_be_visible(timeout=15_000)
    groups = authenticated_page.locator(".group-btn")
    expect(groups.first).to_be_visible(timeout=15_000)


def test_api_docs_search(authenticated_page: Page, app_url: str):
    """Search filters endpoints."""
    authenticated_page.goto(f"{app_url}/docs/api", wait_until="networkidle")
    search = authenticated_page.get_by_test_id("api-docs-search")
    expect(search).to_be_visible(timeout=15_000)
    search.fill("health")
    # Should filter to health-related endpoints
    visible = authenticated_page.locator(".endpoint-card:visible")
    expect(visible.first).to_be_visible(timeout=10_000)


def test_help_page_tabs(authenticated_page: Page, app_url: str):
    """Help page shows all guide sections."""
    authenticated_page.goto(f"{app_url}/help", wait_until="networkidle")
    sections = ["Getting Started", "Manual Pentest", "API Access", "Services", "Plugins", "Troubleshooting"]
    for section in sections:
        expect(authenticated_page.locator(f"text={section}").first).to_be_visible(timeout=15_000)


def test_help_getting_started_expands(authenticated_page: Page, app_url: str):
    """Getting started section is expandable."""
    authenticated_page.goto(f"{app_url}/help", wait_until="networkidle")
    # Click Getting Started
    btn = authenticated_page.locator("text=Getting Started").first
    btn.click()
    authenticated_page.wait_for_load_state("domcontentloaded")
    content = authenticated_page.text_content("body")
    assert content is not None
    assert "mission" in content.lower() or "setup" in content.lower()
