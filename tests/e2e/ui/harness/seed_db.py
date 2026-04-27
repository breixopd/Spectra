"""Seed the test database with an admin user for E2E tests."""

from __future__ import annotations

import asyncio
import os

import asyncpg

from app.auth.security import get_password_hash


def plain_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


async def seed() -> None:
    dsn = plain_dsn()
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")

    conn = await asyncpg.connect(dsn)
    try:
        existing = await conn.fetchval("SELECT id FROM users WHERE username = $1", "admin")
        if existing:
            print("Admin user already exists, skipping seed.")
            return

        password_hash = get_password_hash("TestPassword123!")
        await conn.execute(
            """
            INSERT INTO users (
                id, username, email, hashed_password, role,
                is_active, is_superuser, email_verified,
                login_fail_count, created_at, updated_at
            )
            VALUES (
                gen_random_uuid(), $1, $2, $3, 'admin',
                true, true, true,
                0, now(), now()
            )
            """,
            "admin",
            "admin@test.local",
            password_hash,
        )

        await conn.execute(
            """
            INSERT INTO plans (
                id, name, display_name, features, is_active,
                max_concurrent_missions, max_api_requests_per_hour,
                max_api_requests_per_day, sandbox_max_containers,
                max_storage_mb, sort_order
            )
            VALUES (
                gen_random_uuid(), 'default', 'Default Plan',
                '{"manual_mode": true, "ai_assist": true, "reporting": true, "api_access": true, "sandbox_creation": true}'::jsonb, true,
                5, 1000, 10000, 5, 5000, 0
            )
            ON CONFLICT (name) DO NOTHING
            """
        )

        print("Seeded admin user and default plan.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
