"""Create users, assign plans, and log in for UI tests (PostgreSQL + Playwright)."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid

import asyncpg
import pytest
from playwright.sync_api import Page

from spectra_platform.auth.security import get_password_hash

DEFAULT_TEST_PASSWORD = "TestPassword123!"


def run_async_in_thread(coro) -> None:
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


def plain_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def reset_user_login_state(username: str) -> None:
    dsn = plain_dsn()
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

    run_async_in_thread(_update())


def create_verified_test_user(role: str = "user") -> tuple[str, str]:
    """Insert an active, verified test user. Returns (username, user_id)."""
    username = f"e2e_{role}_{uuid.uuid4().hex[:8]}"
    dsn = plain_dsn()
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
                    get_password_hash(DEFAULT_TEST_PASSWORD),
                    role,
                    role == "admin",
                )
            )
        finally:
            await conn.close()

    result: dict[str, str] = {}

    async def _capture() -> None:
        result["user_id"] = await _insert()

    run_async_in_thread(_capture())
    return username, result["user_id"]


def grant_user_plan_features(user_id: str, features: dict[str, bool]) -> None:
    """Create a throwaway plan with JSON features and assign via subscriptions."""
    dsn = plain_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL not set")

    async def _update() -> None:
        conn = await asyncpg.connect(dsn)
        try:
            plan_name = f"e2e_plan_{uuid.uuid4().hex[:8]}"
            plan_id = await conn.fetchval(
                """
                INSERT INTO plans (
                    id, name, display_name, features, is_active,
                    is_default,
                    max_concurrent_missions, max_api_requests_per_hour,
                    max_api_requests_per_day, sandbox_max_containers,
                    max_storage_mb, sort_order
                )
                VALUES (
                    gen_random_uuid(), $1, $1, $2::jsonb, true,
                    false,
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

    run_async_in_thread(_update())


def ui_login(page: Page, app_url: str, username: str, password: str = DEFAULT_TEST_PASSWORD) -> None:
    reset_user_login_state(username)
    page.context.clear_cookies()
    page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_url("**/dashboard", timeout=30_000)
