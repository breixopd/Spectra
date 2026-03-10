"""Browser tests for API docs and help pages."""
import pytest
from playwright.async_api import Page

pytestmark = [pytest.mark.asyncio, pytest.mark.ui]


async def test_api_docs_loads(authenticated_page: Page):
    """API docs page loads and shows route groups."""
    await authenticated_page.goto("/docs/api")
    await authenticated_page.wait_for_selector("[data-testid='docs-sidebar']", timeout=10000)
    groups = await authenticated_page.query_selector_all("[data-testid='route-group']")
    assert len(groups) > 0


async def test_api_docs_search(authenticated_page: Page):
    """Search filters endpoints."""
    await authenticated_page.goto("/docs/api")
    search = await authenticated_page.wait_for_selector("input[placeholder*='Search']", timeout=10000)
    assert search is not None
    await search.fill("health")
    # Should filter to health-related endpoints
    await authenticated_page.wait_for_timeout(500)
    visible = await authenticated_page.query_selector_all("[data-testid='endpoint-card']:visible")
    assert len(visible) >= 1


async def test_help_page_tabs(authenticated_page: Page):
    """Help page shows all guide sections."""
    await authenticated_page.goto("/help")
    sections = ["Getting Started", "Manual Pentest", "API Access", "Services", "Plugin", "Troubleshooting"]
    for section in sections:
        assert await authenticated_page.query_selector(f"text={section}")


async def test_help_getting_started_expands(authenticated_page: Page):
    """Getting started section is expandable."""
    await authenticated_page.goto("/help")
    # Click Getting Started
    btn = await authenticated_page.query_selector("text=Getting Started")
    if btn:
        await btn.click()
        await authenticated_page.wait_for_timeout(300)
        content = await authenticated_page.text_content("body")
        assert content is not None
        assert "mission" in content.lower() or "setup" in content.lower()
