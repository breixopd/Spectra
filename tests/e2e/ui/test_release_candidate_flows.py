"""Release-candidate browser coverage for roles, entitlements, and error paths."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid

import asyncpg
import httpx
import pytest
from playwright.sync_api import Browser, Page, expect

from app.core.security import get_password_hash

pytestmark = [pytest.mark.e2e, pytest.mark.ui]

_TEST_PASSWORD = "TestPassword123!"


def _run_async(coro) -> None:
    result: dict[str, BaseException | None] = {"error": None}

    def _target() -> None:
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join(timeout=15)
    if result["error"] is not None:
        raise result["error"]
    if thread.is_alive():
        raise TimeoutError("Timed out while preparing browser test database state")


def _plain_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _reset_login_state(username: str) -> None:
    dsn = _plain_dsn()
    if not dsn:
        return

    async def _update() -> None:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                """
                UPDATE users
                SET login_fail_count = 0,
                    locked_until = NULL,
                    last_activity = NOW()
                WHERE username = $1
                """,
                username,
            )
        finally:
            await conn.close()

    _run_async(_update())


def _create_user(_app_url: str, role: str = "user") -> tuple[str, str]:
    username = f"rc_{role}_{uuid.uuid4().hex[:8]}"
    dsn = _plain_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL not set")

    async def _insert() -> str:
        conn = await asyncpg.connect(dsn)
        try:
            return str(
                await conn.fetchval(
                    """
                    INSERT INTO users (
                        id, username, email, hashed_password, role,
                        is_active, is_superuser, email_verified,
                        login_fail_count, created_at, updated_at
                    )
                    VALUES (
                        gen_random_uuid(), $1, $2, $3, $4,
                        true, $5, true,
                        0, now(), now()
                    )
                    RETURNING id::text
                    """,
                    username,
                    f"{username}@test.local",
                    get_password_hash(_TEST_PASSWORD),
                    role,
                    role == "admin",
                )
            )
        finally:
            await conn.close()

    result: dict[str, str] = {}

    async def _capture() -> None:
        result["user_id"] = await _insert()

    _run_async(_capture())
    user_id = result["user_id"]
    return username, user_id


def _grant_features(user_id: str, features: dict[str, bool]) -> None:
    dsn = _plain_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL not set")

    async def _update() -> None:
        conn = await asyncpg.connect(dsn)
        try:
            plan_name = f"rc_plan_{uuid.uuid4().hex[:8]}"
            plan_id = await conn.fetchval(
                """
                INSERT INTO plans (
                    id, name, display_name, features, is_active,
                    max_concurrent_missions, max_api_requests_per_hour,
                    max_api_requests_per_day, sandbox_max_containers,
                    max_storage_mb, sort_order
                )
                VALUES (
                    gen_random_uuid(), $1, $1, $2::jsonb, true,
                    1, 100, 1000, 1, 500, 0
                )
                RETURNING id
                """,
                plan_name,
                json.dumps(features),
            )
            await conn.execute(
                """
                INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)
                VALUES (gen_random_uuid(), $1::uuid, $2::uuid, 'active', now())
                ON CONFLICT (user_id) DO UPDATE SET plan_id = $2::uuid, status = 'active'
                """,
                user_id,
                plan_id,
            )
        finally:
            await conn.close()

    _run_async(_update())


def _login(page: Page, app_url: str, username: str, password: str = _TEST_PASSWORD) -> None:
    _reset_login_state(username)
    page.context.clear_cookies()
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_url("**/dashboard", timeout=30_000)


@pytest.mark.timeout(60)
def test_api_docs_denied_without_api_access(page: Page, app_url: str):
    username, _user_id = _create_user(app_url, role="user")
    _login(page, app_url, username)

    response = page.goto(f"{app_url}/docs/api", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 403
    expect(page.locator(".error-code")).to_contain_text("403", timeout=10_000)
    expect(page.locator("body")).to_contain_text("API documentation requires", timeout=10_000)


@pytest.mark.timeout(60)
def test_api_docs_hides_admin_routes_for_api_access_user(page: Page, app_url: str):
    username, user_id = _create_user(app_url, role="user")
    _grant_features(user_id, {"api_access": True})
    _login(page, app_url, username)

    page.goto(f"{app_url}/docs/api", wait_until="networkidle")

    expect(page.locator(".doc-sidebar")).to_be_visible(timeout=15_000)
    expect(page.locator(".endpoint-card").first).to_be_visible(timeout=15_000)
    assert page.locator(".group-btn[data-group='admin']").count() == 0
    assert page.locator(".endpoint-card[data-path*='/api/admin/']").count() == 0
    assert page.locator(".endpoint-card[data-path*='/api/v1/system/']").count() == 0


@pytest.mark.timeout(60)
def test_manual_mode_redirects_without_entitlement(page: Page, app_url: str):
    username, _user_id = _create_user(app_url, role="user")
    _login(page, app_url, username)

    page.goto(f"{app_url}/manual", wait_until="domcontentloaded")

    page.wait_for_url("**/dashboard", timeout=15_000)
    expect(page.locator("#sidebar")).to_be_visible(timeout=10_000)


@pytest.mark.timeout(60)
def test_non_admin_plugin_creator_redirects_to_toolbox(page: Page, app_url: str):
    username, _user_id = _create_user(app_url, role="user")
    _login(page, app_url, username)

    page.goto(f"{app_url}/toolbox/create", wait_until="domcontentloaded")

    page.wait_for_url("**/toolbox", timeout=15_000)
    expect(page.locator("body")).to_contain_text("Tool", timeout=15_000)


@pytest.mark.timeout(60)
def test_staff_mission_launch_denied_by_api(page: Page, app_url: str):
    username, _user_id = _create_user(app_url, role="staff")
    _login(page, app_url, username)

    # Staff users can view mission surfaces, but must not be able to create missions.
    with httpx.Client(base_url=app_url, timeout=30) as client:
        response = client.post(
            "/api/v1/auth/token",
            data={"username": username, "password": _TEST_PASSWORD},
        )
        response.raise_for_status()
        staff_token = response.json()["access_token"]
        launch = client.post(
            "/api/v1/missions",
            headers={"Authorization": f"Bearer {staff_token}"},
            json={
                "target": "127.0.0.1",
                "directive": "Do not run; permission regression check",
                "authorization_confirmed": True,
            },
        )

    assert launch.status_code == 403, launch.text


@pytest.mark.timeout(45)
def test_invalid_shell_session_returns_clear_404(page: Page, app_url: str):
    username, _user_id = _create_user(app_url, role="user")
    _login(page, app_url, username)

    response = page.goto(f"{app_url}/shell/{uuid.uuid4()}", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 404
    expect(page.locator("body")).to_contain_text("Session not found or inactive", timeout=10_000)


@pytest.mark.timeout(45)
def test_auth_redirect_without_suppression(browser: Browser, app_url: str):
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
        page.wait_for_url("**/login", timeout=15_000)
        expect(page.locator("#username")).to_be_visible(timeout=10_000)
    finally:
        context.close()

