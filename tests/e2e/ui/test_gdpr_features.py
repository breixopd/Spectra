"""GDPR feature tests — data export, processing restriction, cookie consent."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


# ===================================================================
# Authenticated tests — Data & Privacy profile section
# ===================================================================


@pytest.mark.timeout(30)
def test_data_privacy_tab_visible(authenticated_page: Page, app_url: str):
    """Profile page shows Data & Privacy tab."""
    page = authenticated_page
    page.goto(f"{app_url}/profile", wait_until="domcontentloaded")
    tab = page.locator("a[data-section='data-privacy']")
    expect(tab).to_be_visible(timeout=10_000)
    tab.click()
    section = page.locator("#section-data-privacy")
    expect(section).to_be_visible(timeout=10_000)


@pytest.mark.timeout(30)
def test_download_my_data_button(authenticated_page: Page, app_url: str):
    """Data & Privacy section has Download My Data button."""
    page = authenticated_page
    page.goto(f"{app_url}/profile", wait_until="domcontentloaded")
    page.evaluate("""() => {
        document.querySelectorAll('.profile-section').forEach(s => s.classList.remove('active'));
        document.getElementById('section-data-privacy')?.classList.add('active');
    }""")
    expect(page.locator("#section-data-privacy")).to_be_visible(timeout=10_000)
    download_btn = page.locator("button", has_text="Download My Data")
    expect(download_btn).to_be_visible(timeout=10_000)


@pytest.mark.timeout(30)
def test_restrict_processing_toggle(fresh_authenticated_page: Page, app_url: str):
    """Data & Privacy section has processing restriction toggle."""
    page = fresh_authenticated_page
    page.goto(f"{app_url}/profile", wait_until="domcontentloaded")
    page.evaluate("""() => {
        document.querySelectorAll('.profile-section').forEach(s => s.classList.remove('active'));
        document.getElementById('section-data-privacy')?.classList.add('active');
    }""")
    expect(page.locator("#section-data-privacy")).to_be_visible(timeout=10_000)
    toggle = page.locator("#restrict-processing-toggle")
    expect(toggle).to_be_attached(timeout=10_000)


@pytest.mark.timeout(30)
def test_training_data_toggle(fresh_authenticated_page: Page, app_url: str):
    """Data & Privacy section has training data sharing toggle."""
    page = fresh_authenticated_page
    page.goto(f"{app_url}/profile", wait_until="domcontentloaded")
    page.evaluate("""() => {
        document.querySelectorAll('.profile-section').forEach(s => s.classList.remove('active'));
        document.getElementById('section-data-privacy')?.classList.add('active');
    }""")
    expect(page.locator("#section-data-privacy")).to_be_visible(timeout=10_000)
    toggle = page.locator("#share-training-toggle")
    expect(toggle).to_be_attached(timeout=10_000)


@pytest.mark.timeout(30)
def test_delete_account_button(fresh_authenticated_page: Page, app_url: str):
    """Data & Privacy section has Delete My Account button (do NOT click it)."""
    page = fresh_authenticated_page
    page.goto(f"{app_url}/profile", wait_until="domcontentloaded")
    page.evaluate("""() => {
        document.querySelectorAll('.profile-section').forEach(s => s.classList.remove('active'));
        document.getElementById('section-data-privacy')?.classList.add('active');
    }""")
    expect(page.locator("#section-data-privacy")).to_be_visible(timeout=10_000)
    delete_btn = page.locator("#section-data-privacy button", has_text="Delete My Account")
    expect(delete_btn).to_be_visible(timeout=10_000)


# ===================================================================
# Unauthenticated tests — Cookie consent & legal pages
# ===================================================================


@pytest.mark.timeout(30)
def test_cookie_consent_banner_appears(page: Page, app_url: str):
    """Cookie consent banner appears on first visit (no prior consent cookie)."""
    page.context.clear_cookies()
    page.goto(f"{app_url}/", wait_until="domcontentloaded")
    banner = page.locator("#cookie-consent")
    expect(banner).to_be_visible(timeout=10_000)


@pytest.mark.timeout(30)
def test_cookie_consent_accept_all(page: Page, app_url: str):
    """Accepting all cookies dismisses the banner."""
    page.context.clear_cookies()
    page.goto(f"{app_url}/", wait_until="domcontentloaded")
    banner = page.locator("#cookie-consent")
    expect(banner).to_be_visible(timeout=10_000)
    accept_btn = page.locator("button[data-cookie-consent='all']")
    accept_btn.click()
    expect(banner).to_be_hidden(timeout=5_000)


@pytest.mark.timeout(30)
def test_cookie_consent_essential_only(page: Page, app_url: str):
    """Essential-only button dismisses the banner."""
    page.context.clear_cookies()
    page.goto(f"{app_url}/", wait_until="domcontentloaded")
    banner = page.locator("#cookie-consent")
    expect(banner).to_be_visible(timeout=10_000)
    essential_btn = page.locator("button[data-cookie-consent='essential']")
    essential_btn.click()
    expect(banner).to_be_hidden(timeout=5_000)


@pytest.mark.timeout(30)
def test_cookie_preferences_link_in_footer(page: Page, app_url: str):
    """Landing page footer has Cookie Preferences link."""
    page.goto(f"{app_url}/", wait_until="domcontentloaded")
    # Dismiss banner if shown
    banner = page.locator("#cookie-consent")
    if banner.is_visible():
        page.locator("button[data-cookie-consent='all']").click()
        expect(banner).to_be_hidden(timeout=5_000)
    cookie_pref = page.locator("a", has_text="Cookie Preferences")
    expect(cookie_pref.first).to_be_visible(timeout=10_000)


@pytest.mark.timeout(30)
def test_privacy_policy_has_automated_decision_section(page: Page, app_url: str):
    """Privacy policy includes automated decision-making section (GDPR Art. 22)."""
    page.goto(f"{app_url}/legal/privacy", wait_until="domcontentloaded")
    section = page.locator("text=Automated Decision-Making")
    expect(section).to_be_visible(timeout=10_000)


@pytest.mark.timeout(30)
def test_terms_deletion_section(page: Page, app_url: str):
    """Terms of Service explains immediate account deletion."""
    page.goto(f"{app_url}/legal/terms", wait_until="domcontentloaded")
    content = page.locator("text=immediate and permanent")
    expect(content).to_be_visible(timeout=10_000)
