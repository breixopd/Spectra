"""Playwright UI test fixtures."""

import os
import urllib.parse
from typing import Any, cast

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect


def pytest_collection_modifyitems(items):
    """Use thread-based timeout for all UI tests.

    The default signal method cannot interrupt Playwright's native browser
    process, causing tests to hang indefinitely when a Playwright call blocks.
    """
    for item in items:
        existing = item.get_closest_marker("timeout")
        timeout_val = existing.args[0] if existing and existing.args else 60
        # Remove original timeout markers — signal method cannot interrupt Playwright
        item.own_markers = [m for m in item.own_markers if m.name != "timeout"]
        item.add_marker(pytest.mark.timeout(timeout_val, method="thread"))


APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
ADMIN_USERNAME = os.environ.get("APP_USERNAME", os.environ.get("APP_ADMIN_USER", "admin"))
ADMIN_PASSWORD = os.environ.get("APP_PASSWORD", os.environ.get("APP_ADMIN_PASSWORD", "TestPassword123!"))
ALLOWED_APP_URL_SCHEMES = {"http", "https"}
AUTHENTICATED_PAGE_TIMEOUT_MS = 15_000
AUTH_TOKEN_ENDPOINT = "/api/v1/auth/token"
ACCESS_COOKIE_KEY = "access_token"
REFRESH_COOKIE_KEY = "refresh_token"
ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
AUTH_COOKIE_SAMESITE = "Strict"


def normalize_app_base_url(app_base_url: str) -> str:
    """Normalize the configured app base URL and reject unsafe schemes."""
    parsed_url = urllib.parse.urlsplit(app_base_url)
    if parsed_url.scheme not in ALLOWED_APP_URL_SCHEMES or not parsed_url.netloc:
        raise ValueError("APP_BASE_URL must use http or https and include a host")
    return urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path.rstrip("/"), "", ""))


@pytest.fixture(scope="session")
def app_url():
    """Base URL for the application."""
    return normalize_app_base_url(APP_BASE_URL)


@pytest.fixture(scope="session")
def authenticated_cookies(app_url: str) -> list[dict[str, object]]:
    """Authenticate once and reuse the issued auth cookies across UI tests."""
    _reset_user_activity(ADMIN_USERNAME)
    return _build_auth_cookies(app_url)


def _refresh_auth_cookies(app_url: str) -> list[dict[str, object]]:
    """Re-authenticate and return fresh cookies (called when stale)."""
    _reset_user_activity(ADMIN_USERNAME)
    return _build_auth_cookies(app_url)


def _assert_authenticated_dashboard(page: Page, app_url: str):
    """Assert the browser reached the authenticated dashboard shell."""
    expect(page).to_have_url(f"{app_url}/dashboard", timeout=AUTHENTICATED_PAGE_TIMEOUT_MS)
    expect(page.locator("#sidebar")).to_be_visible(timeout=AUTHENTICATED_PAGE_TIMEOUT_MS)


def _build_auth_cookies(app_url: str) -> list[dict[str, object]]:
    """Authenticate via the token endpoint, retrying on transient failure."""
    import time as _time

    parsed_url = urllib.parse.urlsplit(app_url)
    if not parsed_url.hostname:
        raise ValueError("APP_BASE_URL must resolve to a hostname for browser auth cookies")

    secure = parsed_url.scheme == "https"
    last_exc: Exception | None = None

    for _attempt in range(3):
        try:
            with httpx.Client(base_url=app_url, timeout=10) as client:
                response = client.post(
                    AUTH_TOKEN_ENDPOINT,
                    data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
                )

            if response.status_code != 200:
                raise RuntimeError(
                    f"UI auth fixture token login failed with HTTP {response.status_code}: {response.text.strip()}"
                )

            payload = response.json()
            if payload.get("mfa_required"):
                raise RuntimeError("UI auth fixture reached MFA instead of issuing a full auth token pair.")

            access_token = response.cookies.get(ACCESS_COOKIE_KEY)
            refresh_token = response.cookies.get(REFRESH_COOKIE_KEY)
            if not access_token or not refresh_token:
                raise RuntimeError("UI auth fixture token login did not set both auth cookies.")

            return [
                {
                    "name": ACCESS_COOKIE_KEY,
                    "value": access_token,
                    "domain": parsed_url.hostname,
                    "path": ACCESS_COOKIE_PATH,
                    "httpOnly": True,
                    "secure": secure,
                    "sameSite": AUTH_COOKIE_SAMESITE,
                },
                {
                    "name": REFRESH_COOKIE_KEY,
                    "value": refresh_token,
                    "domain": parsed_url.hostname,
                    "path": REFRESH_COOKIE_PATH,
                    "httpOnly": True,
                    "secure": secure,
                    "sameSite": AUTH_COOKIE_SAMESITE,
                },
            ]
        except Exception as exc:
            last_exc = exc
            _time.sleep(2)

    raise last_exc  # type: ignore[misc]


def _reset_user_activity(username: str) -> None:
    """Reset the user's last_activity to NOW so the session idle timeout
    doesn't reject API requests during the test run."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        import asyncio

        import asyncpg

        async def _update():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    "UPDATE users SET last_activity = NOW() WHERE username = $1",
                    username,
                )
            finally:
                await conn.close()

        asyncio.run(_update())
    except Exception:
        pass


@pytest.fixture(scope="session")
def shared_context(browser: Browser):
    """Single browser context shared by every test.

    Chromium has a practical limit on how many contexts can be created and
    destroyed in one browser process before cookie handling becomes unreliable.
    Using one shared context avoids this entirely.
    """
    context = browser.new_context()
    context.set_default_navigation_timeout(30_000)
    context.set_default_timeout(15_000)

    # Suppress API 401→/login redirects from spectraApi that race with
    # Playwright navigations (causing net::ERR_ABORTED).  The init script
    # wraps window.fetch BEFORE page scripts load: any API 401 is silently
    # converted to 200 so the client treats it as a soft failure.
    # A deferred block patches the WebSocket close handler too.
    context.add_init_script("""
        (function() {
            var _origFetch = window.fetch;
            window.fetch = function(url, options) {
                return _origFetch.apply(this, arguments).then(function(response) {
                    if (response.status === 401) {
                        var u = (typeof url === 'string') ? url : '';
                        if (u.indexOf('/api/') !== -1) {
                            return new Response(
                                JSON.stringify({data: null, detail: 'auth-suppressed'}),
                                {status: 200, statusText: 'OK',
                                 headers: {'Content-Type': 'application/json'}}
                            );
                        }
                    }
                    return response;
                });
            };
        })();
        setTimeout(function() {
            if (typeof socket !== 'undefined' && socket && socket.onclose) {
                var _orig = socket.onclose;
                socket.onclose = function(e) {
                    if (e && e.code === 4001) return;
                    _orig.call(socket, e);
                };
            }
        }, 0);
    """)

    yield context
    context.close()


@pytest.fixture
def page(shared_context: BrowserContext):
    """Override pytest-playwright's ``page`` fixture.

    Uses the shared session-scoped context and clears cookies between tests
    so unauthenticated pages start clean.
    """
    shared_context.clear_cookies()
    p = shared_context.new_page()
    yield p
    if not p.is_closed():
        p.close()


@pytest.fixture
def setup_page(page: Page, app_url: str):
    """Navigate to setup page."""
    page.goto(f"{app_url}/setup")
    return page


@pytest.fixture
def login_page(page: Page, app_url: str):
    """Navigate to login page."""
    page.goto(f"{app_url}/login")
    return page


@pytest.fixture
def authenticated_page(
    shared_context: BrowserContext,
    authenticated_cookies: list[dict[str, object]],
    app_url: str,
):
    """Return a fresh authenticated page backed by reused server auth cookies.

    If the cached session cookies have been invalidated (e.g. by a logout test),
    re-authenticate automatically to obtain fresh tokens.  Handles redirect
    loops caused by stale cookies gracefully.
    """
    # Close any orphan pages left by timed-out tests.
    for p in shared_context.pages:
        if not p.is_closed():
            try:
                p.close()
            except Exception:
                pass

    # Brief pause to let any pending keepalive responses (e.g. from logout
    # tests) settle before we re-inject auth cookies.
    import time as _t

    _t.sleep(0.3)

    cookies_to_use = authenticated_cookies
    needs_reauth = False

    # Clear stale/refreshed cookies then re-inject the canonical auth cookies.
    shared_context.clear_cookies()
    shared_context.add_cookies(cast(Any, cookies_to_use))
    _page = shared_context.new_page()

    # Navigate and wait for JS-initiated API calls (e.g. system/status) to
    # complete so any auth-triggered redirects resolve before the test body.
    try:
        _page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
        try:
            _page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        # Check if redirected to login (stale cookies).
        if "/login" in _page.url or "/dashboard" not in _page.url:
            needs_reauth = True
    except Exception:
        # ERR_TOO_MANY_REDIRECTS or other navigation errors → stale cookies.
        needs_reauth = True

    if needs_reauth:
        # Close the broken page and start fresh with new tokens.
        if not _page.is_closed():
            _page.close()

        cookies_to_use = _refresh_auth_cookies(app_url)
        # Update the session-scoped list in-place so later tests benefit.
        authenticated_cookies.clear()
        authenticated_cookies.extend(cookies_to_use)

        shared_context.clear_cookies()
        shared_context.add_cookies(cast(Any, cookies_to_use))

        # Create a new page and navigate to dashboard.  Use a retry to
        # handle the rare case where Caddy's round-robin sends the very
        # first request to a backend whose in-memory caches haven't yet
        # seen the freshly-issued token.
        _page = shared_context.new_page()
        for _nav_attempt in range(3):
            try:
                _page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
                if "/login" not in _page.url:
                    break
            except Exception:
                pass
            import time as _t2

            _t2.sleep(1)

    # Lightweight assertion: verify we reached dashboard, not login.
    assert "/login" not in _page.url, f"authenticated_page fixture failed to reach dashboard (url={_page.url})"

    yield _page
    if not _page.is_closed():
        _page.close()


@pytest.fixture
def logged_in_page(authenticated_page: Page):
    """Alias for tests that only need a logged-in browser page."""
    return authenticated_page


def _db_dsn_from_env() -> str:
    """Return a plain DSN from DATABASE_URL."""
    raw = os.environ.get("DATABASE_URL", "")
    return raw.replace("postgresql+asyncpg://", "postgresql://")


async def _seed_manual_mode(dsn: str) -> None:
    """Connect to the database and seed manual_mode plan+subscription."""
    import asyncpg  # already in requirements

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            DO $$
            DECLARE
                v_user_id UUID;
                v_plan_id UUID;
            BEGIN
                SELECT id INTO v_user_id FROM users WHERE username = $1;
                IF v_user_id IS NULL THEN
                    RAISE EXCEPTION 'User not found';
                END IF;

                INSERT INTO plans (id, name, display_name, features, is_active,
                                  max_concurrent_missions, max_api_requests_per_hour,
                                  max_api_requests_per_day, sandbox_max_containers,
                                  max_storage_mb, sort_order)
                VALUES (gen_random_uuid(), 'test_manual_mode', 'Test Manual Mode',
                        '{"manual_mode": true}'::jsonb, true, 1, 100, 1000, 1, 500, 0)
                ON CONFLICT (name) DO UPDATE SET features = '{"manual_mode": true}'::jsonb
                RETURNING id INTO v_plan_id;

                INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)
                VALUES (gen_random_uuid(), v_user_id, v_plan_id, 'active', now())
                ON CONFLICT (user_id) DO UPDATE SET plan_id = v_plan_id, status = 'active';
            END $$;
            """,
            ADMIN_USERNAME,
        )
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def ensure_manual_mode_subscription() -> None:
    """Seed the DB with a plan+subscription granting manual_mode to the admin user."""
    import asyncio
    import threading

    dsn = _db_dsn_from_env()
    if not dsn:
        pytest.skip("DATABASE_URL not set")
        return

    result: dict[str, Exception | None] = {"error": None}

    def _run() -> None:
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_seed_manual_mode(dsn))
            loop.close()
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=15)

    if result["error"]:
        pytest.skip(f"Could not seed manual_mode: {result['error']}")
