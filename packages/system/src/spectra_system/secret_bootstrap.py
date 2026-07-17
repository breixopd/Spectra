"""Bootstrap persistent secrets on first boot.

Ensures cryptographic secrets (JWT_SECRET_KEY, SECRET_KEY, SERVICE_AUTH_SECRET)
are generated once and persisted to the system_config DB table so they survive
container restarts. Uses a PostgreSQL advisory lock to prevent race conditions
when multiple replicas boot simultaneously.
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets

from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_common.config import settings
from spectra_persistence.advisory_locks import stable_lock_id
from spectra_persistence.models.config import SystemConfig

logger = logging.getLogger(__name__)

_ADVISORY_LOCK_ID = stable_lock_id("spectra_secret_bootstrap")

_MANAGED_SECRETS = {
    "JWT_SECRET_KEY": "JWT_SECRET_KEY",
    "SECRET_KEY": "SECRET_KEY",
    "SERVICE_AUTH_SECRET": "SERVICE_AUTH_SECRET",
}


async def ensure_persistent_secrets(session: AsyncSession) -> None:
    """Load or generate persistent secrets and apply them to the settings singleton.

    On first boot:
      - If the env var was explicitly set, persist that value to DB.
      - Otherwise, generate a secure random value and persist it.

    On subsequent boots:
      - Load the DB value and apply it to settings (DB is authoritative).
      - If an env var is explicitly set, it overrides the DB value and
        the new value is persisted.

    Uses pg_advisory_xact_lock to serialize first-boot across replicas.
    """
    # Acquire advisory lock to prevent race condition on first boot
    await session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _ADVISORY_LOCK_ID})

    changes = 0
    for db_key, attr_name in _MANAGED_SECRETS.items():
        env_value = os.environ.get(db_key, "").strip()
        # Also check _FILE variant (Docker Swarm secrets)
        if not env_value:
            file_path = os.environ.get(f"{db_key}_FILE", "")
            if file_path:
                try:
                    from pathlib import Path
                    env_value = Path(file_path).read_text().strip()
                except OSError:
                    env_value = ""

        # Check DB for existing value
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == db_key)
        )
        existing = result.scalar_one_or_none()

        if existing and existing.value:
            db_value = existing.value  # auto-decrypts via hybrid property
            if env_value and env_value != db_value:
                # Explicit env var overrides DB — update DB
                existing.is_secret = True
                existing.value = env_value  # auto-encrypts via hybrid property setter
                _apply_secret(attr_name, env_value)
                changes += 1
                logger.info("Secret '%s' updated from env var override", db_key)
            else:
                # DB is authoritative
                _apply_secret(attr_name, db_value)
                logger.debug("Secret '%s' loaded from DB", db_key)
        else:
            # No DB value — seed it
            if env_value:
                value_to_persist = env_value
            else:
                # Use the auto-generated value from get_settings()
                current = getattr(settings, attr_name, None)
                if isinstance(current, SecretStr):
                    value_to_persist = current.get_secret_value()
                else:
                    value_to_persist = str(current) if current else _secrets.token_urlsafe(32)

            if existing:
                existing.is_secret = True
                existing.value = value_to_persist
            else:
                session.add(SystemConfig(
                    key=db_key,
                    _value=value_to_persist,  # will be encrypted by before_insert event
                    is_secret=True,
                    description=f"Auto-managed secret: {db_key}",
                ))
            _apply_secret(attr_name, value_to_persist)
            changes += 1
            logger.info("Secret '%s' persisted to DB (first boot or new secret)", db_key)

    changes += await _ensure_jwt_keypair(session)

    await session.commit()
    if changes:
        logger.info("Secret bootstrap complete: %d secrets persisted/updated", changes)
    else:
        logger.info("Secret bootstrap complete: all secrets loaded from DB")


async def _ensure_jwt_keypair(session: AsyncSession) -> int:
    """Ensure an Ed25519 JWT signing keypair exists, generating one on first boot.

    The private/public keys are treated as a unit: if either is missing from both
    env and DB, a fresh keypair is generated and persisted. An explicit env pair
    (JWT_PRIVATE_KEY + JWT_PUBLIC_KEY) always overrides the DB. Returns the number
    of rows written.
    """
    from pathlib import Path

    def _env(key: str) -> str:
        value = os.environ.get(key, "").strip()
        if not value:
            file_path = os.environ.get(f"{key}_FILE", "")
            if file_path:
                try:
                    value = Path(file_path).read_text().strip()
                except OSError:
                    value = ""
        return value

    async def _db_row(key: str) -> SystemConfig | None:
        result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
        return result.scalar_one_or_none()

    async def _store(key: str, value: str, row: SystemConfig | None) -> None:
        if row is not None:
            row.is_secret = True
            row.value = value
        else:
            session.add(
                SystemConfig(
                    key=key,
                    _value=value,
                    is_secret=True,
                    description=f"Auto-managed secret: {key}",
                )
            )

    env_priv, env_pub = _env("JWT_PRIVATE_KEY"), _env("JWT_PUBLIC_KEY")
    priv_row, pub_row = await _db_row("JWT_PRIVATE_KEY"), await _db_row("JWT_PUBLIC_KEY")

    # Explicit env pair overrides DB.
    if env_priv and env_pub:
        changed = (not priv_row or priv_row.value != env_priv) or (not pub_row or pub_row.value != env_pub)
        if changed:
            await _store("JWT_PRIVATE_KEY", env_priv, priv_row)
            await _store("JWT_PUBLIC_KEY", env_pub, pub_row)
        _apply_secret("JWT_PRIVATE_KEY", env_priv)
        _apply_secret("JWT_PUBLIC_KEY", env_pub)
        if changed:
            logger.info("JWT signing keypair updated from env override")
            return 2
        return 0

    # Both present in DB — load them.
    if priv_row and priv_row.value and pub_row and pub_row.value:
        _apply_secret("JWT_PRIVATE_KEY", priv_row.value)
        _apply_secret("JWT_PUBLIC_KEY", pub_row.value)
        logger.debug("JWT signing keypair loaded from DB")
        return 0

    # First boot (or partial state) — generate a fresh keypair.
    from spectra_common.encryption import generate_jwt_keypair

    private_pem, public_pem = generate_jwt_keypair()
    await _store("JWT_PRIVATE_KEY", private_pem, priv_row)
    await _store("JWT_PUBLIC_KEY", public_pem, pub_row)
    _apply_secret("JWT_PRIVATE_KEY", private_pem)
    _apply_secret("JWT_PUBLIC_KEY", public_pem)
    logger.info("Generated and persisted new Ed25519 JWT signing keypair (EdDSA)")
    return 2


def _apply_secret(attr_name: str, value: str) -> None:
    """Apply a secret value to the settings singleton."""
    current = getattr(settings, attr_name, None)
    if isinstance(current, SecretStr):
        setattr(settings, attr_name, SecretStr(value))
    else:
        setattr(settings, attr_name, value)
