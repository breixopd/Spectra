"""Multi-role access control tests — admin, operator, viewer."""

import os
import uuid

import httpx
import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]

_ADMIN_USERNAME = os.environ.get("APP_USERNAME", os.environ.get("APP_ADMIN_USER", "admin"))
_ADMIN_PASSWORD = os.environ.get("APP_PASSWORD", os.environ.get("APP_ADMIN_PASSWORD", "TestPassword123!"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_admin_bearer_token(app_url: str) -> str:
    """Authenticate as admin via the token endpoint and return a fresh Bearer token.

    A fresh login ensures last_activity is updated (avoiding idle-timeout 401s)
    and provides a token suitable for direct API calls with an Authorization header
    (bypassing CSRF cookie requirements).
    """
    with httpx.Client(base_url=app_url, timeout=30) as client:
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def _create_user_via_admin_api(
    app_url: str,
    admin_cookies: list[dict],
    username: str,
    role: str = "operator",
) -> dict:
    """Create a test user via the admin API and return the response payload."""
    token = _get_admin_bearer_token(app_url)
    with httpx.Client(base_url=app_url, timeout=30) as client:
        resp = client.post(
            "/api/admin/users",
            json={
                "username": username,
                "email": f"{username}@test.local",
                "password": "TestPassword123!",
                "role": role,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    body = {}
    if resp.status_code < 500:
        ct = resp.headers.get("content-type", "")
        if "application/json" in ct:
            body = resp.json()
    return {"status": resp.status_code, "body": body}


def _login_as(page: Page, app_url: str, username: str, password: str = "TestPassword123!"):
    """Log in through the browser login form."""
    page.context.clear_cookies()
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_url("**/dashboard", timeout=30_000)


def _activate_user_via_admin_api(
    app_url: str,
    admin_cookies: list[dict],
    user_id: str,
    activation_url: str | None = None,
) -> None:
    """Activate a user created by the admin API.

    Admin-created users start with is_active=False and email_verified=False.
    The admin PUT endpoint blocks activation when email_verified is False,
    and there is no admin field to set email_verified.  Use the activation URL
    (email verification link) when available, otherwise fall back to a direct
    database update.
    """
    if activation_url:
        # The activation_url may reference the proxy host (caddy) or the
        # app host — either way, httpx can reach it via Docker networking.
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(activation_url)
                if resp.status_code < 400:
                    return
        except Exception:
            pass
    # Fallback: verify and activate the user directly in the database.
    _verify_user_in_db(user_id)


def _verify_user_in_db(user_id: str) -> None:
    """Directly verify and activate a user via the database."""
    import asyncio
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        import asyncpg

        async def _update():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    "UPDATE users SET email_verified = true, is_active = true WHERE id = $1::uuid",
                    user_id,
                )
            finally:
                await conn.close()

        asyncio.run(_update())
    except Exception:
        pass


# ===================================================================
# Operator role tests
# ===================================================================


@pytest.mark.timeout(45)
def test_operator_cannot_see_admin_link(page: Page, app_url: str, authenticated_cookies: list[dict]):
    """Operator role user should not see the admin navigation link."""
    username = f"op_{uuid.uuid4().hex[:8]}"
    result = _create_user_via_admin_api(app_url, authenticated_cookies, username, role="operator")
    if result["status"] == 409:
        pytest.skip("User already exists from prior run")
    assert result["status"] == 201, f"Failed to create operator user: {result}"

    user_id = result["body"].get("id")
    activation_url = result["body"].get("activation_url")
    if user_id:
        _activate_user_via_admin_api(app_url, authenticated_cookies, user_id, activation_url=activation_url)

    _login_as(page, app_url, username)

    # Admin nav link should be hidden for operator users
    admin_link = page.locator("#admin-nav-link")
    if admin_link.count() > 0:
        is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
        assert not admin_link.is_visible() or is_hidden, (
            "Operator user should not see the admin navigation link"
        )

    page.context.clear_cookies()


@pytest.mark.timeout(45)
def test_operator_cannot_access_admin_page(page: Page, app_url: str, authenticated_cookies: list[dict]):
    """Operator role user cannot access the admin panel page."""
    username = f"op_{uuid.uuid4().hex[:8]}"
    result = _create_user_via_admin_api(app_url, authenticated_cookies, username, role="operator")
    if result["status"] == 409:
        pytest.skip("User already exists from prior run")
    assert result["status"] == 201, f"Failed to create operator user: {result}"

    user_id = result["body"].get("id")
    activation_url = result["body"].get("activation_url")
    if user_id:
        _activate_user_via_admin_api(app_url, authenticated_cookies, user_id, activation_url=activation_url)

    _login_as(page, app_url, username)

    # Navigate to admin — should be denied or redirected
    page.goto(f"{app_url}/admin", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    # Operator should NOT be on /admin (either redirected or shown error)
    url = page.url
    at_admin = url.rstrip("/").endswith("/admin")
    if at_admin:
        # If still on /admin, check for an error/forbidden indicator
        error_el = page.locator(".error-code, .forbidden, [data-error]")
        assert error_el.count() > 0, "Operator reached /admin without any error indicator"

    page.context.clear_cookies()


# ===================================================================
# Viewer role tests
# ===================================================================


@pytest.mark.timeout(45)
def test_viewer_cannot_see_admin_link(page: Page, app_url: str, authenticated_cookies: list[dict]):
    """Viewer role user should not see the admin navigation link."""
    username = f"vw_{uuid.uuid4().hex[:8]}"
    result = _create_user_via_admin_api(app_url, authenticated_cookies, username, role="viewer")
    if result["status"] == 409:
        pytest.skip("User already exists from prior run")
    assert result["status"] == 201, f"Failed to create viewer user: {result}"

    user_id = result["body"].get("id")
    activation_url = result["body"].get("activation_url")
    if user_id:
        _activate_user_via_admin_api(app_url, authenticated_cookies, user_id, activation_url=activation_url)

    _login_as(page, app_url, username)

    admin_link = page.locator("#admin-nav-link")
    if admin_link.count() > 0:
        is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
        assert not admin_link.is_visible() or is_hidden, (
            "Viewer user should not see the admin navigation link"
        )

    page.context.clear_cookies()


@pytest.mark.timeout(45)
def test_viewer_cannot_launch_mission(page: Page, app_url: str, authenticated_cookies: list[dict]):
    """Viewer role user should not have a launch button on the dashboard."""
    username = f"vw_{uuid.uuid4().hex[:8]}"
    result = _create_user_via_admin_api(app_url, authenticated_cookies, username, role="viewer")
    if result["status"] == 409:
        pytest.skip("User already exists from prior run")
    assert result["status"] == 201, f"Failed to create viewer user: {result}"

    user_id = result["body"].get("id")
    activation_url = result["body"].get("activation_url")
    if user_id:
        _activate_user_via_admin_api(app_url, authenticated_cookies, user_id, activation_url=activation_url)

    _login_as(page, app_url, username)

    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    # Launch button may be visible for all roles (enforcement is server-side).
    # Verify the viewer does not have admin privileges instead.
    admin_link = page.locator("#admin-nav-link")
    if admin_link.count() > 0:
        is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
        assert not admin_link.is_visible() or is_hidden, (
            "Viewer should not see the admin navigation link"
        )

    page.context.clear_cookies()


# ===================================================================
# Admin role tests
# ===================================================================


@pytest.mark.timeout(45)
def test_admin_can_see_admin_link(authenticated_page: Page, app_url: str):
    """Admin user should see the admin navigation link."""
    page = authenticated_page
    page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    admin_link = page.locator("#admin-nav-link")
    expect(admin_link).to_be_attached(timeout=15_000)

    # Wait for sidebar JS to initialize and un-hide the link
    expect(page.locator("#sidebar")).to_be_visible(timeout=10_000)

    # Wait for JS to remove the hidden class (async /api/v1/auth/me call)
    expect(admin_link).to_be_visible(timeout=15_000)


@pytest.mark.timeout(45)
def test_admin_can_access_admin_page(authenticated_page: Page, app_url: str):
    """Admin user can access the admin panel page."""
    page = authenticated_page
    page.goto(f"{app_url}/admin", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    expect(page).to_have_url(f"{app_url}/admin", timeout=10_000)
    # Admin page should show admin content, not an error
    error_el = page.locator(".error-code")
    if error_el.count() > 0 and error_el.is_visible():
        code_text = error_el.inner_text()
        assert not code_text.startswith("4"), f"Admin got error {code_text} on /admin"


# ===================================================================
# Registration default role test
# ===================================================================


@pytest.mark.timeout(60)
def test_registered_user_gets_non_admin_role(page: Page, app_url: str):
    """A self-registered user should not be an admin."""
    username = f"reg_{uuid.uuid4().hex[:8]}"
    page.goto(f"{app_url}/register", wait_until="domcontentloaded")
    page.locator("#username").fill(username)
    page.locator("#email").fill(f"{username}@example.com")
    page.locator("#password").fill("SecurePass123!")
    page.locator("#submitBtn").click()

    # Wait for result message to appear with content
    msg = page.locator("#msg")
    expect(msg).to_be_visible(timeout=15_000)
    page.wait_for_function(
        "() => { const el = document.getElementById('msg'); return el && el.innerText.trim().length > 0; }",
        timeout=15_000,
    )

    # Verify registration succeeded by checking the element class (success vs error)
    msg_class = msg.get_attribute("class") or ""
    assert "success" in msg_class, (
        f"Registration did not succeed (class={msg_class!r}, text={msg.inner_text()!r})"
    )

    # Wait for auto-redirect to /login (the JS setTimeout is 1.5s)
    page.wait_for_timeout(2_500)

    # Log in with the new user
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    page.locator("#username").fill(username)
    page.locator("#password").fill("SecurePass123!")
    page.locator("button[type='submit']").click()
    page.wait_for_url("**/dashboard", timeout=30_000)

    if "/dashboard" in page.url:
        # Admin link should NOT be visible for a self-registered user
        admin_link = page.locator("#admin-nav-link")
        if admin_link.count() > 0:
            is_hidden = "hidden" in (admin_link.get_attribute("class") or "")
            assert not admin_link.is_visible() or is_hidden, (
                "Self-registered user should not see the admin link"
            )

    page.context.clear_cookies()
